"""Conversation-scoped Git storage for Context Tracker."""
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from mcp.server.fastmcp import Context, FastMCP

ROOT = Path(os.environ.get(
    "CONTEXT_TRACKER_HOME", "~/.local/state/context-tracker-mcp"
)).expanduser().resolve() / "conversations-v1"
NOTE = "notes/current.json"
SCOPE_DIRECTORY = re.compile(r"[0-9a-f]{64}")
BRANCH_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,79}")
MAX_CONVERSATIONS = 128
MAX_BRANCHES = 16
MAX_REVISIONS = 256

mcp = FastMCP(
    "context-tracker",
    instructions="Read the current conversation's working note when relevant. "
    "Use context_write to edit or replace it as the conversation progresses.",
)


def conversation_key(ctx: Context) -> str:
    # This variable is set by a launcher dedicated to one conversation.
    local = os.environ.get("CONTEXT_TRACKER_LOCAL_SCOPE", "").strip()
    trusted_host = os.environ.get("CONTEXT_TRACKER_TRUSTED_HOST", "").strip()
    if trusted_host and local:
        raise ValueError("Configure either a trusted host or a private launcher scope")
    if trusted_host:
        meta = ctx.request_context.meta
        fields = meta.model_extra if meta else {}
        scope = fields.get("context-tracker/conversation")
        if not isinstance(scope, dict) or scope.get("host") != trusted_host:
            raise ValueError("Missing trusted conversation binding. Configure the MCP host.")
        tenant, conversation = scope.get("scope"), scope.get("id")
        if not all(isinstance(value, str) and value.strip() for value in (tenant, conversation)):
            raise ValueError("Invalid host conversation binding")
        binding = ["host", trusted_host, tenant, conversation]
    elif local:
        binding = ["launcher", local]
    else:
        meta = ctx.request_context.meta
        fields = meta.model_extra if meta else {}
        subject = fields.get("openai/subject")
        session = fields.get("openai/session")
        organization = fields.get("openai/organization")
        if not all(isinstance(value, str) and value.strip() for value in (subject, session)):
            raise ValueError("Missing trusted conversation binding. Configure the MCP host.")
        binding = ["openai", organization or "", subject, session]
    return hashlib.sha256(json.dumps(binding).encode("utf-8")).hexdigest()


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Git error")
    return result.stdout.strip()


def initialize(repo: Path) -> None:
    # The staging directory is reclaimed by the next call if this process dies.
    staging = ROOT / ".initializing"
    with tempfile.TemporaryDirectory(dir=staging) as directory:
        checkout = Path(directory) / "repo"
        checkout.mkdir(mode=0o700)
        git(checkout, "init", "-b", "main", "--template=")
        git(checkout, "config", "user.name", "Context Tracker")
        git(checkout, "config", "user.email", "context-tracker@localhost")
        git(checkout, "config", "commit.gpgsign", "false")
        git(checkout, "config", "core.hooksPath", os.devnull)
        (checkout / "notes").mkdir()
        (checkout / NOTE).write_text('{"title":"","content":""}\n', encoding="utf-8")
        git(checkout, "add", NOTE)
        git(checkout, "commit", "-m", "Initialize empty context")
        checkout.rename(repo)


@contextmanager
def checkout(ctx: Context):
    key = conversation_key(ctx)
    idle_seconds = int(os.environ.get("CONTEXT_TRACKER_IDLE_SECONDS", "86400"))
    if idle_seconds < 1:
        raise ValueError("CONTEXT_TRACKER_IDLE_SECONDS must be positive")

    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (ROOT / ".lock").open("a") as lock:
        # Cleanup and Git mutations share the lock across processes.
        fcntl.flock(lock, fcntl.LOCK_EX)
        staging = ROOT / ".initializing"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(mode=0o700)
        cutoff = time.time() - idle_seconds
        active = 0
        for directory in ROOT.iterdir():
            if not SCOPE_DIRECTORY.fullmatch(directory.name) or not directory.is_dir():
                continue
            if directory.stat().st_mtime <= cutoff:
                directory.rename(staging / directory.name)
                shutil.rmtree(staging / directory.name)
            else:
                active += 1

        repo = ROOT / key
        if not repo.exists():
            if active >= MAX_CONVERSATIONS:
                raise RuntimeError("Conversation storage is full. Wait for an inactive scope to expire.")
            initialize(repo)

        # Recover an interrupted write before allowing reads or branch switches.
        for leftover in (repo / "notes").glob(".pending-*"):
            leftover.unlink()
        if git(repo, "status", "--porcelain", "--", NOTE):
            git(repo, "restore", "--source=HEAD", "--staged", "--worktree", "--", NOTE)
        try:
            yield repo
        finally:
            os.utime(repo)


def state(repo: Path) -> dict:
    data = json.loads((repo / NOTE).read_text(encoding="utf-8"))
    return {
        "status": "ACTIVE" if data["title"] or data["content"] else "EMPTY",
        "branch": git(repo, "branch", "--show-current"),
        **data,
    }


def branch_names(repo: Path) -> list[str]:
    return git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads").splitlines()


@mcp.tool()
def context_read(ctx: Context) -> str:
    """Read this conversation's current note as JSON text."""
    with checkout(ctx) as repo:
        return json.dumps(state(repo), ensure_ascii=False)


@mcp.tool()
def context_write(title: str, content: str, ctx: Context) -> str:
    """Edit or replace this conversation's current note and commit a revision."""
    if len(title) > 120 or len(content) > 500:
        raise ValueError("Title <=120 and content <=500 characters")
    if content.strip() and not title.strip():
        raise ValueError("Title required for nonempty content")

    data = {"title": title, "content": content}
    with checkout(ctx) as repo:
        note = repo / NOTE
        if data == json.loads(note.read_text(encoding="utf-8")):
            return json.dumps({"changed": False, **state(repo)}, ensure_ascii=False)

        # Periodically checkpoint history while preserving each branch's note.
        if int(git(repo, "rev-list", "--count", "--all")) >= MAX_REVISIONS:
            checkpoint_history(repo)

        with tempfile.NamedTemporaryFile(
            "w", dir=note.parent, prefix=".pending-", delete=False, encoding="utf-8"
        ) as pending:
            json.dump(data, pending, ensure_ascii=False, indent=2)
            pending.write("\n")
        os.replace(pending.name, note)
        try:
            git(repo, "commit", "-m", "Update context", "--", NOTE)
        except RuntimeError:
            git(repo, "restore", "--source=HEAD", "--staged", "--worktree", "--", NOTE)
            raise
        return json.dumps({
            "changed": True,
            "commit": git(repo, "rev-parse", "--short", "HEAD"),
            **state(repo),
        }, ensure_ascii=False)


def checkpoint_history(repo: Path) -> None:
    """Replace old history with one baseline commit per branch."""
    refs = branch_names(repo)
    commands = ["start"]
    for name in refs:
        ref = f"refs/heads/{name}"
        old = git(repo, "rev-parse", ref)
        tree = git(repo, "rev-parse", f"{old}^{{tree}}")
        baseline = git(repo, "commit-tree", tree, "-m", "Checkpoint context")
        commands.append(f"update {ref} {baseline} {old}")
    commands.extend(["prepare", "commit", ""])
    subprocess.run(
        ["git", "-C", str(repo), "update-ref", "--stdin"],
        input="\n".join(commands), text=True, capture_output=True, check=True,
    )
    git(repo, "reflog", "expire", "--expire=now", "--all")
    git(repo, "gc", "--prune=now")


@mcp.tool()
def context_branches(ctx: Context) -> dict:
    """List branches in this conversation."""
    with checkout(ctx) as repo:
        return {"current": git(repo, "branch", "--show-current"), "branches": branch_names(repo)}


@mcp.tool()
def context_branch(name: str, ctx: Context) -> dict:
    """Create and switch to a branch, inheriting the current note."""
    if not BRANCH_NAME.fullmatch(name) or ".." in name or name.endswith(("/", ".", ".lock")):
        raise ValueError("Invalid branch")
    with checkout(ctx) as repo:
        if len(branch_names(repo)) >= MAX_BRANCHES:
            raise ValueError("Conversation branch limit reached")
        git(repo, "check-ref-format", "--branch", name)
        git(repo, "switch", "-c", name)
        return state(repo)


@mcp.tool()
def context_checkout(name: str, ctx: Context) -> dict:
    """Switch to an existing branch in this conversation."""
    with checkout(ctx) as repo:
        if name not in branch_names(repo):
            raise ValueError("Unknown branch")
        git(repo, "switch", name)
        return state(repo)


@mcp.tool()
def context_tree(ctx: Context) -> dict:
    """List tracked paths on this conversation's current branch."""
    with checkout(ctx) as repo:
        return {
            "branch": git(repo, "branch", "--show-current"),
            "files": git(repo, "ls-tree", "-r", "--name-only", "HEAD").splitlines(),
        }


@mcp.tool()
def context_history(ctx: Context, limit: int = 10) -> dict:
    """List recent note commits on this conversation's current branch."""
    if not 1 <= limit <= 50:
        raise ValueError("Limit must be 1..50")
    with checkout(ctx) as repo:
        lines = git(repo, "log", f"-{limit}", "--format=%h|%s", "--", NOTE).splitlines()
        return {
            "branch": git(repo, "branch", "--show-current"),
            "commits": [dict(zip(("commit", "subject"), line.split("|", 1))) for line in lines],
        }


if __name__ == "__main__":
    mcp.run(transport="stdio")
