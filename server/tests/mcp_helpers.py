from __future__ import annotations

from app.monitor.models import Mcp, McpConfig
from app.monitor.scripts import ScriptUpload
from app.users.store import User
from app.web.deps import SESSION_COOKIE

BAT = {"start": ScriptUpload(".bat", "exit /b 0"), "stop": ScriptUpload(".bat", "exit /b 0")}


def cfg(**kw) -> McpConfig:
    """Shared McpConfig builder for tests (defaults: calculator on 127.0.0.1:9102)."""
    return McpConfig.model_validate({"name": "calc", "host": "127.0.0.1", "port": 9102, **kw})


def make_user(services, email: str, role: str = "developer") -> User:
    return services.users.create(email, email.split("@", 1)[0], role, None)


def seed_mcp(services, owner: User, scripts=BAT, **config) -> Mcp:
    """Create the MCP with its scripts (default: calc on 127.0.0.1:9102) and register it with the monitor."""
    mcp = services.scripts.create_mcp(cfg(**config), owner.id, scripts)
    services.monitor.add(mcp)
    return mcp


def login_as(client, services, user: User, channel: str) -> str:
    """Create a session directly, set its cookie on the client and return its CSRF token."""
    sid, csrf = services.sessions.create(user.id, channel, "127.0.0.1", "ua")
    client.cookies.set(SESSION_COOKIE, sid)
    return csrf
