# Claude Code notes

@AGENTS.md

In Claude Code the `bridge` MCP server (see `.mcp.json`) is preconfigured with run DB `runs/chat-demo.db`; prefer its tools
(`start_run`, `list_questions`, `get_question`, `ask_user`, `answer_question`, `resume_run`, `readiness`, ...) over the CLI.
`scripts/session-start.sh` installs the package at session start. If the tools are missing, run it, then restart the session.
