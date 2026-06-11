from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from app.api.deps import DBSession, ServiceAuth
from app.core.rbac import Permission
from app.schemas.ai_keys import ProviderKeyDelete, ProviderKeyRead, ProviderKeyUpsert
from app.services.access import AccessService
from app.services.provider_keys import ProviderKeyService

router = APIRouter()


@router.put("", response_model=ProviderKeyRead)
async def upsert_provider_key(
    payload: ProviderKeyUpsert,
    session: DBSession,
    _: ServiceAuth,
    actor_user_id: Annotated[UUID, Query()],
) -> ProviderKeyRead:
    access = AccessService(session)
    await access.require_workspace_permission(
        payload.workspace_id, actor_user_id, Permission.MANAGE_WORKSPACE
    )
    await access.require_workspace_in_organization(payload.workspace_id, payload.organization_id)
    return await ProviderKeyService(session).upsert(payload)


@router.get("", response_model=list[ProviderKeyRead])
async def list_provider_keys(
    session: DBSession,
    _: ServiceAuth,
    organization_id: Annotated[UUID, Query()],
    workspace_id: Annotated[UUID, Query()],
    actor_user_id: Annotated[UUID, Query()],
) -> list[ProviderKeyRead]:
    access = AccessService(session)
    await access.require_workspace_permission(
        workspace_id,
        actor_user_id,
        Permission.MANAGE_WORKSPACE,
    )
    await access.require_workspace_in_organization(workspace_id, organization_id)
    return await ProviderKeyService(session).list_for_organization(organization_id)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider_key(
    payload: ProviderKeyDelete,
    session: DBSession,
    _: ServiceAuth,
    actor_user_id: Annotated[UUID, Query()],
) -> Response:
    access = AccessService(session)
    await access.require_workspace_permission(
        payload.workspace_id, actor_user_id, Permission.MANAGE_WORKSPACE
    )
    await access.require_workspace_in_organization(payload.workspace_id, payload.organization_id)
    await ProviderKeyService(session).delete(payload)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
