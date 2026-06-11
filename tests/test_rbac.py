from __future__ import annotations

from app.core.rbac import Permission, role_has_permission


def test_admin_can_manage_workspace() -> None:
    assert role_has_permission("admin", Permission.MANAGE_WORKSPACE)


def test_member_cannot_view_audit() -> None:
    assert not role_has_permission("member", Permission.VIEW_AUDIT)


def test_unknown_role_has_no_permissions() -> None:
    assert not role_has_permission("owner", Permission.READ_MEMORY)
