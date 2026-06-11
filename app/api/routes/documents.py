from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import DBSession, ServiceAuth
from app.core.rbac import Permission
from app.schemas.documents import DocumentIngestRequest, DocumentIngestResponse
from app.services.access import AccessService
from app.services.documents import DocumentService

router = APIRouter()


@router.post("/ingest", response_model=DocumentIngestResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest_document(
    payload: DocumentIngestRequest,
    session: DBSession,
    _: ServiceAuth,
    actor_user_id: Annotated[UUID, Query()],
) -> DocumentIngestResponse:
    await AccessService(session).require_workspace_permission(
        payload.workspace_id, actor_user_id, Permission.MANAGE_WORKSPACE
    )
    document, chunks_created = await DocumentService(session).ingest(payload)
    return DocumentIngestResponse(document_id=document.id, chunks_created=chunks_created)
