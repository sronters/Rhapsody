from __future__ import annotations

import uuid
from pathlib import Path

import boto3
from botocore.client import BaseClient

from app.core.config import Settings, get_settings


class AudioStorageError(RuntimeError):
    pass


class AudioStorageService:
    def __init__(self, settings: Settings | None = None, client: BaseClient | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = client or self._build_client()

    def upload_chunk_file(
        self,
        *,
        workspace_id: uuid.UUID,
        call_session_id: uuid.UUID,
        sequence_number: int,
        local_path: str,
        content_type: str,
    ) -> str:
        path = Path(local_path)
        if not path.exists():
            raise AudioStorageError(f"Audio chunk does not exist: {local_path}")
        object_ref = (
            f"workspaces/{workspace_id}/calls/{call_session_id}/"
            f"chunks/{sequence_number:06d}.wav"
        )
        self.client.put_object(
            Bucket=self.settings.s3_bucket,
            Key=object_ref,
            Body=path.read_bytes(),
            ContentType=content_type,
        )
        return object_ref

    def _build_client(self) -> BaseClient:
        return boto3.client(
            "s3",
            endpoint_url=self.settings.s3_endpoint_url,
            aws_access_key_id=self.settings.s3_access_key_id,
            aws_secret_access_key=self.settings.s3_secret_access_key,
        )
