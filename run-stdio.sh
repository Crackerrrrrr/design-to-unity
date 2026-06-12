#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
export MCP_TRANSPORT=stdio

if [ -x ".venv/bin/python" ]; then
  exec .venv/bin/python -m design_handoff_mcp.server
fi

exec python -m design_handoff_mcp.server

