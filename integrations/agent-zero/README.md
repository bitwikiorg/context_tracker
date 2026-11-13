# Agent Zero setup

Context Tracker can keep a separate working note for each Agent Zero chat. Agent Zero supplies the chat ID automatically for local stdio servers that opt in.

1. Back up `helpers/mcp_handler.py` and the project's `.a0proj/mcp_servers.json`. From the Agent Zero root, run `git apply --check /path/to/v2.15.patch`, then `git apply /path/to/v2.15.patch`. This patch was tested on Agent Zero v2.15 at `ba9b67df`. Recheck compatibility after an Agent Zero upgrade.
2. Update the Context Tracker server to this revision. In the existing tracker entry, set `"send_session_meta": true` at the server level and `"CONTEXT_TRACKER_TRUSTED_HOST": "agent-zero"` inside `env`. Remove `CONTEXT_TRACKER_LOCAL_SCOPE`. Point `CONTEXT_TRACKER_HOME` at a fresh directory so the old shared notes and history stay separate.
3. Restart Agent Zero. In two chats in the same project, write a note in A, confirm B starts empty, write in B, then edit A. Read both again and verify that each retained its own value.

The patched MCP client sends host, project scope, and chat ID in request metadata under `context-tracker/conversation`. The metadata is supplied by the local host. Use this mode only when the tracker is launched through a trusted connection. The patch opts in per local stdio server and leaves remote MCP requests unchanged. The ChatGPT tunnel can continue using its current metadata and configuration.

If the pilot fails, disable the tracker entry, then restore the saved handler and project configuration as needed. Keep the prior shared notes offline while investigating. Restart Agent Zero after restoring the handler.
