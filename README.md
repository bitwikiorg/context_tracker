<div align="center">

# Context Tracker

**One working note for your AI agent, with Git history.**

[Quick start](#quick-start) · [Session workflow](#session-workflow) · [MCP tools](#mcp-tools) · [Storage](#storage)

</div>

Context Tracker gives an AI agent a place to keep the questions, tasks, and clues it wants to revisit later in a conversation. It exposes seven tools through the Model Context Protocol (MCP). Each Git branch holds one note with a title of up to **120 characters** and content of up to **500 characters**.

## Quick start

You’ll need Python 3.10 or newer, Git 2.28 or newer, and an MCP client that supports stdio.

```sh
git clone https://github.com/bitwikiorg/context_tracker.git
cd context_tracker
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Configure your MCP client to launch `server.py` over stdio. For clients that use an `mcpServers` configuration, replace `/absolute/path/to/context_tracker` with the path to your clone.

```json
{
  "mcpServers": {
    "context-tracker": {
      "command": "/absolute/path/to/context_tracker/.venv/bin/python",
      "args": ["/absolute/path/to/context_tracker/server.py"],
      "env": {
        "CONTEXT_TRACKER_HOME": "/absolute/path/to/context-tracker-state"
      }
    }
  }
}
```

Choose a fresh directory for `CONTEXT_TRACKER_HOME` and call `context_read`. The response is JSON text with `status: EMPTY`, branch `main`, and blank title and content.

## Session workflow

1. **Start a conversation.** Use `context_write` to set its working note. If you’re resuming the same conversation, read the existing note first.
2. **Revisit it when it matters.** Call `context_read` when an earlier question, constraint, or task becomes relevant. Treat the note as context for the current request.
3. **Keep it current.** Replace the note as priorities change. Carry forward open items that still matter and drop resolved ones.

For example, call `context_write` with these arguments.

```json
{
  "title": "README review",
  "content": "Open question: does the setup example show where the Git state lives?"
}
```

Call `context_read` to retrieve the note. Its status is now `ACTIVE`.

> [!IMPORTANT]
> The agent or host decides when to call the tools. Starting a conversation leaves the stored note in place. Initialize the note for each new conversation, or give each conversation its own state directory when your client can set one.

## MCP tools

| Tool | Arguments | Behavior |
| --- | --- | --- |
| `context_read` | None | Return the current note, branch, and `EMPTY` or `ACTIVE` status as JSON text. |
| `context_write` | `title`, `content` | Replace the note and return JSON text. An identical write returns `changed: false` and skips the commit. |
| `context_branches` | None | List local branches and identify the current branch. |
| `context_branch` | `name` | Create and switch to a branch that inherits the current note. |
| `context_checkout` | `name` | Switch to an existing branch and return its note. |
| `context_tree` | None | List tracked paths on the current branch. |
| `context_history` | `limit` (optional) | List recent commits for the note. Default 10, range 1–50. |

## Storage

The server initializes a Git repository with `notes/current.json` on `main`. The default directory is `~/.local/state/context-tracker-mcp`. Set `CONTEXT_TRACKER_HOME` in the server process environment to choose another location.

- **Branches** let you follow a different thread from the current note and return to the original later. Each server process using the same directory shares its checked-out branch.
- **Separate directories** give simultaneous conversations independent notes, history, and branch selection.
- **Clearing the note** takes two empty strings in `context_write`. This clears the current note and preserves previous revisions in Git.
