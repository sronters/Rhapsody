from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

import boto3
from botocore.client import BaseClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.models import AuditLog
from app.repositories.workspace import WorkspaceRepository
from app.schemas.files import FileDownloadUrlRequest, FileUploadUrlRequest


@dataclass(frozen=True)
class PresignedUpload:
    storage_key: str
    upload_url: str
    expires_in_seconds: int
    headers: dict[str, str]


@dataclass(frozen=True)
class PresignedDownload:
    download_url: str
    expires_in_seconds: int


class ObjectStorageService:
    def __init__(self, settings: Settings | None = None, client: BaseClient | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = client or self._build_client()

    def create_upload_url(
        self, workspace_id: uuid.UUID, filename: str, content_type: str, purpose: str
    ) -> PresignedUpload:
        storage_key = build_storage_key(workspace_id, purpose, filename)
        expires = 900
        upload_url = self.client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self.settings.s3_bucket,
                "Key": storage_key,
                "ContentType": content_type,
            },
            ExpiresIn=expires,
        )
        return PresignedUpload(
            storage_key=storage_key,
            upload_url=upload_url,
            expires_in_seconds=expires,
            headers={"Content-Type": content_type},
        )

    def create_download_url(self, storage_key: str) -> PresignedDownload:
        expires = 300
        download_url = self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.settings.s3_bucket, "Key": storage_key},
            ExpiresIn=expires,
        )
        return PresignedDownload(download_url=download_url, expires_in_seconds=expires)

    def _build_client(self) -> BaseClient:
        return boto3.client(
            "s3",
            endpoint_url=self.settings.s3_endpoint_url,
            aws_access_key_id=self.settings.s3_access_key_id,
            aws_secret_access_key=self.settings.s3_secret_access_key,
        )


class FileService:
    def __init__(
        self,
        session: AsyncSession,
        storage: ObjectStorageService | None = None,
    ) -> None:
        self.session = session
        self.storage = storage or ObjectStorageService()
        self.workspace_repository = WorkspaceRepository(session)

    async def create_upload_url(self, payload: FileUploadUrlRequest) -> PresignedUpload:
        workspace = await self.workspace_repository.get(payload.workspace_id)
        upload = self.storage.create_upload_url(
            payload.workspace_id,
            payload.filename,
            payload.content_type,
            payload.purpose,
        )
        self.session.add(
            AuditLog(
                organization_id=workspace.organization_id,
                workspace_id=payload.workspace_id,
                action="file.upload_url_created",
                resource_type="file",
                metadata_json={
                    "storage_key": upload.storage_key,
                    "purpose": payload.purpose,
                    "content_type": payload.content_type,
                },
            )
        )
        await self.session.commit()
        return upload

    async def create_download_url(self, payload: FileDownloadUrlRequest) -> PresignedDownload:
        workspace = await self.workspace_repository.get(payload.workspace_id)
        ensure_storage_key_belongs_to_workspace(payload.workspace_id, payload.storage_key)
        download = self.storage.create_download_url(payload.storage_key)
        self.session.add(
            AuditLog(
                organization_id=workspace.organization_id,
                workspace_id=payload.workspace_id,
                action="file.download_url_created",
                resource_type="file",
                metadata_json={"storage_key": payload.storage_key},
            )
        )
        await self.session.commit()
        return download


def build_storage_key(workspace_id: uuid.UUID, purpose: str, filename: str) -> str:
    safe_filename = sanitize_filename(filename)
    return f"workspaces/{workspace_id}/{purpose}/{uuid.uuid4()}-{safe_filename}"


def sanitize_filename(filename: str) -> str:
    stripped = filename.strip().replace("\\", "/").split("/")[-1]
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", stripped).strip(".-")
    return safe or "upload.bin"


def ensure_storage_key_belongs_to_workspace(workspace_id: uuid.UUID, storage_key: str) -> None:
    expected_prefix = f"workspaces/{workspace_id}/"
    if not storage_key.startswith(expected_prefix):
        raise ValueError("Storage key does not belong to the requested workspace.")
