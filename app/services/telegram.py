from __future__ import annotations

import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.models import AuditLog, MemoryChunk, Message, User, Workspace
from app.schemas.telegram import TelegramEvent
from app.services.embeddings import EmbeddingService


class TelegramWebhookVerificationError(PermissionError):
    pass


class TelegramFileDownloadError(RuntimeError):
    pass


class TelegramIngestService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.embedding_service = EmbeddingService()

    async def ingest(self, event: TelegramEvent) -> uuid.UUID:
        workspace = (
            await self.session.scalars(select(Workspace).where(Workspace.id == event.workspace_id))
        ).one()
        user = await self._get_or_create_user(event)
        await self.session.flush()
        content = event.text or f"[{event.event_type} stored at {event.file_storage_key}]"
        message = Message(
            workspace_id=event.workspace_id,
            telegram_message_id=event.telegram_message_id,
            sender_user_id=user.id,
            content=content,
            importance=classify_message_importance(content),
        )
        self.session.add(message)
        await self.session.flush()

        if message.importance != "normal":
            self.session.add(
                MemoryChunk(
                    workspace_id=event.workspace_id,
                    source_type="message",
                    source_id=message.id,
                    source_title=f"Telegram message {event.telegram_message_id or message.id}",
                    content=content,
                    embedding=self.embedding_service.embed_for_storage(content),
                )
            )
        self.session.add(
            AuditLog(
                organization_id=workspace.organization_id,
                workspace_id=event.workspace_id,
                actor_user_id=user.id,
                action="telegram.event.ingested",
                resource_type="message",
                resource_id=message.id,
                metadata_json={"event_type": event.event_type, "importance": message.importance},
            )
        )
        await self.session.commit()
        return message.id

    async def _get_or_create_user(self, event: TelegramEvent) -> User:
        if event.sender_telegram_user_id is not None:
            existing = (
                await self.session.scalars(
                    select(User).where(User.telegram_user_id == event.sender_telegram_user_id)
                )
            ).first()
            if existing:
                existing.display_name = event.sender_display_name
                return existing
        user = User(
            telegram_user_id=event.sender_telegram_user_id,
            display_name=event.sender_display_name,
        )
        self.session.add(user)
        return user


def classify_message_importance(text: str) -> str:
    lowered = text.lower()
    if any(marker in lowered for marker in ["decided", "agreed", "решили", "выбираем"]):
        return "decision"
    if any(marker in lowered for marker in ["i will", "todo", "сделаю", "deadline", "до пятницы"]):
        return "task"
    if any(marker in lowered for marker in ["blocked", "risk", "problem", "риск", "блокер"]):
        return "risk"
    if "@rhapsody" in lowered:
        return "explicit_query"
    return "normal"


def verify_telegram_webhook_secret(
    expected_secret: str | None,
    provided_secret: str | None,
) -> None:
    if not expected_secret:
        return
    if provided_secret != expected_secret:
        raise TelegramWebhookVerificationError("Invalid Telegram webhook secret token.")


def build_telegram_file_download_url(bot_token: str, file_path: str) -> str:
    return f"https://api.telegram.org/file/bot{bot_token}/{file_path.lstrip('/')}"


async def resolve_telegram_file_download_url(
    file_id: str,
    settings: Settings | None = None,
) -> str:
    resolved_settings = settings or get_settings()
    if not resolved_settings.telegram_bot_token:
        raise TelegramFileDownloadError("Telegram bot token is not configured.")

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(
            f"https://api.telegram.org/bot{resolved_settings.telegram_bot_token}/getFile",
            params={"file_id": file_id},
        )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok") or not payload.get("result", {}).get("file_path"):
        raise TelegramFileDownloadError("Telegram did not return a downloadable file path.")
    return build_telegram_file_download_url(
        resolved_settings.telegram_bot_token,
        payload["result"]["file_path"],
    )
