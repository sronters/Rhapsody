from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.services import BotContext, TelegramProductService
from app.calls.repository import (
    CallAudioChunkRepository,
    CallSessionRepository,
    ListenerAccountRepository,
)
from app.core.config import Settings, get_settings
from app.db.models import AuditLog, CallSession, ListenerAccount, LiveMeetingSession, Workspace
from app.i18n import t
from app.listener.adapters import (
    ListenerConfigurationError,
    ListenerError,
    ListenerJoinError,
    ListenerRuntimeStatus,
    ListenerStopResult,
    MeetingListenerAdapter,
    MTProtoMeetingListenerAdapter,
    validate_listener_configuration,
)
from app.services.crypto import SecretCipher
from app.services.product_ai import ProductAIClient

ACTIVE_LIVE_STATUSES = (
    "start_requested",
    "starting",
    "listening",
    "stop_requested",
    "stopping",
    "transcribing",
    "analyzing",
)
START_WAIT_SECONDS = 30
STOP_WAIT_SECONDS = 180
POLL_SECONDS = 1


@dataclass(frozen=True)
class LiveListenStart:
    session_id: UUID
    message: str


@dataclass(frozen=True)
class LiveListenStop:
    session_id: UUID
    report: str


@dataclass(frozen=True)
class LiveListenStatus:
    active: bool
    message: str


@dataclass(frozen=True)
class RecorderSetupStatus:
    ready: bool
    message: str


class LiveMeetingListenerService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings | None = None,
        adapter: MeetingListenerAdapter | None = None,
        ai_client: ProductAIClient | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.adapter = adapter or MTProtoMeetingListenerAdapter(self.settings)
        self.ai_client = ai_client
        self.inline_runtime = adapter is not None

    async def start_listening(
        self,
        context: BotContext,
        telegram_chat_id: int,
    ) -> LiveListenStart:
        validate_listener_configuration(self.settings)
        existing = await self._active_session(context.workspace_id, telegram_chat_id)
        if existing is not None:
            if existing.status in {"start_requested", "starting"}:
                started = await self._wait_for_terminal_start(existing.id)
                return LiveListenStart(
                    session_id=started.id,
                    message=(
                        "Rhapsody is now listening to this call and will generate meeting notes."
                    ),
                )
            return LiveListenStart(
                session_id=existing.id,
                message="Rhapsody is already listening to this group's active call.",
            )
        if not await self._has_recorder_capacity():
            raise ListenerConfigurationError(
                "No Rhapsody Recorder account is available. Run /connect_calls or ask an "
                "operator to add a recorder account to the listener pool."
            )

        live_session = LiveMeetingSession(
            workspace_id=context.workspace_id,
            telegram_chat_id=telegram_chat_id,
            started_by_user_id=context.user_id,
            started_at=datetime.now(timezone.utc),
            status="start_requested",
        )
        self.session.add(live_session)
        await self.session.flush()
        await CallSessionRepository(self.session).create_requested(
            organization_id=context.organization_id,
            workspace_id=context.workspace_id,
            telegram_chat_id=telegram_chat_id,
            requested_by_user_id=context.user_id,
            live_meeting_session_id=live_session.id,
        )
        self._audit(
            context,
            "live_listener.start_requested",
            live_session.id,
            {"telegram_chat_id": telegram_chat_id},
        )
        await self.session.commit()

        if not self.inline_runtime:
            started = await self._wait_for_terminal_start(live_session.id)
            return LiveListenStart(
                session_id=started.id,
                message="Rhapsody is now listening to this call and will generate meeting notes.",
            )

        await self.process_start_request(live_session.id)
        await self.session.refresh(live_session)
        if live_session.status == "failed":
            raise ListenerJoinError(live_session.error_message or "Live listener failed to start.")
        return LiveListenStart(
            session_id=live_session.id,
            message="Rhapsody is now listening to this call and will generate meeting notes.",
        )

    async def process_start_request(self, live_session_id: UUID) -> None:
        live_session = await self.session.get(LiveMeetingSession, live_session_id)
        if live_session is None or live_session.status not in {"start_requested", "starting"}:
            return
        context = await self._context_for_session(live_session)
        call_session = await self._call_session_for_live_session(live_session, context)
        call_repository = CallSessionRepository(self.session)
        listener_account_repository = ListenerAccountRepository(self.session)
        listener_account = await self._reserve_listener_account(call_session)
        if listener_account is None and not self.settings.telegram_user_session:
            live_session.status = "failed"
            live_session.error_message = "No Rhapsody Recorder account is available."
            await call_repository.transition(
                call_session,
                "FAILED",
                failure_code="RecorderUnavailable",
                failure_message=live_session.error_message,
            )
            await self.session.commit()
            raise ListenerConfigurationError(live_session.error_message)
        live_session.status = "starting"
        await call_repository.transition(call_session, "CONNECTING")
        await self.session.commit()

        try:
            result = await self.adapter.start(
                live_session.id,
                live_session.telegram_chat_id,
                live_session.workspace_id,
                self._recorder_session(listener_account),
            )
        except ListenerError as exc:
            live_session.status = "failed"
            live_session.error_message = str(exc)
            await call_repository.transition(
                call_session,
                "FAILED",
                failure_code=exc.__class__.__name__,
                failure_message=str(exc),
            )
            if listener_account is not None:
                await listener_account_repository.cooldown(listener_account, seconds=60)
            self._audit(
                context,
                "live_listener.start_failed",
                live_session.id,
                {"error": str(exc)},
            )
            await self.session.commit()
            raise

        live_session.status = "listening"
        live_session.audio_object_ref = result.audio_object_ref
        await call_repository.transition(call_session, "JOINED")
        await call_repository.transition(call_session, "RECORDING")
        if listener_account is not None:
            await listener_account_repository.mark_busy(listener_account)
        self._audit(
            context,
            "live_listener.started",
            live_session.id,
            {"telegram_chat_id": live_session.telegram_chat_id},
        )
        await self.session.commit()

    async def stop_listening(
        self,
        context: BotContext,
        telegram_chat_id: int,
    ) -> LiveListenStop:
        live_session = await self._active_session(context.workspace_id, telegram_chat_id)
        if live_session is None:
            raise ListenerConfigurationError("Rhapsody is not listening to a call in this group.")

        if live_session.status in {"stop_requested", "stopping", "transcribing", "analyzing"}:
            completed = await self._wait_for_terminal_stop(live_session.id)
            return LiveListenStop(
                session_id=completed.id,
                report=completed.report_text or "Live meeting report was generated.",
            )

        live_session.status = "stop_requested"
        live_session.stop_requested_at = datetime.now(timezone.utc)
        self._audit(
            context,
            "live_listener.stop_requested",
            live_session.id,
            {"telegram_chat_id": telegram_chat_id},
        )
        await self.session.commit()

        if not self.inline_runtime:
            completed = await self._wait_for_terminal_stop(live_session.id)
            return LiveListenStop(
                session_id=completed.id,
                report=completed.report_text or "Live meeting report was generated.",
            )

        await self.process_stop_request(live_session.id)
        await self.session.refresh(live_session)
        if live_session.status == "failed":
            raise ListenerJoinError(live_session.error_message or "Live listener failed to stop.")
        return LiveListenStop(
            session_id=live_session.id,
            report=live_session.report_text or "Live meeting report was generated.",
        )

    async def process_stop_request(self, live_session_id: UUID) -> None:
        live_session = await self.session.get(LiveMeetingSession, live_session_id)
        if live_session is None or live_session.status not in {"stop_requested", "stopping"}:
            return
        context = await self._context_for_session(live_session)
        call_session = await self._call_session_for_live_session(live_session, context)
        call_repository = CallSessionRepository(self.session)
        listener_account_repository = ListenerAccountRepository(self.session)
        listener_account = await self._listener_account_for_call(call_session)
        live_session.status = "stopping"
        await call_repository.transition(call_session, "FINALIZING")
        await self.session.commit()

        try:
            live_session.status = "transcribing"
            await self.session.commit()
            result = await self.adapter.stop(live_session.id)
        except Exception as exc:
            message = _listener_error_message(exc)
            live_session.status = "failed"
            live_session.error_message = message
            await call_repository.transition(
                call_session,
                "FAILED",
                failure_code=exc.__class__.__name__,
                failure_message=message,
            )
            if listener_account is not None:
                await listener_account_repository.cooldown(listener_account, seconds=60)
            self._audit(
                context,
                "live_listener.stop_failed",
                live_session.id,
                {"error": message},
            )
            await self.session.commit()
            if isinstance(exc, ListenerError):
                raise
            raise ListenerJoinError(message) from exc

        live_session.transcript = result.transcript
        live_session.audio_object_ref = result.audio_object_ref or live_session.audio_object_ref
        await self._persist_captured_chunks(call_session, result)
        if listener_account is not None:
            await listener_account_repository.release(listener_account)
        live_session.stopped_at = datetime.now(timezone.utc)
        live_session.status = "analyzing"
        await self.session.commit()

        try:
            report = await TelegramProductService(
                self.session,
                ai_client=self.ai_client,
            ).ingest_meeting(context, result.transcript)
        except Exception as exc:
            message = _listener_error_message(exc)
            live_session.status = "failed"
            live_session.error_message = message
            self._audit(
                context,
                "live_listener.analysis_failed",
                live_session.id,
                {"error": message},
            )
            await self.session.commit()
            raise ListenerJoinError(message) from exc

        live_session.status = "completed"
        live_session.report_text = report
        await call_repository.transition(call_session, "COMPLETED")
        if listener_account is not None:
            await listener_account_repository.release(listener_account)
        self._audit(
            context,
            "live_listener.stopped",
            live_session.id,
            {"telegram_chat_id": live_session.telegram_chat_id},
        )
        await self.session.commit()

    async def live_status(self, context: BotContext, telegram_chat_id: int) -> LiveListenStatus:
        live_session = await self._active_session(context.workspace_id, telegram_chat_id)
        if live_session is None:
            return LiveListenStatus(
                active=False,
                message="Rhapsody is not listening in this group.",
            )
        display_status = t(
            f"live_calls.status.{live_session.status.upper()}",
            context.locale,
        )
        if not self.inline_runtime:
            return LiveListenStatus(
                active=live_session.status == "listening",
                message=f"Live listener status: {display_status} ({live_session.status}).",
            )
        runtime = await self._runtime_status(live_session.id)
        return LiveListenStatus(
            active=runtime.active,
            message=(
                f"Live listener status: {display_status} "
                f"({live_session.status}). {runtime.detail}"
            ),
        )

    async def call_setup(
        self,
        context: BotContext,
        telegram_chat_id: int,
    ) -> RecorderSetupStatus:
        try:
            validate_listener_configuration(self.settings)
        except ListenerConfigurationError as exc:
            return RecorderSetupStatus(ready=False, message=str(exc))

        active = await self._active_session(context.workspace_id, telegram_chat_id)
        if active is not None:
            return RecorderSetupStatus(
                ready=True,
                message=(
                    "Call recording is already connected for this group. "
                    "Start the Telegram call and use /listen when you want Rhapsody to join."
                ),
            )

        available = await ListenerAccountRepository(self.session).available()
        if not available:
            return RecorderSetupStatus(
                ready=False,
                message=(
                    "No Rhapsody Recorder account is available right now. "
                    "An operator needs to add a recorder session to the listener account pool."
                ),
            )

        recorder = available[0]
        return RecorderSetupStatus(
            ready=True,
            message=(
                "Call recording is ready for this group.\n\n"
                f"1. Add {_recorder_label(recorder)} to this Telegram group.\n"
                "2. Start the Telegram group call.\n"
                "3. Send /listen when the call is live.\n\n"
                "Ordinary users do not need a Telegram API ID, API hash, user session, "
                "or AI provider key."
            ),
        )

    async def recorder_status(
        self,
        context: BotContext,
        telegram_chat_id: int,
    ) -> RecorderSetupStatus:
        active = await self._active_session(context.workspace_id, telegram_chat_id)
        if active is not None:
            call_session = await CallSessionRepository(self.session).for_live_session(active.id)
            recorder = await self._listener_account_for_call(call_session) if call_session else None
            return RecorderSetupStatus(
                ready=True,
                message=(
                    f"Live listener status: {active.status}. "
                    f"Recorder: {_recorder_label(recorder) if recorder else 'reserved'}."
                ),
            )

        available = await ListenerAccountRepository(self.session).available()
        if available:
            names = ", ".join(_recorder_label(account) for account in available[:5])
            return RecorderSetupStatus(
                ready=True,
                message=f"Recorder pool is ready. Available recorders: {names}.",
            )
        return RecorderSetupStatus(
            ready=False,
            message="Recorder pool is empty or all recorder accounts are busy/cooling down.",
        )

    async def process_pending_once(self) -> None:
        pending_start = (
            await self.session.scalars(
                select(LiveMeetingSession)
                .where(LiveMeetingSession.status == "start_requested")
                .order_by(LiveMeetingSession.started_at.asc())
            )
        ).first()
        if pending_start is not None:
            try:
                await self.process_start_request(pending_start.id)
            except ListenerError:
                return

        pending_stop = (
            await self.session.scalars(
                select(LiveMeetingSession)
                .where(LiveMeetingSession.status == "stop_requested")
                .order_by(LiveMeetingSession.stop_requested_at.asc())
            )
        ).first()
        if pending_stop is not None:
            try:
                await self.process_stop_request(pending_stop.id)
            except ListenerError:
                return

        await self._refresh_recording_audio_state()

    async def _runtime_status(self, session_id: UUID) -> ListenerRuntimeStatus:
        try:
            return await self.adapter.status(session_id)
        except ListenerError as exc:
            return ListenerRuntimeStatus(active=False, detail=str(exc))

    async def _refresh_recording_audio_state(self) -> None:
        rows = (
            await self.session.scalars(
                select(LiveMeetingSession)
                .where(LiveMeetingSession.status == "listening")
                .order_by(LiveMeetingSession.started_at.asc())
            )
        ).all()
        repository = CallSessionRepository(self.session)
        now = datetime.now(timezone.utc)
        changed = False
        for live_session in rows:
            call_session = await repository.for_live_session(live_session.id)
            if call_session is None or call_session.status not in {
                "RECORDING",
                "CONNECTED_NO_AUDIO",
            }:
                continue
            runtime = await self._runtime_status(live_session.id)
            if runtime.frames_seen > 0:
                await repository.mark_audio_received(call_session)
                if call_session.status == "CONNECTED_NO_AUDIO":
                    await repository.transition(call_session, "RECONNECTING")
                    await repository.transition(call_session, "RECORDING")
                changed = True
                continue
            audio_deadline = (
                call_session.joined_at or live_session.started_at
            ) + timedelta(seconds=self.settings.live_no_audio_timeout_seconds)
            if now >= audio_deadline and call_session.status == "RECORDING":
                await repository.transition(
                    call_session,
                    "CONNECTED_NO_AUDIO",
                    failure_code="NO_AUDIO_FRAMES",
                    failure_message="Listener joined the call but no audio frames were received.",
                )
                changed = True
        if changed:
            await self.session.commit()

    async def _active_session(
        self,
        workspace_id: UUID,
        telegram_chat_id: int,
    ) -> LiveMeetingSession | None:
        return (
            await self.session.scalars(
                select(LiveMeetingSession)
                .where(
                    LiveMeetingSession.workspace_id == workspace_id,
                    LiveMeetingSession.telegram_chat_id == telegram_chat_id,
                    LiveMeetingSession.status.in_(ACTIVE_LIVE_STATUSES),
                )
                .order_by(LiveMeetingSession.started_at.desc())
            )
        ).first()

    async def _context_for_session(self, live_session: LiveMeetingSession) -> BotContext:
        workspace = await self.session.get(Workspace, live_session.workspace_id)
        if workspace is None:
            raise ListenerConfigurationError("Workspace for live session no longer exists.")
        return BotContext(
            organization_id=workspace.organization_id,
            workspace_id=live_session.workspace_id,
            user_id=live_session.started_by_user_id,
        )

    async def _call_session_for_live_session(
        self,
        live_session: LiveMeetingSession,
        context: BotContext,
    ) -> CallSession:
        repository = CallSessionRepository(self.session)
        call_session = await repository.for_live_session(live_session.id)
        if call_session is not None:
            return call_session
        return await repository.create_requested(
            organization_id=context.organization_id,
            workspace_id=context.workspace_id,
            telegram_chat_id=live_session.telegram_chat_id,
            requested_by_user_id=context.user_id,
            live_meeting_session_id=live_session.id,
        )

    async def _reserve_listener_account(
        self,
        call_session: CallSession,
    ) -> ListenerAccount | None:
        if call_session.listener_account_id is not None:
            return await self.session.get(ListenerAccount, call_session.listener_account_id)
        return await ListenerAccountRepository(self.session).reserve_for_call(call_session)

    async def _listener_account_for_call(
        self,
        call_session: CallSession,
    ) -> ListenerAccount | None:
        if call_session.listener_account_id is None:
            return None
        return await self.session.get(ListenerAccount, call_session.listener_account_id)

    async def _has_recorder_capacity(self) -> bool:
        if self.settings.telegram_user_session:
            return True
        return bool(await ListenerAccountRepository(self.session).available())

    def _recorder_session(self, listener_account: ListenerAccount | None) -> str | None:
        if listener_account is not None:
            return self._decrypt_recorder_session(listener_account.encrypted_session)
        return self.settings.telegram_user_session

    def _decrypt_recorder_session(self, encrypted_session: str) -> str:
        if self.settings.has_default_encryption_key:
            return encrypted_session
        try:
            return SecretCipher(self.settings.encryption_key).decrypt(encrypted_session)
        except Exception as exc:
            raise ListenerConfigurationError(
                "Recorder account session could not be decrypted."
            ) from exc

    async def _persist_captured_chunks(
        self,
        call_session: CallSession,
        result: ListenerStopResult,
    ) -> None:
        chunk_repository = CallAudioChunkRepository(self.session)
        captured_chunks = result.chunks
        if not captured_chunks and result.audio_object_ref:
            chunk = await chunk_repository.create_spooled(
                call_session=call_session,
                sequence_number=1,
                local_path=result.audio_object_ref,
                byte_size=0,
                duration_ms=0,
            )
            if result.transcript.strip():
                await chunk_repository.mark_transcribed(chunk, result.transcript.strip())
            return
        for captured_chunk in captured_chunks:
            chunk = await chunk_repository.create_spooled(
                call_session=call_session,
                sequence_number=captured_chunk.sequence_number,
                local_path=captured_chunk.local_path,
                byte_size=captured_chunk.byte_size,
                duration_ms=captured_chunk.duration_ms,
                content_type=captured_chunk.content_type,
            )
            if captured_chunk.transcript:
                await chunk_repository.mark_transcribed(chunk, captured_chunk.transcript)
            if captured_chunk.byte_size > 0:
                await CallSessionRepository(self.session).mark_audio_received(call_session)

    async def _wait_for_terminal_start(self, live_session_id: UUID) -> LiveMeetingSession:
        return await self._wait_for_status(
            live_session_id,
            success_statuses={"listening"},
            timeout_seconds=START_WAIT_SECONDS,
            timeout_message=(
                "Live listener service did not confirm call capture within 30 seconds. "
                "Check listener container logs."
            ),
        )

    async def _wait_for_terminal_stop(self, live_session_id: UUID) -> LiveMeetingSession:
        return await self._wait_for_status(
            live_session_id,
            success_statuses={"completed"},
            timeout_seconds=STOP_WAIT_SECONDS,
            timeout_message=(
                "Live listener service did not finish processing within 180 seconds. "
                "Check listener container logs."
            ),
        )

    async def _wait_for_status(
        self,
        live_session_id: UUID,
        success_statuses: set[str],
        timeout_seconds: int,
        timeout_message: str,
    ) -> LiveMeetingSession:
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while True:
            self.session.expire_all()
            live_session = await self.session.get(LiveMeetingSession, live_session_id)
            if live_session is None:
                raise ListenerJoinError("Live listener session disappeared.")
            if live_session.status in success_statuses:
                return live_session
            if live_session.status == "failed":
                raise ListenerJoinError(live_session.error_message or "Live listener failed.")
            if asyncio.get_running_loop().time() >= deadline:
                live_session.status = "failed"
                live_session.error_message = timeout_message
                await self.session.commit()
                raise ListenerJoinError(timeout_message)
            await asyncio.sleep(POLL_SECONDS)

    def _audit(
        self,
        context: BotContext,
        action: str,
        session_id: UUID,
        metadata: dict,
    ) -> None:
        self.session.add(
            AuditLog(
                organization_id=context.organization_id,
                workspace_id=context.workspace_id,
                actor_user_id=context.user_id,
                action=action,
                resource_type="live_meeting_session",
                resource_id=session_id,
                metadata_json=metadata,
            )
        )


def _listener_error_message(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        if status_code == 401:
            return "The selected AI provider rejected the configured API key."
        if status_code == 402:
            return "The selected AI provider requires billing or credits before this can run."
        if status_code == 429:
            return "The selected AI provider is rate-limited or out of quota."
        if status_code >= 500:
            return "The selected AI provider is temporarily unavailable."
    message = str(exc).strip()
    return message or "Live listener failed."


def _recorder_label(account: ListenerAccount | None) -> str:
    if account is None:
        return "Rhapsody Recorder"
    if account.username:
        return f"@{account.username.lstrip('@')}"
    return account.display_name
