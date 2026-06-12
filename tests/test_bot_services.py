from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.bot.services import EMPTY_MEMORY_MESSAGE, TelegramProductService
from app.db.base import Base
from app.db.models import (
    AuditLog,
    Decision,
    Document,
    Meeting,
    MemoryChunk,
    Task,
    TelegramChat,
    WorkspaceMember,
)
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


class SourceAwareAIClient(FakeAIClient):
    async def extract_meeting(self, transcript: str) -> LLMMeetingExtraction:
        lowered = transcript.lower()
        if "postgres" in lowered:
            return LLMMeetingExtraction.model_validate(
                {
                    "summary": "This Alpha project decided to use Postgres.",
                    "tasks": [],
                    "decisions": [{"title": "Use Postgres"}],
                    "risks": [],
                    "follow_up": "",
                }
            )
        if "qdrant" in lowered:
            return LLMMeetingExtraction.model_validate(
                {
                    "summary": "The group project decided to use Qdrant.",
                    "tasks": [{"title": "Verify group scope"}],
                    "decisions": [{"title": "Use Qdrant"}],
                    "risks": [],
                    "follow_up": "",
                }
            )
        return LLMMeetingExtraction.model_validate(
            {
                "summary": "This Alpha project decided to use Gemini.",
                "tasks": [{"title": "Test documents", "assignee": "Baktiyar"}],
                "decisions": [{"title": "Use Gemini"}],
                "risks": [],
                "follow_up": "",
            }
        )

    async def answer_question(self, question, sources):
        source_text = "\n".join(source.excerpt for source in sources)
        if "Postgres" in source_text:
            return "Postgres was selected [1]."
        if "Qdrant" in source_text:
            return "Qdrant was selected [1]."
        if "Gemini" in source_text:
            return "Gemini was selected [1]."
        return "I do not have relevant project memory."


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
    assert first.role == "owner"
    assert second.role == "owner"


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
async def test_project_creation_and_switching_keeps_data_isolated(session_factory) -> None:
    async with session_factory() as session:
        service = TelegramProductService(session, ai_client=FakeAIClient())
        first = await service.setup(telegram_user_id=1, display_name="Boss", telegram_chat_id=10)
        await service.ingest_document_text(first, "Alpha context.", name="alpha.txt")
        created = await service.create_project(first, 10, "Beta", "Team")
        active = await service.context_for_chat(1, 10)
        await service.ingest_document_text(active, "Beta context.", name="beta.txt")
        projects = await service.list_projects(active, 10)
        await service.use_project(active, 10, "1")
        switched = await service.context_for_chat(1, 10)
        memory = (await session.scalars(select(MemoryChunk))).all()

    assert "Beta" in created
    assert "Beta" in projects
    assert active.workspace_id != first.workspace_id
    assert switched.workspace_id in {first.workspace_id, active.workspace_id}
    assert {chunk.workspace_id for chunk in memory} == {first.workspace_id, active.workspace_id}


@pytest.mark.asyncio
async def test_private_project_selection_is_scoped_per_user(session_factory) -> None:
    async with session_factory() as session:
        service = TelegramProductService(session, ai_client=FakeAIClient())
        owner = await service.setup(telegram_user_id=1, display_name="Boss", telegram_chat_id=10)
        member = await service.setup(telegram_user_id=2, display_name="Member", telegram_chat_id=10)
    assert owner.workspace_id != member.workspace_id
    assert owner.role == "owner"
    assert member.role == "owner"


@pytest.mark.asyncio
async def test_group_selected_project_requires_membership(session_factory) -> None:
    async with session_factory() as session:
        service = TelegramProductService(session, ai_client=FakeAIClient())
        await service.create_project_for_telegram_user(
            telegram_user_id=1,
            display_name="Owner",
            telegram_chat_id=-100,
            chat_type="group",
            name="Group Project",
            chat_title="Team",
        )

        intruder = await service.context_for_chat(2, -100, "group")

    assert intruder is None


@pytest.mark.asyncio
async def test_group_project_creation_rejects_non_manager_when_group_already_bound(
    session_factory,
) -> None:
    async with session_factory() as session:
        service = TelegramProductService(session, ai_client=FakeAIClient())
        await service.create_project_for_telegram_user(
            telegram_user_id=1,
            display_name="Owner",
            telegram_chat_id=-100,
            chat_type="group",
            name="Group Project",
            chat_title="Team",
        )

        with pytest.raises(PermissionError):
            await service.create_project_for_telegram_user(
                telegram_user_id=2,
                display_name="Intruder",
                telegram_chat_id=-100,
                chat_type="group",
                name="Hijack",
                chat_title="Team",
            )

        context = await service.context_for_chat(1, -100, "group")

    assert context is not None
    assert context.workspace_name == "Group Project"


@pytest.mark.asyncio
async def test_second_user_cannot_use_another_users_private_project(session_factory) -> None:
    async with session_factory() as session:
        service = TelegramProductService(session, ai_client=SourceAwareAIClient())
        await service.create_project_for_telegram_user(1, "Owner", 10, "private", "Alpha")
        owner = await service.context_for_chat(1, 10, "private")
        await service.ingest_meeting(
            owner,
            "In Alpha we decided to use Gemini. Baktiyar must test documents tomorrow.",
        )

        other = await service.setup(2, "Other", 20, chat_type="private")
        projects = await service.list_available_projects(2, "Other", 20, "private")
        switch_result = await service.use_project_for_telegram_user(
            2,
            "Other",
            20,
            "private",
            "Alpha",
        )
        other_answer = await service.ask(other, "What did we decide?")

    assert "Alpha" not in projects
    assert "Не нашёл проект" in switch_result
    assert other_answer == EMPTY_MEMORY_MESSAGE


@pytest.mark.asyncio
async def test_same_private_project_name_for_different_users_stays_isolated(
    session_factory,
) -> None:
    async with session_factory() as session:
        service = TelegramProductService(session, ai_client=SourceAwareAIClient())
        await service.create_project_for_telegram_user(1, "User A", 10, "private", "Alpha")
        user_a_alpha = await service.context_for_chat(1, 10, "private")
        await service.ingest_meeting(
            user_a_alpha,
            "In Alpha we decided to use Gemini. Baktiyar must test documents tomorrow.",
        )

        await service.create_project_for_telegram_user(2, "User B", 20, "private", "Alpha")
        user_b_alpha = await service.context_for_chat(2, 20, "private")
        await service.ingest_meeting(
            user_b_alpha,
            "In my Alpha project we decided to use Postgres.",
        )

        user_b_answer = await service.ask(user_b_alpha, "What did we decide?")
        user_b_tasks = await service.list_tasks(user_b_alpha)
        user_b_decisions = await service.list_decisions(user_b_alpha)
        user_b_audit = await service.list_audit(user_b_alpha)
        user_a_answer = await service.ask(user_a_alpha, "What did we decide?")
        user_a_tasks = await service.list_tasks(user_a_alpha)
        user_a_decisions = await service.list_decisions(user_a_alpha)
        memberships = (await session.scalars(select(WorkspaceMember))).all()

    assert user_a_alpha.workspace_id != user_b_alpha.workspace_id
    assert "Postgres" in user_b_answer
    assert "Gemini" not in user_b_answer
    assert "Baktiyar" not in user_b_tasks
    assert "Use Gemini" not in user_b_decisions
    assert "Gemini" not in user_b_audit
    assert "Gemini" in user_a_answer
    assert "Postgres" not in user_a_answer
    assert "Test documents" in user_a_tasks
    assert "Use Gemini" in user_a_decisions
    user_a_members = {
        member.user_id for member in memberships if member.workspace_id == user_a_alpha.workspace_id
    }
    user_b_members = {
        member.user_id for member in memberships if member.workspace_id == user_b_alpha.workspace_id
    }
    assert user_a_members == {
        user_a_alpha.user_id
    }
    assert user_b_members == {
        user_b_alpha.user_id
    }


@pytest.mark.asyncio
async def test_non_manager_cannot_rebind_bound_group_to_own_project(
    session_factory,
) -> None:
    async with session_factory() as session:
        service = TelegramProductService(session, ai_client=SourceAwareAIClient())
        await service.create_project_for_telegram_user(
            1,
            "Owner",
            -100,
            "group",
            "GroupProject",
            "Team",
        )
        group_context = await service.context_for_chat(1, -100, "group")
        await service.ingest_meeting(
            group_context,
            "In GroupProject we decided to use Qdrant for vector search.",
        )
        await service.create_project_for_telegram_user(2, "Intruder", 20, "private", "Evil")

        with pytest.raises(PermissionError):
            await service.use_project_for_telegram_user(
                2,
                "Intruder",
                -100,
                "group",
                "Evil",
                "Team",
            )

        owner_group_context = await service.context_for_chat(1, -100, "group")
        intruder_group_context = await service.context_for_chat(2, -100, "group")
        answer = await service.ask(owner_group_context, "What did this group decide?")
        tasks = await service.list_tasks(owner_group_context)
        decisions = await service.list_decisions(owner_group_context)
        audit = await service.list_audit(owner_group_context)
        active_group_chats = (
            await session.scalars(
                select(TelegramChat).where(
                    TelegramChat.telegram_chat_id == -100,
                    TelegramChat.selected_by_user_id.is_(None),
                    TelegramChat.is_active.is_(True),
                )
            )
        ).all()

    assert owner_group_context.workspace_name == "GroupProject"
    assert intruder_group_context is None
    assert "Qdrant" in answer
    assert "Evil" not in answer
    assert "Postgres" not in answer
    assert "Verify group scope" in tasks
    assert "Use Qdrant" in decisions
    assert "workspace.created" in audit
    assert len(active_group_chats) == 1
    assert active_group_chats[0].workspace_id == owner_group_context.workspace_id


@pytest.mark.asyncio
async def test_private_project_switching_keeps_memory_tasks_decisions_and_audit_isolated(
    session_factory,
) -> None:
    async with session_factory() as session:
        service = TelegramProductService(session, ai_client=FakeAIClient())
        await service.create_project_for_telegram_user(1, "Owner", 10, "private", "Alpha")
        alpha = await service.context_for_chat(1, 10, "private")
        await service.ingest_meeting(alpha, "Alpha meeting transcript")
        await service.ingest_document_text(alpha, "Alpha-only document text.", name="alpha.txt")

        await service.create_project_for_telegram_user(1, "Owner", 10, "private", "Beta")
        beta = await service.context_for_chat(1, 10, "private")
        await service.ingest_document_text(beta, "Beta-only document text.", name="beta.txt")

        beta_answer = await service.ask(beta, "What document text exists?")
        beta_tasks = await service.list_tasks(beta)
        beta_decisions = await service.list_decisions(beta)
        beta_audit = await service.list_audit(beta)
        await service.use_project_for_telegram_user(1, "Owner", 10, "private", "Alpha")
        alpha_again = await service.context_for_chat(1, 10, "private")
        alpha_answer = await service.ask(alpha_again, "What document text exists?")
        documents = (await session.scalars(select(Document))).all()
        chunks = (await session.scalars(select(MemoryChunk))).all()

    assert alpha.workspace_id != beta.workspace_id
    assert "alpha.txt" not in beta_answer
    assert "beta.txt" in beta_answer
    assert "Prepare launch checklist" not in beta_tasks
    assert "Use Supplier X" not in beta_decisions
    assert "meeting.ingested" not in beta_audit
    assert "alpha.txt" in alpha_answer
    assert {document.workspace_id for document in documents} == {
        alpha.workspace_id,
        beta.workspace_id,
    }
    assert {chunk.workspace_id for chunk in chunks} == {alpha.workspace_id, beta.workspace_id}
    assert all(document.uploaded_by_user_id is not None for document in documents)


@pytest.mark.asyncio
async def test_meeting_document_ask_tasks_decisions_audit_flow(session_factory) -> None:
    async with session_factory() as session:
        service = TelegramProductService(session, ai_client=FakeAIClient())
        context = await service.setup(telegram_user_id=1, display_name="User", telegram_chat_id=10)

        meeting_text = await service.ingest_meeting(context, "Launch transcript")
        document_text = await service.ingest_document_text(context, "Supplier X met compliance.")
        answer = await service.ask(context, "Why Supplier X?")
        tasks = await service.list_tasks(context)
        task_detail = await service.task_detail(context, 1)
        decisions = await service.list_decisions(context)
        decision_detail = await service.decision_detail(context, 1)
        digest = await service.digest(context, 7)
        attention = await service.attention(context)
        topics = await service.topics(context)
        audit = await service.list_audit(context)
        persisted_meetings = (await session.scalars(select(Meeting))).all()
        persisted_tasks = (await session.scalars(select(Task))).all()
        persisted_decisions = (await session.scalars(select(Decision))).all()
        persisted_memory = (await session.scalars(select(MemoryChunk))).all()
        persisted_audit = (await session.scalars(select(AuditLog))).all()

    assert "Итоги встречи" in meeting_text
    assert "Document saved and indexed" in document_text
    assert "Источники:" in answer
    assert "Prepare launch checklist" in tasks
    assert "Задача 1" in task_detail
    assert "Use Supplier X" in decisions
    assert "Источник: Meeting" in decisions
    assert "Решение 1" in decision_detail
    assert "Дайджест" in digest
    assert "Vendor approval delay" in attention
    assert "Темы" in topics
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

    assert "Итоги встречи" in result
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
    assert "Задачи не найдены." in formatted
    assert "Решения не найдены." in formatted
    assert "Риски не найдены." in formatted
    assert "Не указаны." in formatted


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

    assert "Статус: done" in result
    assert "task.status_updated" in audit
