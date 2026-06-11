from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import DBSession, ServiceAuth
from app.core.rbac import Permission
from app.schemas.files import (
    FileDownloadUrlRequest,
    FileDownloadUrlResponse,
    FileUploadUrlRequest,
    FileUploadUrlResponse,
)
from app.services.access import AccessService
from app.services.files import FileService

router = APIRouter()


@router.post("/upload-url", response_model=FileUploadUrlResponse)
async def create_upload_url(
    payload: FileUploadUrlRequest,
    session: DBSession,
    _: ServiceAuth,
    actor_user_id: Annotated[UUID, Query()],
) -> FileUploadUrlResponse:
    await AccessService(session).require_workspace_permission(
        payload.workspace_id, actor_user_id, Permission.MANAGE_WORKSPACE
    )
    upload = await FileService(session).create_upload_url(payload)
    return FileUploadUrlResponse(
        storage_key=upload.storage_key,
        upload_url=upload.upload_url,
        expires_in_seconds=upload.expires_in_seconds,
        headers=upload.headers,
    )


@router.post("/download-url", response_model=FileDownloadUrlResponse)
async def create_download_url(
    payload: FileDownloadUrlRequest,
    session: DBSession,
    _: ServiceAuth,
    actor_user_id: Annotated[UUID, Query()],
) -> FileDownloadUrlResponse:
    await AccessService(session).require_workspace_permission(
        payload.workspace_id, actor_user_id, Permission.READ_MEMORY
    )
    download = await FileService(session).create_download_url(payload)
    return FileDownloadUrlResponse(
        download_url=download.download_url,
        expires_in_seconds=download.expires_in_seconds,
    )
