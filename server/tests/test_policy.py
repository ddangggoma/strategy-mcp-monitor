from datetime import UTC, datetime
from types import MappingProxyType

import pytest

from app.auth import policy
from app.auth.policy import RULES, can
from app.auth.policy import Action as A
from app.users.store import User


def mk(role, uid=1, active=True):
    return User(uid, f"{uid}@x.com", "n", role, active, datetime.now(UTC), None, None)


DEV, ADM = mk("developer", 1), mk("admin", 2)
# (action, 익명, 개발자, Admin, local_only, owner_only)
MATRIX = [
    (A.VIEW_BOARD,           1, 1, 1, False, False),
    (A.VIEW_MCP_HISTORY,     0, 1, 1, False, False),
    (A.VIEW_SESSION_HISTORY, 0, 1, 1, False, False),
    (A.VIEW_LOGS,            0, 1, 1, False, False),
    (A.EXPORT_LOGS,          0, 1, 1, False, False),
    (A.VIEW_AUDIT,           0, 1, 1, False, False),
    (A.EDIT_MCP_SETTINGS,    0, 1, 1, False, False),
    (A.MCP_MANUAL_ACTION,    0, 1, 1, False, False),
    (A.CREATE_MCP,           0, 1, 1, True,  False),
    (A.VIEW_SCRIPTS,         0, 1, 1, True,  False),
    (A.EDIT_SCRIPTS,         0, 1, 1, True,  True),
    (A.TRANSFER_OWNERSHIP,   0, 0, 1, True,  False),
    (A.MANAGE_USERS,         0, 0, 1, True,  False),
    (A.EDIT_GLOBAL_SETTINGS, 0, 0, 1, True,  False),
    (A.EDIT_RETENTION,       0, 0, 1, True,  False),
    (A.EDIT_NOTICE,          0, 0, 1, True,  False),
]


@pytest.mark.parametrize("action,anon,dev,adm,local_only,owner_only", MATRIX)
@pytest.mark.parametrize("channel", ["local", "external"])
@pytest.mark.parametrize("is_owner", [True, False])
def test_matrix(action, anon, dev, adm, local_only, owner_only, channel, is_owner):
    for user, allowed in ((None, anon), (DEV, dev), (ADM, adm)):
        owner = (user.id if user else 99) if is_owner else 99
        expected = bool(allowed) and (channel == "local" or not local_only) and (not owner_only or (user is not None and owner == user.id))
        assert can(user, action, channel, owner_id=owner) is expected, (action, user and user.role, channel, is_owner)


@pytest.mark.parametrize("channel", ["local", "external"])
def test_delete_mcp(channel):
    local = channel == "local"
    assert can(DEV, A.DELETE_MCP, channel, owner_id=DEV.id) is local
    assert can(DEV, A.DELETE_MCP, channel, owner_id=99) is False
    assert can(ADM, A.DELETE_MCP, channel, owner_id=99) is local
    assert can(None, A.DELETE_MCP, channel, owner_id=99) is False


def test_inactive_user_is_anonymous():
    assert can(mk("admin", 3, active=False), A.VIEW_LOGS, "local") is False
    assert can(mk("admin", 3, active=False), A.VIEW_BOARD, "local") is True


def test_admin_scripts_not_exempt():
    assert can(ADM, A.EDIT_SCRIPTS, "local", owner_id=99) is False


def test_matrix_covers_every_action():
    covered = {row[0] for row in MATRIX} | {A.DELETE_MCP}
    assert covered == set(A)


def test_every_action_has_a_rule():
    assert set(RULES) == set(A)


def test_unlisted_action_is_denied(monkeypatch):
    monkeypatch.setattr(policy, "RULES", MappingProxyType({a: r for a, r in RULES.items() if a is not A.VIEW_BOARD}))
    assert can(ADM, A.VIEW_BOARD, "local") is False
    assert can(None, A.VIEW_BOARD, "local") is False


@pytest.mark.parametrize("action,user", [
    (A.EDIT_SCRIPTS, DEV), (A.EDIT_SCRIPTS, ADM), (A.DELETE_MCP, DEV),
])
def test_owner_only_without_owner_is_denied(action, user):
    assert can(user, action, "local") is False
    assert can(user, action, "local", owner_id=None) is False


def test_admin_can_delete_ownerless_mcp():
    # spec 4.3: admin deletes any MCP (local); an owner-less MCP must stay deletable
    assert can(ADM, A.DELETE_MCP, "local", owner_id=None) is True
    assert can(ADM, A.DELETE_MCP, "external", owner_id=None) is False


@pytest.mark.parametrize("action", list(A))
@pytest.mark.parametrize("user", [None, DEV, ADM])
def test_unknown_channel_is_denied(action, user):
    assert can(user, action, "bogus", owner_id=1) is False  # type: ignore[arg-type]


def test_unknown_role_is_denied():
    odd = mk("superuser", 5)  # type: ignore[arg-type]
    for action in A:
        assert can(odd, action, "local", owner_id=5) is False


def test_rules_frozen():
    with pytest.raises(TypeError):
        RULES[A.VIEW_BOARD] = RULES[A.VIEW_LOGS]  # type: ignore[index]


def test_unknown_channel_case_is_denied():
    assert can(ADM, A.VIEW_BOARD, "LOCAL") is False  # type: ignore[arg-type]


def test_inactive_owner_is_not_owner():
    assert can(mk("developer", 5, active=False), A.EDIT_SCRIPTS, "local", owner_id=5) is False


def test_view_scripts_ignores_owner():
    assert can(DEV, A.VIEW_SCRIPTS, "local", owner_id=99) is True
    assert can(DEV, A.VIEW_SCRIPTS, "local") is True
