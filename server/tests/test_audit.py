from datetime import datetime, timedelta, timezone

from app.audit import AuditLogger


class _Log:
    def __init__(self):
        self.events = []

    def emit(self, cat, **fields):
        self.events.append((cat, fields))


def _hit(audit, ip, now, event="otp_request"):
    audit.auth_rate_limited(event=event, email="a@x.com", channel="external", ip=ip,
                            user_agent=None, now=now)


def test_rate_limited_audit_once_per_event_ip_window():
    log = _Log(); audit = AuditLogger(log)
    t0 = datetime(2026, 11, 4, 5, 0, tzinfo=timezone.utc)
    for i in range(5):
        _hit(audit, "1.1.1.1", t0 + timedelta(seconds=i))
    assert len(log.events) == 1 and log.events[0][1]["ok"] is False
    _hit(audit, "2.2.2.2", t0)                      # other IP
    _hit(audit, "1.1.1.1", t0, event="login")       # other event
    assert len(log.events) == 3
    _hit(audit, "1.1.1.1", t0 + timedelta(seconds=601))  # next window
    assert len(log.events) == 4


def test_rate_limited_audit_memory_is_bounded():
    log = _Log(); audit = AuditLogger(log)
    t0 = datetime(2026, 11, 4, 5, 0, tzinfo=timezone.utc)
    for i in range(30000):
        _hit(audit, f"ip{i}", t0)
    assert audit.throttle_size <= 10000
    _hit(audit, "late", t0 + timedelta(seconds=700))
    assert audit.throttle_size == 1  # expired entries purged
