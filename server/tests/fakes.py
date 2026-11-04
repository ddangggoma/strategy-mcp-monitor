from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.monitor.models import Mcp, McpConfig


class FakeClock:
    def __init__(self, start: datetime) -> None:
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


class CapturingOtpProvider:
    """Test OTP provider that records (email, code) pairs instead of delivering."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, email: str, code: str) -> None:
        self.sent.append((email, code))


def make_mcp(id: int = 1, **config) -> Mcp:
    """Mcp fixture: 127.0.0.1:(9100 + id) named m<id>, unowned, created 2026-11-04T05:00Z."""
    fields = {"name": f"m{id}", "host": "127.0.0.1", "port": 9100 + id, **config}
    return Mcp(
        id=id,
        config=McpConfig.model_validate(fields),
        owner_id=None,
        created_by=None,
        created_at=datetime(2026, 11, 4, 5, 0, 0, tzinfo=timezone.utc),
    )
