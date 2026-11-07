"""Single permission policy (spec §4.3). Every authorization decision goes through can()."""
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum, StrEnum, auto
from types import MappingProxyType
from typing import get_args

from app.users.store import Role, User
from app.web.channels import Channel


class Action(StrEnum):
    VIEW_BOARD = "view_board"
    VIEW_MCP_HISTORY = "view_mcp_history"
    VIEW_SESSION_HISTORY = "view_session_history"
    VIEW_LOGS = "view_logs"
    EXPORT_LOGS = "export_logs"
    VIEW_AUDIT = "view_audit"
    EDIT_MCP_SETTINGS = "edit_mcp_settings"
    MCP_MANUAL_ACTION = "mcp_manual_action"
    CREATE_MCP = "create_mcp"
    DELETE_MCP = "delete_mcp"
    VIEW_SCRIPTS = "view_scripts"
    EDIT_SCRIPTS = "edit_scripts"
    TRANSFER_OWNERSHIP = "transfer_ownership"
    MANAGE_USERS = "manage_users"
    EDIT_GLOBAL_SETTINGS = "edit_global_settings"
    EDIT_RETENTION = "edit_retention"
    EDIT_NOTICE = "edit_notice"


class OwnerRule(Enum):
    NONE = auto()            # owner is irrelevant
    ALWAYS = auto()          # only the owner, whatever the role (admin is not exempt)
    DEVELOPER_ONLY = auto()  # developers need to own it; admins may act on any resource


@dataclass(frozen=True)
class Rule:
    min_role: Role | None  # None = anonymous allowed; otherwise "developer" or "admin"
    local_only: bool = False
    owner: OwnerRule = OwnerRule.NONE


_RANK = {None: 0, "developer": 1, "admin": 2}

RULES: Mapping[Action, Rule] = MappingProxyType({
    Action.VIEW_BOARD: Rule(None),
    Action.VIEW_MCP_HISTORY: Rule("developer"),
    Action.VIEW_SESSION_HISTORY: Rule("developer"),
    Action.VIEW_LOGS: Rule("developer"),
    Action.EXPORT_LOGS: Rule("developer"),
    Action.VIEW_AUDIT: Rule("developer"),
    Action.EDIT_MCP_SETTINGS: Rule("developer"),
    Action.MCP_MANUAL_ACTION: Rule("developer"),
    Action.CREATE_MCP: Rule("developer", local_only=True),
    Action.DELETE_MCP: Rule("developer", local_only=True, owner=OwnerRule.DEVELOPER_ONLY),
    Action.VIEW_SCRIPTS: Rule("developer", local_only=True),  # read-only, any owner
    Action.EDIT_SCRIPTS: Rule("developer", local_only=True, owner=OwnerRule.ALWAYS),
    Action.TRANSFER_OWNERSHIP: Rule("admin", local_only=True),
    Action.MANAGE_USERS: Rule("admin", local_only=True),
    Action.EDIT_GLOBAL_SETTINGS: Rule("admin", local_only=True),
    Action.EDIT_RETENTION: Rule("admin", local_only=True),
    Action.EDIT_NOTICE: Rule("admin", local_only=True),
})


def can(user: User | None, action: Action, channel: Channel, owner_id: int | None = None) -> bool:
    """Deny by default: unknown action, channel or role, and missing owner, all return False."""
    if user is not None and not user.active:
        user = None  # a deactivated account is anonymous in every respect, ownership included
    rule = RULES.get(action)
    if rule is None or channel not in get_args(Channel):
        return False
    if rule.local_only and channel != "local":
        return False

    role = user.role if user is not None else None
    if role not in _RANK:
        return False
    if _RANK[role] < _RANK[rule.min_role]:
        return False

    owner_required = rule.owner is OwnerRule.ALWAYS or (
        rule.owner is OwnerRule.DEVELOPER_ONLY and role != "admin"
    )
    if owner_required:
        return user is not None and owner_id is not None and owner_id == user.id
    return True
