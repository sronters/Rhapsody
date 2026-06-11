from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.services.document_parsing import extract_text_from_document
from app.services.embeddings import EmbeddingService
from app.services.meetings import extract_meeting_intelligence
from app.services.telegram import build_telegram_file_download_url


@dataclass(frozen=True)
class TelegramFileTransferPlan:
    download_url: str
    storage_key: str


@dataclass(frozen=True)
class DocumentIndexingPlan:
    extracted_text: str
    embedding_dimensions: int
    chunk_count_hint: int


def plan_telegram_file_transfer(
    bot_token: str,
    telegram_file_path: str,
    workspace_id: UUID,
    purpose: str,
) -> TelegramFileTransferPlan:
    filename = telegram_file_path.rsplit("/", maxsplit=1)[-1] or "telegram-file.bin"
    return TelegramFileTransferPlan(
        download_url=build_telegram_file_download_url(bot_token, telegram_file_path),
        storage_key=f"workspaces/{workspace_id}/telegram/{purpose}/{filename}",
    )


def plan_document_indexing(
    content: bytes,
    filename: str,
    content_type: str,
) -> DocumentIndexingPlan:
    text = extract_text_from_document(content, filename, content_type)
    embedding_service = EmbeddingService()
    embedding = embedding_service.embed_text(text[:4000])
    return DocumentIndexingPlan(
        extracted_text=text,
        embedding_dimensions=len(embedding),
        chunk_count_hint=max(1, len(text) // 1600 + 1),
    )


def deterministic_transcribe_audio_reference(storage_key: str) -> str:
    return f"Transcript placeholder for audio object {storage_key}. Configure Whisper for STT."


def deterministic_weekly_summary(workspace_name: str, highlights: list[str]) -> str:
    bullet_list = "\n".join(f"- {item}" for item in highlights) or "- No highlights captured."
    return f"Weekly summary for {workspace_name}:\n{bullet_list}"


def deterministic_meeting_extraction(transcript: str) -> dict:
    intelligence = extract_meeting_intelligence(transcript)
    return intelligence.model_dump()