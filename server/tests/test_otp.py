import pytest
from app.auth.otp import OtpService, OtpRateLimitError, DummyOtpProvider
from app.users.store import UserStore, InvalidEmailError
from tests.fakes import CapturingOtpProvider

@pytest.fixture
def env(db, clock):
    users = UserStore(db, clock); u = users.create("a@x.com", "a", "admin", None)
    p = CapturingOtpProvider()
    return OtpService(db, users, p, clock, secret=b"k" * 32), p, u, clock

def test_success_once(env):
    svc, p, u, _ = env
    svc.request("A@x.com", "1.1.1.1"); code = p.sent[-1][1]
    assert len(code) == 6 and code.isdigit()
    assert svc.verify("a@x.com", code).id == u.id
    assert svc.verify("a@x.com", code) is None  # 1회용

def test_expiry(env):
    svc, p, _, clock = env
    svc.request("a@x.com", "ip"); code = p.sent[-1][1]
    clock.advance(301)
    assert svc.verify("a@x.com", code) is None

def test_valid_just_before_expiry(env):
    svc, p, _, clock = env
    svc.request("a@x.com", "ip"); code = p.sent[-1][1]; clock.advance(299)
    assert svc.verify("a@x.com", code) is not None

def test_attempt_limit(env):
    svc, p, _, _ = env
    svc.request("a@x.com", "ip"); code = p.sent[-1][1]
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5): assert svc.verify("a@x.com", wrong) is None
    assert svc.verify("a@x.com", code) is None

def test_cooldown(env):
    svc, _, _, clock = env
    svc.request("a@x.com", "ip")
    with pytest.raises(OtpRateLimitError) as e: svc.request("a@x.com", "ip")
    assert 1 <= e.value.retry_after <= 60
    clock.advance(60); svc.request("a@x.com", "ip")

def test_unknown_email_silent(env):
    svc, p, _, _ = env
    svc.request("ghost@x.com", "ip")
    assert p.sent == []
    with pytest.raises(OtpRateLimitError): svc.request("ghost@x.com", "ip")  # 등록 여부와 무관하게 같은 동작

def test_ip_limit(env):
    svc, _, _, clock = env
    for i in range(10): svc.request(f"u{i}@x.com", "9.9.9.9")
    with pytest.raises(OtpRateLimitError): svc.request("u10@x.com", "9.9.9.9")
    clock.advance(601); svc.request("u10@x.com", "9.9.9.9")

def test_inactive_user_cannot_verify(env, db, clock):
    svc, p, u, _ = env
    UserStore(db, clock).create("b@x.com", "b", "admin", None)
    svc.request("a@x.com", "ip"); code = p.sent[-1][1]
    UserStore(db, clock).set_active(u.id, False)
    assert svc.verify("a@x.com", code) is None

def test_dev_fixed_code(db, clock):
    users = UserStore(db, clock); users.create("a@x.com", "a", "admin", None)
    svc = OtpService(db, users, CapturingOtpProvider(), clock, b"k" * 32, dev_fixed_code="000000")
    assert svc.verify("a@x.com", "000000") is not None

def test_dummy_provider_outbox(paths):
    lines = []
    DummyOtpProvider(paths.dev_dir / "otp-outbox.log", echo=lines.append).send("a@x.com", "123456")
    assert "a@x.com 123456" in (paths.dev_dir / "otp-outbox.log").read_text("utf-8")
    assert "123456" in lines[0]

# --- additional tests for controller decisions ---

def test_provider_is_public_attribute(env):
    svc, p, _, _ = env
    assert svc.provider is p

def test_invalid_email_request_raises(env):
    svc, p, _, _ = env
    with pytest.raises(InvalidEmailError): svc.request("not-an-email", "ip")
    assert p.sent == []

def test_invalid_email_verify_returns_none(env):
    svc, _, _, _ = env
    assert svc.verify("not-an-email", "123456") is None

def test_rate_limited_request_keeps_existing_code(env):
    svc, p, _, _ = env
    svc.request("a@x.com", "ip"); code = p.sent[-1][1]
    with pytest.raises(OtpRateLimitError): svc.request("a@x.com", "ip")
    assert len(p.sent) == 1
    assert svc.verify("a@x.com", code) is not None

def test_ip_limited_request_does_not_send(env):
    svc, p, _, _ = env
    for i in range(10): svc.request(f"u{i}@x.com", "9.9.9.9")
    sent = len(p.sent)
    with pytest.raises(OtpRateLimitError) as e: svc.request("a@x.com", "9.9.9.9")
    assert isinstance(e.value.retry_after, int) and 1 <= e.value.retry_after <= 600
    assert len(p.sent) == sent

def test_malformed_code_counts_as_attempt(env):
    svc, p, _, _ = env
    svc.request("a@x.com", "ip"); code = p.sent[-1][1]
    for bad in ["", "abc", "12345", "１２３４５６", "é" * 6, "\ud800" * 6]:
        assert svc.verify("a@x.com", bad) is None
    assert svc.verify("a@x.com", code) is None  # 7 attempts used

def test_new_request_resets_attempts(env):
    svc, p, _, clock = env
    svc.request("a@x.com", "ip")
    for _ in range(5): svc.verify("a@x.com", "bad000")
    clock.advance(60); svc.request("a@x.com", "ip"); new = p.sent[-1][1]
    assert svc.verify("a@x.com", new) is not None

def test_inactive_user_request_sends_nothing_but_cooldown(env, db, clock):
    svc, p, u, _ = env
    UserStore(db, clock).create("b@x.com", "b", "admin", None)
    UserStore(db, clock).set_active(u.id, False)
    svc.request("a@x.com", "ip")
    assert p.sent == []
    with pytest.raises(OtpRateLimitError): svc.request("a@x.com", "ip")

def test_dev_fixed_code_rejected_for_unknown_and_inactive(db, clock):
    users = UserStore(db, clock)
    a = users.create("a@x.com", "a", "admin", None); users.create("b@x.com", "b", "admin", None)
    users.set_active(a.id, False)
    svc = OtpService(db, users, CapturingOtpProvider(), clock, b"k" * 32, dev_fixed_code="000000")
    assert svc.verify("ghost@x.com", "000000") is None
    assert svc.verify("a@x.com", "000000") is None

def test_dev_fixed_code_respects_attempt_limit(db, clock):
    users = UserStore(db, clock); users.create("a@x.com", "a", "admin", None)
    svc = OtpService(db, users, CapturingOtpProvider(), clock, b"k" * 32, dev_fixed_code="000000")
    svc.request("a@x.com", "ip")
    for _ in range(5): svc.verify("a@x.com", "999999")
    assert svc.verify("a@x.com", "000000") is None
