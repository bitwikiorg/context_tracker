# Context Tracker

Context Tracker is a Git-backed MCP server for working context within a conversation. Each branch holds one note with a title of up to 120 characters and content of up to 500 characters. Use it for open questions, tasks, and observations worth revisiting later in the session.

## Run locally

Requires Python 3.10 or newer and Git 2.28 or newer.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python server.py
```

Configure your MCP client to launch the virtual environment's Python with the absolute path to `server.py` as an argument. The server uses stdio. Its first launch initializes an empty note on `main` in `~/.local/state/context-tracker-mcp`. Set `CONTEXT_TRACKER_HOME` to choose a different state directory. Give concurrent conversations separate state directories when they need independent notes and branch selections.

## Session workflow

At the beginning of a conversation, establish its working context with `context_write`. Read it with `context_read` when revisiting an open item and update it as the session evolves. Git retains notes and revision history on disk, so the MCP client or agent must establish the appropriate context for each new conversation. Starting a conversation does not automatically invoke an MCP tool. Writing two empty strings clears the current note while preserving Git history.

| Tool | Behavior |
| --- | --- |
| `context_read` | Return the current note and its `EMPTY` or `ACTIVE` status as JSON text. |
| `context_write` | Replace the note and return the result as JSON text. Identical writes do not create a commit. |
| `context_branches` | List branches and identify the current branch. |
| `context_branch` | Create and switch to a branch that inherits the current note. |
| `context_checkout` | Switch to an existing branch. |
| `context_tree` | List tracked paths on the current branch. |
| `context_history` | List recent commits for the current note. |
