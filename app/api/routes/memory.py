from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter
from fastapi.params import Query

from app.api.deps import DBSession, ServiceAuth
from app.core.rbac import Permission
from app.schemas.memory import MemoryAnswer, MemoryQuestion
from app.services.access import AccessService
from app.services.memory import MemoryService

router = APIRouter()


@router.post("/ask", response_model=MemoryAnswer)
async def ask_memory(
    payload: MemoryQuestion,
    session: DBSession,
    _: ServiceAuth,
    actor_user_id: Annotated[UUID, Query()],
) -> MemoryAnswer:
    await AccessService(session).require_workspace_permission(
        payload.workspace_id,
        actor_user_id,
        Permission.READ_MEMORY,
    )
    service = MemoryService(session)
    return await service.answer_question(payload)
