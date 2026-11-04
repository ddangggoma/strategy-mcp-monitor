from __future__ import annotations

from app.monitor.models import McpConfig


def cfg(**kw) -> McpConfig:
    """Shared McpConfig builder for tests (defaults: calculator on 127.0.0.1:9102)."""
    return McpConfig.model_validate({"name": "calc", "host": "127.0.0.1", "port": 9102, **kw})
