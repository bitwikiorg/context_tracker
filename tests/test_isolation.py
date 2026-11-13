"""Integration checks against the stdio server and real Git repositories."""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import asynccontextmanager
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = Path(__file__).resolve().parents[1] / "server.py"
A = {"openai/subject": "alice", "openai/session": "chat-a"}
B = {"openai/subject": "alice", "openai/session": "chat-b"}
OTHER_USER = {"openai/subject": "bob", "openai/session": "chat-a"}


@asynccontextmanager
async def connected(home, **settings):
    env = {**os.environ, "CONTEXT_TRACKER_HOME": str(home),
           "CONTEXT_TRACKER_LOCAL_SCOPE": "", **settings}
    parameters = StdioServerParameters(command=sys.executable, args=[str(SERVER)], env=env)
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as client:
            await client.initialize()
            yield client


async def call(client, tool, meta=None, **arguments):
    result = await client.call_tool(tool, arguments, meta=meta)
    if result.isError:
        raise AssertionError(result)
    return json.loads(result.content[0].text) if tool in ("context_read", "context_write") else (result.structuredContent or json.loads(result.content[0].text))


class IsolationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.home = Path(directory.name)
        self.root = self.home / "conversations-v1"

    async def test_conversations_and_edits(self):
        legacy = self.home / "notes"
        legacy.mkdir()
        (legacy / "current.json").write_text("legacy data")
        async with connected(self.home) as first, connected(self.home) as second:
            self.assertEqual(len((await first.list_tools()).tools), 7)
            for metadata in (None, {"openai/session": "chat-a"}, {"openai/subject": "", "openai/session": 7}):
                denied = await first.call_tool("context_read", meta=metadata)
                self.assertTrue(denied.isError)
            self.assertFalse(self.root.exists())

            empty_a, empty_b = await asyncio.gather(
                call(first, "context_read", A), call(second, "context_read", B)
            )
            self.assertEqual((empty_a["status"], empty_b["status"]), ("EMPTY", "EMPTY"))
            await call(first, "context_write", A, title="Earlier task", content="alpha")
            edited = await call(first, "context_write", A, title="Next task", content="café")
            self.assertTrue(edited["changed"])
            same = await call(first, "context_write", A, title="Next task", content="café")
            self.assertFalse(same["changed"])
            self.assertEqual((await call(first, "context_read", OTHER_USER))["status"], "EMPTY")
            self.assertEqual((await call(second, "context_read", B))["status"], "EMPTY")

            await call(second, "context_branch", B, name="research")
            await call(second, "context_write", B, title="Research", content="beta")
            self.assertEqual((await call(second, "context_tree", B))["branch"], "research")
            self.assertEqual((await call(first, "context_branches", A))["branches"], ["main"])
            self.assertTrue((await first.call_tool("context_checkout", {"name": "research"}, meta=A)).isError)
            self.assertEqual((await call(second, "context_checkout", B, name="main"))["status"], "EMPTY")
            self.assertEqual((await call(second, "context_checkout", B, name="research"))["content"], "beta")
            self.assertEqual(len((await call(first, "context_history", A))["commits"]), 3)

        async with connected(self.home) as reopened:
            self.assertEqual((await call(reopened, "context_read", A))["content"], "café")
            self.assertEqual((await call(reopened, "context_read", B))["branch"], "research")
        self.assertEqual((legacy / "current.json").read_text(), "legacy data")

    async def test_expiry_and_interrupted_write(self):
        async with connected(self.home, CONTEXT_TRACKER_IDLE_SECONDS="60") as client:
            original = await call(client, "context_write", A, title="Saved", content="alpha")
            repo = next(path for path in self.root.iterdir() if len(path.name) == 64)
            note = repo / "notes" / "current.json"
            note.write_text('{"title":"Interrupted","content":"partial"}')
            subprocess.run(["git", "-C", str(repo), "add", str(note)], check=True)
            self.assertEqual((await call(client, "context_read", A))["title"], "Saved")

            await call(client, "context_write", B, title="Separate", content="beta")
            past = time.time() - 120
            os.utime(repo, (past, past))
            self.assertEqual((await call(client, "context_read", B))["content"], "beta")
            self.assertFalse(repo.exists())
            self.assertEqual((await call(client, "context_read", A))["status"], "EMPTY")
            history = await call(client, "context_history", A)
            self.assertEqual(len(history["commits"]), 1)
            self.assertNotIn(original["commit"], str(history))

    async def test_launcher_binding(self):
        async with connected(self.home, CONTEXT_TRACKER_LOCAL_SCOPE="host-chat-a") as a:
            await call(a, "context_write", title="A", content="alpha")
        async with connected(self.home, CONTEXT_TRACKER_LOCAL_SCOPE="host-chat-b") as b:
            self.assertEqual((await call(b, "context_read"))["status"], "EMPTY")
        async with connected(self.home, CONTEXT_TRACKER_LOCAL_SCOPE="host-chat-a") as a:
            self.assertEqual((await call(a, "context_read"))["content"], "alpha")

    async def test_history_checkpoint_keeps_branch_notes(self):
        async with connected(self.home) as client:
            await call(client, "context_write", A, title="Main", content="alpha")
            await call(client, "context_branch", A, name="research")
            await call(client, "context_write", A, title="Draft", content="draft")
            repo = next(path for path in self.root.iterdir() if len(path.name) == 64)
            # Seed history to the real threshold without hundreds of MCP round trips.
            subprocess.run(
                ["sh", "-ec", 'for i in $(seq 1 253); do git commit -q --allow-empty -m "Seed $i"; done'],
                cwd=repo, check=True,
            )
            await call(client, "context_write", A, title="Research", content="beta")
            count = subprocess.check_output(["git", "-C", str(repo), "rev-list", "--count", "--all"], text=True)
            self.assertEqual(int(count), 3)
            self.assertEqual((await call(client, "context_checkout", A, name="main"))["content"], "alpha")
            self.assertEqual((await call(client, "context_checkout", A, name="research"))["content"], "beta")
