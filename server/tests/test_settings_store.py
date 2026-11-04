import pytest
from pydantic import ValidationError
from app.settings.store import Settings, SettingsStore

def test_defaults(db):
    s = SettingsStore(db).get()
    assert (s.ping_interval_sec, s.issue_check_interval_sec, s.confirm_interval_sec) == (5, 10, 1)
    assert (s.log_retention_days, s.log_compress_after_days) == (180, 30)
    assert s.service_start_type == "delayed-auto" and s.otp_provider == "dummy"

def test_update_persists(db):
    SettingsStore(db).update({"ping_interval_sec": 30, "log_retention_days": 365})
    s = SettingsStore(db).get()
    assert s.ping_interval_sec == 30 and s.log_retention_days == 365

@pytest.mark.parametrize("patch", [
    {"ping_interval_sec": 0}, {"ping_interval_sec": 301},
    {"log_retention_days": 6}, {"log_retention_days": 3651},
    {"log_retention_days": 20, "log_compress_after_days": 21},
    {"service_start_type": "boot"}, {"unknown_key": 1},
    {"ping_interval_sec": True}, {"ping_interval_sec": "5"},
    {"ping_interval_sec": 5.0}, {"service_start_type": 1},
])
def test_update_rejects(db, patch):
    with pytest.raises(ValidationError):
        SettingsStore(db).update(patch)
    assert SettingsStore(db).get().ping_interval_sec == 5


def test_corrupt_row_falls_back(db):
    db.execute("INSERT INTO settings(key, value) VALUES ('global', '{not json')")
    s = SettingsStore(db)
    assert s.get() == Settings()
    assert s.update({"ping_interval_sec": 7}).ping_interval_sec == 7
    assert s.get().ping_interval_sec == 7


def test_corrupt_row_warns_once_per_distinct_value(db, capsys):
    db.execute("INSERT INTO settings(key, value) VALUES ('global', '{not json')")
    s = SettingsStore(db)
    for _ in range(3):
        assert s.get() == Settings()
    assert capsys.readouterr().err.count("corrupt") == 1
    db.execute("UPDATE settings SET value = '{\"ping_interval_sec\": 0}' WHERE key = 'global'")
    assert s.get() == Settings()
    assert capsys.readouterr().err.count("corrupt") == 1
