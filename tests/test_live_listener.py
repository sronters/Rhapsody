from __future__ import annotations

import uuid
from dataclasses import dataclass
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.bot.handlers.commands import is_live_listening_chat_type
from app.bot.services import TelegramProductService
from app.core.config import Settings
from app.db.base import Base
from app.db.models import (
    AuditLog,
    CallAudioChunk,
    CallSession,
    ListenerAccount,
    LiveMeetingSession,
    Meeting,
    Task,
)
from app.listener.adapters import (
    ListenerCapturedChunk,
    ListenerConfigurationError,
    ListenerJoinError,
    ListenerRuntimeStatus,
    ListenerStartResult,
    ListenerStopResult,
)
from app.listener.service import LiveMeetingListenerService
from app.services.product_ai import LLMMeetingExtraction


class FakeAIClient:
    def __init__(self) -> None:
        self.settings = type("Settings", (), {"ai_mode": "test"})()

    async def extract_meeting(self, transcript: str) -> LLMMeetingExtraction:
        return LLMMeetingExtraction.model_validate(
            {
                "summary": "Live call reviewed launch readiness.",
                "tasks": [
                    {
                        "title": "Send launch update",
                        "assignee": "Aida",
                        "deadline": "2026-06-12",
                        "priority": "high",
                        "source_text": transcript,
                    }
                ],
                "decisions": [{"title": "Launch Friday", "rationale": "Team aligned."}],
                "risks": [{"title": "Support capacity", "severity": "medium"}],
                "follow_up": "Confirm support coverage.",
            }
        )

    async def answer_question(self, question, sources):
        return "Launch Friday [1]."


@dataclass
class FakeListenerAdapter:
    fail_start: bool = False
    transcript: str = "We decided to launch Friday. Aida will send the launch update."
    recorder_session: str | None = None

    async def start(
        self,
        session_id: UUID,
        telegram_chat_id: int,
        workspace_id: UUID,
        recorder_session: str | None = None,
    ) -> ListenerStartResult:
        self.recorder_session = recorder_session
        if self.fail_start:
            raise ListenerJoinError("No active group call exists.")
        return ListenerStartResult(audio_object_ref=f"live/{session_id}.ogg")

    async def stop(self, session_id: UUID) -> ListenerStopResult:
        return ListenerStopResult(
            transcript=self.transcript,
            audio_object_ref=f"live/{session_id}.ogg",
            chunks=(
                ListenerCapturedChunk(
                    sequence_number=1,
                    local_path=f"spool/{session_id}-000001.wav",
                    byte_size=128,
                    duration_ms=1000,
                    transcript=self.transcript,
                ),
            ),
        )

    async def status(self, session_id: UUID) -> ListenerRuntimeStatus:
        return ListenerRuntimeStatus(active=True, detail="Connected to group call.")


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


def listener_settings(**overrides: object) -> Settings:
    values = {
        "listener_enabled": True,
        "rhapsody_telegram_api_id": 12345,
        "rhapsody_telegram_api_hash": "hash",
        "stt_mode": "openai",
        "openai_api_key": "key",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.mark.asyncio
async def test_listen_fails_clearly_when_env_missing(session_factory) -> None:
    async with session_factory() as session:
        context = await TelegramProductService(session, ai_client=FakeAIClient()).setup(
            telegram_user_id=1,
            display_name="User",
            telegram_chat_id=10,
            chat_title="Group",
        )
        session.add(
            ListenerAccount(
                telegram_user_id=100,
                username="RhapsodyRecorder",
                display_name="Rhapsody Recorder",
                encrypted_session="encrypted",
                status="AVAILABLE",
            )
        )
        await session.flush()
        service = LiveMeetingListenerService(
            session,
            settings=Settings(_env_file=None, listener_enabled=False),
            adapter=FakeListenerAdapter(),
            ai_client=FakeAIClient(),
        )

        with pytest.raises(Exception, match="LISTENER_ENABLED=true"):
            await service.start_listening(context, 10)


@pytest.mark.asyncio
async def test_listen_fails_clearly_when_stt_missing(session_factory) -> None:
    async with session_factory() as session:
        context = await TelegramProductService(session, ai_client=FakeAIClient()).setup(
            telegram_user_id=1,
            display_name="User",
            telegram_chat_id=10,
            chat_title="Group",
        )
        session.add(
            ListenerAccount(
                telegram_user_id=100,
                username="RhapsodyRecorder",
                display_name="Rhapsody Recorder",
                encrypted_session="encrypted",
                status="AVAILABLE",
            )
        )
        await session.flush()
        service = LiveMeetingListenerService(
            session,
            settings=listener_settings(stt_mode=None),
            adapter=FakeListenerAdapter(),
            ai_client=FakeAIClient(),
        )

        with pytest.raises(Exception, match="STT_MODE"):
            await service.start_listening(context, 10)


@pytest.mark.asyncio
async def test_listener_failure_does_not_create_fake_active_state(session_factory) -> None:
    async with session_factory() as session:
        context = await TelegramProductService(session, ai_client=FakeAIClient()).setup(
            telegram_user_id=1,
            display_name="User",
            telegram_chat_id=10,
            chat_title="Group",
        )
        session.add(
            ListenerAccount(
                telegram_user_id=100,
                username="RhapsodyRecorder",
                display_name="Rhapsody Recorder",
                encrypted_session="encrypted",
                status="AVAILABLE",
            )
        )
        await session.flush()
        service = LiveMeetingListenerService(
            session,
            settings=listener_settings(),
            adapter=FakeListenerAdapter(fail_start=True),
            ai_client=FakeAIClient(),
        )

        with pytest.raises(ListenerJoinError, match="No active group call"):
            await service.start_listening(context, 10)
        status = await service.live_status(context, 10)
        sessions = (await session.scalars(select(LiveMeetingSession))).all()
        call_sessions = (await session.scalars(select(CallSession))).all()
        audit = (await session.scalars(select(AuditLog))).all()

    assert not status.active
    assert sessions[0].status == "failed"
    assert call_sessions[0].status == "FAILED"
    assert call_sessions[0].failure_code == "ListenerJoinError"
    assert any(entry.action == "live_listener.start_failed" for entry in audit)


@pytest.mark.asyncio
async def test_listen_requires_available_recorder_before_creating_session(session_factory) -> None:
    async with session_factory() as session:
        context = await TelegramProductService(session, ai_client=FakeAIClient()).setup(
            telegram_user_id=1,
            display_name="User",
            telegram_chat_id=10,
            chat_title="Group",
        )
        service = LiveMeetingListenerService(
            session,
            settings=listener_settings(),
            adapter=FakeListenerAdapter(),
            ai_client=FakeAIClient(),
        )

        with pytest.raises(ListenerConfigurationError, match="No Rhapsody Recorder"):
            await service.start_listening(context, 10)
        sessions = (await session.scalars(select(LiveMeetingSession))).all()
        call_sessions = (await session.scalars(select(CallSession))).all()

    assert sessions == []
    assert call_sessions == []


@pytest.mark.asyncio
async def test_listener_status_transition_and_stop_processes_meeting(session_factory) -> None:
    async with session_factory() as session:
        context = await TelegramProductService(session, ai_client=FakeAIClient()).setup(
            telegram_user_id=1,
            display_name="User",
            telegram_chat_id=10,
            chat_title="Group",
        )
        session.add(
            ListenerAccount(
                telegram_user_id=100,
                display_name="Rhapsody Recorder",
                encrypted_session="encrypted",
                status="AVAILABLE",
            )
        )
        await session.flush()
        adapter = FakeListenerAdapter()
        service = LiveMeetingListenerService(
            session,
            settings=listener_settings(),
            adapter=adapter,
            ai_client=FakeAIClient(),
        )

        started = await service.start_listening(context, 10)
        status = await service.live_status(context, 10)
        stopped = await service.stop_listening(context, 10)
        live_session = await session.get(LiveMeetingSession, started.session_id)
        call_session = (await session.scalars(select(CallSession))).one()
        listener_account = (await session.scalars(select(ListenerAccount))).one()
        chunks = (await session.scalars(select(CallAudioChunk))).all()
        meetings = (await session.scalars(select(Meeting))).all()
        tasks = (await session.scalars(select(Task))).all()
        audit = (await session.scalars(select(AuditLog))).all()

    assert "now listening" in started.message
    assert status.active
    assert "Итоги встречи" in stopped.report
    assert live_session.status == "completed"
    assert call_session.status == "COMPLETED"
    assert call_session.joined_at is not None
    assert call_session.last_audio_at is not None
    assert call_session.ended_at is not None
    assert call_session.listener_account_id == listener_account.id
    assert adapter.recorder_session == "encrypted"
    assert listener_account.status == "AVAILABLE"
    assert listener_account.current_call_session_id is None
    assert len(chunks) == 1
    assert chunks[0].sequence_number == 1
    assert chunks[0].status == "TRANSCRIBED"
    assert chunks[0].transcript == FakeListenerAdapter.transcript
    assert live_session.transcript
    assert meetings
    assert tasks
    assert any(entry.action == "live_listener.started" for entry in audit)
    assert any(entry.action == "live_listener.stopped" for entry in audit)


@pytest.mark.asyncio
async def test_call_setup_uses_rhapsody_recorder_pool(session_factory) -> None:
    async with session_factory() as session:
        context = await TelegramProductService(session, ai_client=FakeAIClient()).setup(
            telegram_user_id=1,
            display_name="User",
            telegram_chat_id=10,
            chat_title="Group",
        )
        session.add(
            ListenerAccount(
                telegram_user_id=100,
                username="RhapsodyRecorder",
                display_name="Rhapsody Recorder",
                encrypted_session="encrypted",
                status="AVAILABLE",
            )
        )
        await session.flush()
        result = await LiveMeetingListenerService(
            session,
            settings=listener_settings(),
            adapter=FakeListenerAdapter(),
            ai_client=FakeAIClient(),
        ).call_setup(context, 10)

    assert result.ready
    assert "@RhapsodyRecorder" in result.message
    assert "Ordinary users do not need" in result.message


def test_live_listening_is_group_only() -> None:
    assert is_live_listening_chat_type("group")
    assert is_live_listening_chat_type("supergroup")
    assert not is_live_listening_chat_type("private")
