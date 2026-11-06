"""The Windows service (``python -m app service``): host, SCM glue and the start type."""

SERVICE_NAME = "mcp-monitor"
DISPLAY_NAME = "MCP Monitor"
DESCRIPTION = "MCP 상태 감시와 RDP 접속·행동 감사 (127.0.0.1:8700 / 0.0.0.0:8701)"
STOP_WAIT_HINT_MS = 30_000
