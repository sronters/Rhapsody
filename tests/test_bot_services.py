from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.bot.services import EMPTY_MEMORY_MESSAGE, TelegramProductService
from app.db.base import Base
from app.db.models import AuditLog, Decision, Meeting, MemoryChunk, Task, TelegramChat
from app.services.document_parsing import UnsupportedDocumentTypeError
from app.services.product_ai import AIConfigurationError, AIResponseError, LLMMeetingExtraction


class FakeAIClient:
    def __init__(self) -> None:
        self.settings = type("Settings", (), {"ai_mode": "test"})()

    async def extract_meeting(self, transcript: str) -> LLMMeetingExtraction:
        return LLMMeetingExtraction.model_validate(
            {
                "summary": "The team reviewed launch readiness.",
                "tasks": [{"title": "Prepare launch checklist"}],
                "decisions": [{"title": "Use Supplier X", "rationale": "It met compliance."}],
                "risks": [{"title": "Vendor approval delay", "severity": "high"}],
                "follow_up": "Confirm owners.",
            }
        )

    async def answer_question(self, question, sources):
        return "Supplier X was selected for compliance [1]."


class InvalidAIClient(FakeAIClient):
    async def extract_meeting(self, transcript: str) -> LLMMeetingExtraction:
        raise AIResponseError("The AI response was not valid meeting JSON.")


class FakeSTTService:
    async def transcribe(self, content: bytes, filename: str, content_type: str | None) -> str:
        return "We decided to launch. Prepare launch checklist by 2026-06-12."


class FakeImageService:
    async def describe_image(self, content: bytes, content_type: str | None) -> str:
        return "Screenshot text: Supplier X compliance approval."


@pytest.fixture
async def session_factory():
    engine = create_async_engine(f"sqlite+aiosqlite:///file:{uuid.uuid4()}?mode=memory&cache=shared")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_setup_creates_and_reuses_workspace(session_factory) -> None:
    async with session_factory() as session:
        service = TelegramProductService(session, ai_client=FakeAIClient())
        first = await service.setup(telegram_user_id=1, display_name="User", telegram_chat_id=10)
        second = await service.setup(telegram_user_id=1, display_name="User", telegram_chat_id=10)

    assert first.workspace_id == second.workspace_id
    assert first.user_id == second.user_id


@pytest.mark.asyncio
async def test_setup_isolates_group_chat_workspaces(session_factory) -> None:
    async with session_factory() as session:
        service = TelegramProductService(session, ai_client=FakeAIClient())
        first = await service.setup(
            telegram_user_id=1,
            display_name="User",
            telegram_chat_id=10,
            chat_title="Group A",
        )
        second = await service.setup(
            telegram_user_id=1,
            display_name="User",
            telegram_chat_id=20,
            chat_title="Group B",
        )
        chats = (await session.scalars(select(TelegramChat))).all()

    assert first.workspace_id != second.workspace_id
    assert {chat.telegram_chat_id for chat in chats} == {10, 20}


@pytest.mark.asyncio
async def test_meeting_document_ask_tasks_decisions_audit_flow(session_factory) -> None:
    async with session_factory() as session:
        service = TelegramProductService(session, ai_client=FakeAIClient())
        context = await service.setup(telegram_user_id=1, display_name="User", telegram_chat_id=10)

        meeting_text = await service.ingest_meeting(context, "Launch transcript")
        document_text = await service.ingest_document_text(context, "Supplier X met compliance.")
        answer = await service.ask(context, "Why Supplier X?")
        tasks = await service.list_tasks(context)
        decisions = await service.list_decisions(context)
        audit = await service.list_audit(context)
        persisted_meetings = (await session.scalars(select(Meeting))).all()
        persisted_tasks = (await session.scalars(select(Task))).all()
        persisted_decisions = (await session.scalars(select(Decision))).all()
        persisted_memory = (await session.scalars(select(MemoryChunk))).all()
        persisted_audit = (await session.scalars(select(AuditLog))).all()

    assert "🧠 Meeting Summary" in meeting_text
    assert "Document saved and indexed" in document_text
    assert "Sources:" in answer
    assert "Prepare launch checklist" in tasks
    assert "Use Supplier X" in decisions
    assert "meeting.ingested" in audit
    assert persisted_meetings
    assert persisted_tasks
    assert persisted_decisions
    assert persisted_memory
    assert persisted_audit
    assert "{" not in meeting_text
    assert "Traceback" not in meeting_text


@pytest.mark.asyncio
async def test_meeting_recording_uses_stt_then_persists(session_factory) -> None:
    async with session_factory() as session:
        service = TelegramProductService(
            session,
            ai_client=FakeAIClient(),
            stt_service=FakeSTTService(),
        )
        context = await service.setup(telegram_user_id=1, display_name="User", telegram_chat_id=10)

        result = await service.ingest_meeting_media(
            context,
            b"audio-bytes",
            "meeting.ogg",
            "audio/ogg",
        )
        meetings = (await session.scalars(select(Meeting))).all()
        tasks = (await session.scalars(select(Task))).all()

    assert "🧠 Meeting Summary" in result
    assert meetings
    assert tasks


@pytest.mark.asyncio
async def test_image_ingestion_uses_vision_then_indexes_memory(session_factory) -> None:
    async with session_factory() as session:
        service = TelegramProductService(
            session,
            ai_client=FakeAIClient(),
            image_service=FakeImageService(),
        )
        context = await service.setup(telegram_user_id=1, display_name="User", telegram_chat_id=10)

        result = await service.ingest_image(context, b"image-bytes", "screen.png", "image/png")
        memory = (await session.scalars(select(MemoryChunk))).all()

    assert "Image saved and indexed" in result
    assert any("Supplier X" in chunk.content for chunk in memory)


@pytest.mark.asyncio
async def test_group_recording_transcript_saved_to_memory(session_factory) -> None:
    async with session_factory() as session:
        service = TelegramProductService(
            session,
            ai_client=FakeAIClient(),
            stt_service=FakeSTTService(),
        )
        context = await service.setup(telegram_user_id=1, display_name="User", telegram_chat_id=10)

        result = await service.ingest_media_message(
            context,
            123,
            b"audio-bytes",
            "voice.ogg",
            "audio/ogg",
        )
        memory = (await session.scalars(select(MemoryChunk))).all()

    assert "Recording transcribed" in result
    assert any("Transcribed Telegram media" in chunk.content for chunk in memory)


@pytest.mark.asyncio
async def test_invalid_llm_json_returns_clean_error(session_factory) -> None:
    async with session_factory() as session:
        service = TelegramProductService(session, ai_client=InvalidAIClient())
        context = await service.setup(telegram_user_id=1, display_name="User", telegram_chat_id=10)

        with pytest.raises(AIResponseError, match="valid meeting JSON"):
            await service.ingest_meeting(context, "Launch transcript")


@pytest.mark.asyncio
async def test_memory_empty_response(session_factory) -> None:
    async with session_factory() as session:
        service = TelegramProductService(session, ai_client=FakeAIClient())
        context = await service.setup(telegram_user_id=1, display_name="User", telegram_chat_id=10)
        answer = await service.ask(context, "What happened?")

    assert answer == EMPTY_MEMORY_MESSAGE


@pytest.mark.asyncio
async def test_document_file_unsupported_type(session_factory) -> None:
    async with session_factory() as session:
        service = TelegramProductService(session, ai_client=FakeAIClient())
        context = await service.setup(telegram_user_id=1, display_name="User", telegram_chat_id=10)

        with pytest.raises(UnsupportedDocumentTypeError, match="Unsupported file type"):
            await service.ingest_document_file(context, b"data", "archive.zip", "application/zip")


def test_empty_task_decision_formatting() -> None:
    extraction = LLMMeetingExtraction(summary="Summary", follow_up="")

    from app.bot.services import format_meeting_extraction

    formatted = format_meeting_extraction(extraction)

    assert "No tasks identified." in formatted
    assert "No decisions identified." in formatted
    assert "No risks identified." in formatted
    assert "No follow-up suggested." in formatted


def test_provider_error_message_for_missing_provider() -> None:
    from app.bot.services import provider_error_message

    assert provider_error_message(AIConfigurationError("OPENAI_API_KEY is required")) == (
        "OPENAI_API_KEY is required"
    )


def test_provider_error_message_for_quota_error() -> None:
    from app.bot.services import provider_error_message

    request = httpx.Request("POST", "https://api.openai.com/v1/audio/transcriptions")
    response = httpx.Response(429, request=request)
    exc = httpx.HTTPStatusError("quota", request=request, response=response)

    assert "quota" in provider_error_message(exc).lower()


@pytest.mark.asyncio
async def test_task_status_update_writes_audit_log(session_factory) -> None:
    async with session_factory() as session:
        service = TelegramProductService(session, ai_client=FakeAIClient())
        context = await service.setup(telegram_user_id=1, display_name="User", telegram_chat_id=10)
        await service.ingest_meeting(context, "Launch transcript")

        result = await service.update_task_status(context, 1, "done")
        audit = await service.list_audit(context)

    assert "Status: done" in result
    assert "task.status_updated" in audit
