<div align="center">

<a id="context-tracker"></a>
<img src="assets/hero-banner.svg" alt="Context Tracker — working context for AI agents, with Git history" width="960">

**One working note. Seven MCP tools. A thread you can return to.**

[Get started](#quick-start) · [How it works](#the-context-loop) · [Tools](#mcp-tools) · [Branches](#branches-and-storage)

</div>

---

Context Tracker gives an AI agent a place to keep unfinished tasks, open questions, and clues it wants to revisit later in a conversation. It exposes a small working note through the **Model Context Protocol (MCP)** and records revisions in Git.

| Keep in view | Revisit later | Follow a thread |
| :--- | :--- | :--- |
| The current goal and its constraints | Questions, reminders, and unresolved decisions | Branch the note and return to an earlier line of work |

<details>
<summary><strong>Explore the documentation</strong></summary>

- [The context loop](#the-context-loop)
- [Quick start](#quick-start)
- [Session workflow](#session-workflow)
- [MCP tools](#mcp-tools)
- [Branches and storage](#branches-and-storage)
- [FAQ](#faq)
- [Repository map](#repository-map)

</details>

## The context loop

The agent writes what matters, retrieves it when relevant, and revises it as the conversation develops. This repeated use is intended to support continuity of attention and consistency across a long session.

```mermaid
flowchart TD
    A["Conversation develops"] --> B["Read the working note"]
    B --> C["Reconcile with current intent"]
    C --> D{"Has the context changed?"}
    D -->|Yes| E["Write the revised note"]
    D -->|No| F["Continue the conversation"]
    E --> G["Git records the revision"]
    G --> F
    F --> A
    style B fill:#def7f3,stroke:#247d74,color:#133c38
    style E fill:#ede8ff,stroke:#7963b3,color:#352652
    style G fill:#fff1dc,stroke:#a87b35,color:#513a18
```

| Note field | Capacity | Purpose |
| :--- | ---: | :--- |
| `title` | 120 characters | Name the active context |
| `content` | 500 characters | Carry the information worth revisiting |

The content is free text. A compact to-do list, an unresolved question, or a reminder about the user's stated preferences can all fit the same note.

<p align="right"><a href="#context-tracker">↑ Back to top</a></p>

---

## Quick start

You’ll need Python 3.10 or newer, Git 2.28 or newer, a Unix host (Linux or macOS), and an MCP client that supports stdio.

```sh
git clone https://github.com/bitwikiorg/context_tracker.git
cd context_tracker
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Configure your MCP client to launch `server.py` over stdio. The example below is for a launcher dedicated to one conversation. Replace the paths and set `CONTEXT_TRACKER_LOCAL_SCOPE` to an opaque key unique to that conversation and its owner. Use the same key when reopening that conversation.

```json
{
  "mcpServers": {
    "context-tracker": {
      "command": "/absolute/path/to/context_tracker/.venv/bin/python",
      "args": ["/absolute/path/to/context_tracker/server.py"],
      "env": {
        "CONTEXT_TRACKER_HOME": "/absolute/path/to/context-tracker-state",
        "CONTEXT_TRACKER_LOCAL_SCOPE": "example-private-launcher-scope"
      }
    }
  }
}
```

Call `context_read` with a fresh conversation binding. The response is JSON text with `status: EMPTY`, branch `main`, and blank title and content.

For a shared ChatGPT tunnel, leave `CONTEXT_TRACKER_LOCAL_SCOPE` unset. The server requires the host-provided `openai/subject` and `openai/session` tool-call metadata. Verify both reach the server before switching a live connection. Treat the tunnel as a trusted ingress. For other hosts, a private stdio launcher can bind one process per conversation. A shared process requires an integration that supplies a trusted binding per call.


<p align="right"><a href="#context-tracker">↑ Back to top</a></p>

---

## Session workflow

1. **Start a conversation.** Call `context_read`. A new conversation starts empty. Use `context_write` when you have working context worth keeping.
2. **Revisit it when it matters.** Call `context_read` when an earlier question, constraint, or task becomes relevant. Treat the note as context for the current request.
3. **Edit or replace the note.** Call `context_write` again with the full title and content you want to keep. To edit just one field, pass the other field unchanged. When the current context is resolved, write the next context into the same note. Git records the previous revision.

For example, call `context_write` with these arguments.

```json
{
  "title": "README review",
  "content": "Open question: does the setup example show where the Git state lives?"
}
```

Call `context_read` to retrieve the note. Its status is now `ACTIVE`.

> [!IMPORTANT]
> Every tool requires a conversation binding before opening state. The host supplies that binding. Never set a static launcher scope on a server that serves several chats.


<p align="right"><a href="#context-tracker">↑ Back to top</a></p>

---

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


<details>
<summary><strong>Response format and write behavior</strong></summary>

`context_read` and `context_write` return explicit JSON text. The other five tools return structured objects.

A successful changed write returns `changed: true`, a short commit identifier, and the current note state. An identical write returns `changed: false`. Nonblank content requires a nonblank title.

```json
{
  "status": "ACTIVE",
  "branch": "main",
  "title": "README review",
  "content": "Open question: does the setup example show where the Git state lives?"
}
```

</details>

<p align="right"><a href="#context-tracker">↑ Back to top</a></p>

---

## Branches and storage

<img src="assets/branches.svg" alt="Main and research branches inherit a shared note, then retain their own revisions" width="960">

`context_branch` creates a branch and switches to it, inheriting the current note. Subsequent writes belong to the selected branch. Use `context_checkout` to return to an existing branch.

| Storage property | Behavior |
| :--- | :--- |
| Default location | `~/.local/state/context-tracker-mcp` |
| Custom location | Set `CONTEXT_TRACKER_HOME` in the server environment |
| Tracked note | `notes/current.json` |
| Initial branch | `main` |
| Conversation storage | Each scope has its own Git repository under `conversations-v1` |
| Idle retention | 24 hours by default, configurable with `CONTEXT_TRACKER_IDLE_SECONDS`. Cleanup runs on the next scoped call. |
| Bounds | 128 retained conversations per root and 16 branches per conversation |
| History | At 256 reachable commits, the next changed write checkpoints branch tips and prunes prior history. |

The server initializes each repository on first use. A filesystem lock coordinates calls and expiry across server processes. When storage is full, a new conversation can open after an inactive scope expires.

For rollout, use a separate state root and test two real conversations through the same host. The legacy shared repository is outside the new scopes. To roll back, disable the staged endpoint or redeploy a verified isolated build. Keep the old shared checkout offline.

<p align="right"><a href="#context-tracker">↑ Back to top</a></p>

---

## FAQ

<details>
<summary><strong>Does the note survive a server restart?</strong></summary>

Yes, while the conversation is retained. Reopening it with the same trusted binding retrieves its note and selected branch.

</details>

<details>
<summary><strong>How do I clear the note?</strong></summary>

Call `context_write` with an empty title and empty content.

```json
{"title": "", "content": ""}
```

The current state becomes `EMPTY`. Previous revisions remain available until a history checkpoint or idle expiry.

</details>

<details>
<summary><strong>What can the file tree show?</strong></summary>

`context_tree` lists tracked paths on the selected branch. The current server manages one note at `notes/current.json`.

</details>

<p align="right"><a href="#context-tracker">↑ Back to top</a></p>

---

## Repository map

| File | Role |
| :--- | :--- |
| [server.py](server.py) | MCP tools, note validation, and Git operations |
| [requirements.txt](requirements.txt) | Pinned MCP dependency |
| [tests/test_isolation.py](tests/test_isolation.py) | Stdio integration tests with temporary Git storage |
| [assets/hero-banner.svg](assets/hero-banner.svg) | Project banner |
| [assets/branches.svg](assets/branches.svg) | Note branching diagram |

<p align="right"><a href="#context-tracker">↑ Back to top</a></p>
