from __future__ import annotations

from enum import Enum


class WorkspaceRole(str, Enum):
    MEMBER = "member"
    TEAM_LEAD = "team_lead"
    MANAGER = "manager"
    ADMIN = "admin"
    ENTERPRISE_ADMIN = "enterprise_admin"


class Permission(str, Enum):
    READ_MEMORY = "read_memory"
    MANAGE_TASKS = "manage_tasks"
    MANAGE_DECISIONS = "manage_decisions"
    MANAGE_WORKSPACE = "manage_workspace"
    VIEW_AUDIT = "view_audit"


ROLE_PERMISSIONS: dict[WorkspaceRole, set[Permission]] = {
    WorkspaceRole.MEMBER: {Permission.READ_MEMORY},
    WorkspaceRole.TEAM_LEAD: {
        Permission.READ_MEMORY,
        Permission.MANAGE_TASKS,
        Permission.MANAGE_DECISIONS,
    },
    WorkspaceRole.MANAGER: {
        Permission.READ_MEMORY,
        Permission.MANAGE_TASKS,
        Permission.MANAGE_DECISIONS,
        Permission.VIEW_AUDIT,
    },
    WorkspaceRole.ADMIN: {
        Permission.READ_MEMORY,
        Permission.MANAGE_TASKS,
        Permission.MANAGE_DECISIONS,
        Permission.MANAGE_WORKSPACE,
        Permission.VIEW_AUDIT,
    },
    WorkspaceRole.ENTERPRISE_ADMIN: set(Permission),
}


def role_has_permission(role: str, permission: Permission) -> bool:
    try:
        parsed_role = WorkspaceRole(role)
    except ValueError:
        return False
    return permission in ROLE_PERMISSIONS[parsed_role]
