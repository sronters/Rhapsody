from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.bot.services import TelegramProductService
from app.calls.repository import (
    CallAudioChunkRepository,
    CallSessionRepository,
    ListenerAccountRepository,
)
from app.calls.state_machine import CallSessionStateError, assert_call_session_transition
from app.db.base import Base
from app.db.models import ListenerAccount


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


def test_call_session_state_machine_allows_expected_live_flow() -> None:
    assert_call_session_transition("REQUESTED", "CONNECTING")
    assert_call_session_transition("CONNECTING", "JOINED")
    assert_call_session_transition("JOINED", "RECORDING")
    assert_call_session_transition("RECORDING", "CONNECTED_NO_AUDIO")
    assert_call_session_transition("CONNECTED_NO_AUDIO", "RECONNECTING")
    assert_call_session_transition("RECONNECTING", "RECORDING")
    assert_call_session_transition("RECORDING", "FINALIZING")
    assert_call_session_transition("FINALIZING", "COMPLETED")


def test_call_session_state_machine_rejects_backwards_terminal_flow() -> None:
    with pytest.raises(CallSessionStateError, match="Cannot move"):
        assert_call_session_transition("COMPLETED", "RECORDING")


@pytest.mark.asyncio
async def test_call_session_repository_is_idempotent_for_active_chat(session_factory) -> None:
    async with session_factory() as session:
        context = await TelegramProductService(session).setup(
            telegram_user_id=1,
            display_name="User",
            telegram_chat_id=10,
            chat_title="Group",
        )
        repository = CallSessionRepository(session)

        first = await repository.create_requested(
            organization_id=context.organization_id,
            workspace_id=context.workspace_id,
            telegram_chat_id=10,
            requested_by_user_id=context.user_id,
        )
        second = await repository.create_requested(
            organization_id=context.organization_id,
            workspace_id=context.workspace_id,
            telegram_chat_id=10,
            requested_by_user_id=context.user_id,
        )

    assert first.id == second.id


@pytest.mark.asyncio
async def test_call_session_repository_stamps_operational_timestamps(session_factory) -> None:
    async with session_factory() as session:
        context = await TelegramProductService(session).setup(
            telegram_user_id=1,
            display_name="User",
            telegram_chat_id=10,
            chat_title="Group",
        )
        repository = CallSessionRepository(session)
        call_session = await repository.create_requested(
            organization_id=context.organization_id,
            workspace_id=context.workspace_id,
            telegram_chat_id=10,
            requested_by_user_id=context.user_id,
        )

        await repository.transition(call_session, "CONNECTING")
        await repository.transition(call_session, "JOINED")
        await repository.transition(call_session, "RECORDING")
        await repository.mark_audio_received(call_session)
        await repository.transition(call_session, "RECONNECTING")
        await repository.transition(call_session, "FAILED", failure_code="join_lost")

    assert call_session.started_at is not None
    assert call_session.joined_at is not None
    assert call_session.last_audio_at is not None
    assert call_session.ended_at is not None
    assert call_session.reconnect_count == 1
    assert call_session.failure_code == "join_lost"


@pytest.mark.asyncio
async def test_call_audio_chunk_repository_is_idempotent_by_sequence(session_factory) -> None:
    async with session_factory() as session:
        context = await TelegramProductService(session).setup(
            telegram_user_id=1,
            display_name="User",
            telegram_chat_id=10,
            chat_title="Group",
        )
        call_session = await CallSessionRepository(session).create_requested(
            organization_id=context.organization_id,
            workspace_id=context.workspace_id,
            telegram_chat_id=10,
            requested_by_user_id=context.user_id,
        )
        repository = CallAudioChunkRepository(session)

        first = await repository.create_spooled(
            call_session=call_session,
            sequence_number=1,
            local_path="spool/chunk-1.wav",
            byte_size=100,
            duration_ms=1000,
        )
        second = await repository.create_spooled(
            call_session=call_session,
            sequence_number=1,
            local_path="spool/chunk-1-duplicate.wav",
            byte_size=200,
            duration_ms=2000,
        )
        await repository.mark_transcribed(first, "hello")
        transcripts = await repository.ordered_transcripts(call_session.id)

    assert first.id == second.id
    assert second.local_path == "spool/chunk-1.wav"
    assert transcripts == ["hello"]


@pytest.mark.asyncio
async def test_listener_account_repository_reserves_and_cools_down(session_factory) -> None:
    async with session_factory() as session:
        context = await TelegramProductService(session).setup(
            telegram_user_id=1,
            display_name="User",
            telegram_chat_id=10,
            chat_title="Group",
        )
        call_session = await CallSessionRepository(session).create_requested(
            organization_id=context.organization_id,
            workspace_id=context.workspace_id,
            telegram_chat_id=10,
            requested_by_user_id=context.user_id,
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
        repository = ListenerAccountRepository(session)

        account = await repository.reserve_for_call(call_session)
        await repository.mark_busy(account)
        await repository.cooldown(account, seconds=30)

    assert account is not None
    assert call_session.listener_account_id == account.id
    assert account.status == "COOLDOWN"
    assert account.failure_count == 1
    assert account.cooldown_until is not None


@pytest.mark.asyncio
async def test_call_session_repository_detects_recording_without_audio(session_factory) -> None:
    async with session_factory() as session:
        context = await TelegramProductService(session).setup(
            telegram_user_id=1,
            display_name="User",
            telegram_chat_id=10,
            chat_title="Group",
        )
        repository = CallSessionRepository(session)
        call_session = await repository.create_requested(
            organization_id=context.organization_id,
            workspace_id=context.workspace_id,
            telegram_chat_id=10,
            requested_by_user_id=context.user_id,
        )
        await repository.transition(call_session, "CONNECTING")
        await repository.transition(call_session, "JOINED")
        await repository.transition(call_session, "RECORDING")
        call_session.joined_at = datetime.now(timezone.utc) - timedelta(seconds=30)
        stale = await repository.stale_recording_sessions(audio_timeout_seconds=15)

    assert [row.id for row in stale] == [call_session.id]
    assert call_session.last_audio_at is None
