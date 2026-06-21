from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.calls.state_machine import ACTIVE_CALL_SESSION_STATUSES, assert_call_session_transition
from app.db.models import CallAudioChunk, CallSession, ListenerAccount


class CallSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_requested(
        self,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        telegram_chat_id: int,
        requested_by_user_id: UUID,
        live_meeting_session_id: UUID | None = None,
    ) -> CallSession:
        existing = await self.active_for_chat(workspace_id, telegram_chat_id)
        if existing is not None:
            return existing

        call_session = CallSession(
            organization_id=organization_id,
            workspace_id=workspace_id,
            telegram_chat_id=telegram_chat_id,
            requested_by_user_id=requested_by_user_id,
            live_meeting_session_id=live_meeting_session_id,
            status="REQUESTED",
        )
        self.session.add(call_session)
        await self.session.flush()
        return call_session

    async def active_for_chat(
        self,
        workspace_id: UUID,
        telegram_chat_id: int,
    ) -> CallSession | None:
        return (
            await self.session.scalars(
                select(CallSession)
                .where(
                    CallSession.workspace_id == workspace_id,
                    CallSession.telegram_chat_id == telegram_chat_id,
                    CallSession.status.in_(ACTIVE_CALL_SESSION_STATUSES),
                )
                .order_by(CallSession.created_at.desc())
            )
        ).first()

    async def for_live_session(self, live_meeting_session_id: UUID) -> CallSession | None:
        return (
            await self.session.scalars(
                select(CallSession).where(
                    CallSession.live_meeting_session_id == live_meeting_session_id
                )
            )
        ).first()

    async def transition(
        self,
        call_session: CallSession,
        target_status: str,
        *,
        failure_code: str | None = None,
        failure_message: str | None = None,
    ) -> CallSession:
        assert_call_session_transition(call_session.status, target_status)
        now = datetime.now(timezone.utc)
        if target_status == "CONNECTING" and call_session.started_at is None:
            call_session.started_at = now
        if target_status in {"JOINED", "RECORDING"} and call_session.joined_at is None:
            call_session.joined_at = now
        if target_status in {"COMPLETED", "FAILED", "CANCELLED"}:
            call_session.ended_at = now
        if target_status == "RECONNECTING":
            call_session.reconnect_count += 1
        if failure_code is not None:
            call_session.failure_code = failure_code
        if failure_message is not None:
            call_session.failure_message = failure_message
        call_session.status = target_status
        await self.session.flush()
        return call_session

    async def mark_audio_received(self, call_session: CallSession) -> CallSession:
        call_session.last_audio_at = datetime.now(timezone.utc)
        await self.session.flush()
        return call_session

    async def stale_recording_sessions(self, *, audio_timeout_seconds: int) -> list[CallSession]:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=audio_timeout_seconds)
        stale_after_audio = (
            CallSession.last_audio_at.is_not(None) & (CallSession.last_audio_at < cutoff)
        )
        stale_without_audio = (
            CallSession.last_audio_at.is_(None)
            & CallSession.joined_at.is_not(None)
            & (CallSession.joined_at < cutoff)
        )
        return list(
            await self.session.scalars(
                select(CallSession).where(
                    CallSession.status.in_({"RECORDING", "CONNECTED_NO_AUDIO", "RECONNECTING"}),
                    stale_after_audio | stale_without_audio,
                )
            )
        )


class ListenerAccountRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def available(self) -> list[ListenerAccount]:
        return list(
            await self.session.scalars(
                select(ListenerAccount)
                .where(ListenerAccount.status == "AVAILABLE")
                .order_by(ListenerAccount.failure_count.asc(), ListenerAccount.created_at.asc())
            )
        )

    async def reserve_for_call(self, call_session: CallSession) -> ListenerAccount | None:
        account = (
            await self.session.scalars(
                select(ListenerAccount)
                .where(
                    ListenerAccount.status == "AVAILABLE",
                    ListenerAccount.cooldown_until.is_(None)
                    | (ListenerAccount.cooldown_until <= datetime.now(timezone.utc)),
                )
                .order_by(ListenerAccount.failure_count.asc(), ListenerAccount.created_at.asc())
            )
        ).first()
        if account is None:
            return None
        account.status = "RESERVED"
        account.current_call_session_id = call_session.id
        call_session.listener_account_id = account.id
        await self.session.flush()
        return account

    async def mark_busy(self, account: ListenerAccount) -> ListenerAccount:
        account.status = "BUSY"
        account.last_heartbeat_at = datetime.now(timezone.utc)
        await self.session.flush()
        return account

    async def heartbeat(self, account: ListenerAccount) -> ListenerAccount:
        account.last_heartbeat_at = datetime.now(timezone.utc)
        await self.session.flush()
        return account

    async def release(self, account: ListenerAccount, *, status: str = "AVAILABLE") -> None:
        account.status = status
        account.current_call_session_id = None
        await self.session.flush()

    async def cooldown(self, account: ListenerAccount, *, seconds: int) -> None:
        account.status = "COOLDOWN"
        account.current_call_session_id = None
        account.failure_count += 1
        account.cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=seconds)
        await self.session.flush()


class CallAudioChunkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_spooled(
        self,
        *,
        call_session: CallSession,
        sequence_number: int,
        local_path: str,
        byte_size: int,
        duration_ms: int,
        content_type: str = "audio/wav",
    ) -> CallAudioChunk:
        existing = await self.get_by_sequence(call_session.id, sequence_number)
        if existing is not None:
            return existing
        chunk = CallAudioChunk(
            call_session_id=call_session.id,
            workspace_id=call_session.workspace_id,
            sequence_number=sequence_number,
            local_path=local_path,
            byte_size=byte_size,
            duration_ms=duration_ms,
            content_type=content_type,
            status="SPOOLED",
        )
        self.session.add(chunk)
        await self.session.flush()
        return chunk

    async def get(self, chunk_id: UUID) -> CallAudioChunk | None:
        return await self.session.get(CallAudioChunk, chunk_id)

    async def get_by_sequence(
        self,
        call_session_id: UUID,
        sequence_number: int,
    ) -> CallAudioChunk | None:
        return (
            await self.session.scalars(
                select(CallAudioChunk).where(
                    CallAudioChunk.call_session_id == call_session_id,
                    CallAudioChunk.sequence_number == sequence_number,
                )
            )
        ).first()

    async def pending_upload(self, *, limit: int = 50) -> list[CallAudioChunk]:
        return list(
            await self.session.scalars(
                select(CallAudioChunk)
                .where(CallAudioChunk.status == "SPOOLED")
                .order_by(CallAudioChunk.created_at.asc())
                .limit(limit)
            )
        )

    async def pending_transcription(self, *, limit: int = 50) -> list[CallAudioChunk]:
        return list(
            await self.session.scalars(
                select(CallAudioChunk)
                .where(CallAudioChunk.status.in_({"SPOOLED", "UPLOADED", "TRANSCRIBE_FAILED"}))
                .order_by(CallAudioChunk.created_at.asc())
                .limit(limit)
            )
        )

    async def mark_uploaded(self, chunk: CallAudioChunk, object_ref: str) -> CallAudioChunk:
        chunk.object_ref = object_ref
        chunk.status = "UPLOADED"
        await self.session.flush()
        return chunk

    async def mark_transcribed(self, chunk: CallAudioChunk, transcript: str) -> CallAudioChunk:
        chunk.transcript = transcript
        chunk.status = "TRANSCRIBED"
        await self.session.flush()
        return chunk

    async def mark_failed(
        self,
        chunk: CallAudioChunk,
        *,
        status: str,
        failure_code: str,
        failure_message: str,
    ) -> CallAudioChunk:
        chunk.status = status
        chunk.failure_code = failure_code
        chunk.failure_message = failure_message
        chunk.attempt_count += 1
        await self.session.flush()
        return chunk

    async def ordered_transcripts(self, call_session_id: UUID) -> list[str]:
        chunks = (
            await self.session.scalars(
                select(CallAudioChunk)
                .where(
                    CallAudioChunk.call_session_id == call_session_id,
                    CallAudioChunk.status == "TRANSCRIBED",
                )
                .order_by(CallAudioChunk.sequence_number.asc())
            )
        ).all()
        return [chunk.transcript or "" for chunk in chunks if (chunk.transcript or "").strip()]
