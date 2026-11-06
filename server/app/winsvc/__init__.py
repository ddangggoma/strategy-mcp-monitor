"""The Windows service (``python -m app service``): host, SCM glue and the start type."""

SERVICE_NAME = "mcp-monitor"
DISPLAY_NAME = "MCP Monitor"
DESCRIPTION = "MCP 상태 감시와 RDP 접속·행동 감사 (127.0.0.1:8700 / 0.0.0.0:8701)"
# A requested stop (plan review I5): STOP_PENDING every STOP_HEARTBEAT_SEC with an increasing
# checkpoint, each promising the next within STOP_WAIT_HINT_MS; the whole stop sequence is capped at
# STOP_DEADLINE_SEC (then the process reports STOPPED and leaves); at OS shutdown the service asks
# for PRESHUTDOWN with a timeout above that cap (the plain SHUTDOWN notice gives about 5 s).
STOP_WAIT_HINT_MS = 10_000
STOP_HEARTBEAT_SEC = 2.0
STOP_DEADLINE_SEC = 50.0
PRESHUTDOWN_TIMEOUT_MS = 60_000
