#!/bin/bash
# Claude Code SessionStart hook: make sure Bridge and its dependencies are importable so the
# `bridge` MCP server (.mcp.json) and the CLI work in fresh cloud sessions. Cheap no-op when already installed.
set -uo pipefail
cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/..}"
if ! python3 -c "import bridge, nimbus, testbed, fastapi, mcp" >/dev/null 2>&1; then
  python3 -m pip install -q -e ".[dev]" >/dev/null 2>&1 || python3 -m pip install -q --user -e ".[dev]" >/dev/null 2>&1
fi
mkdir -p runs exports
exit 0
