from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID

from aiogram import Bot
from sqlalchemy import select

from app.bot.services import BotContext, TelegramProductService
from app.calls.repository import CallAudioChunkRepository, CallSessionRepository
from app.core.config import get_settings
from app.db.models import AuditLog, CallSession, LiveMeetingSession, TelegramChat, Workspace
from app.db.session import AsyncSessionFactory
from app.listener.service import _listener_error_message
from app.services.audio_storage import AudioStorageService
from app.services.product_ai import ProductAIClient
from app.services.scheduling import find_task_reminder_candidates
from app.services.stt import SpeechToTextService
from app.workers.celery_app import celery_app


@celery_app.task(name="meetings.process_recording")
def process_recording(meeting_id: str) -> dict[str, str]:
    return {"meeting_id": meeting_id, "status": "queued_for_stt"}


@celery_app.task(name="documents.index_document")
def index_document(document_id: str) -> dict[str, str]:
    return {"document_id": document_id, "status": "queued_for_embedding"}


@celery_app.task(name="tasks.dispatch_due_reminders")
def dispatch_due_reminders() -> dict[str, str]:
    return asyncio.run(dispatch_due_reminders_to_telegram())


@celery_app.task(name="retention.sweep_workspace")
def sweep_workspace_retention(workspace_id: str, older_than_iso: str) -> dict[str, str]:
    return {
        "workspace_id": workspace_id,
        "older_than": older_than_iso,
        "status": "queued_for_retention_sweep",
    }


@celery_app.task(name="calls.upload_pending_chunks")
def upload_pending_call_chunks(limit: int = 50) -> dict[str, str]:
    return asyncio.run(upload_pending_call_chunks_once(limit=limit))


@celery_app.task(name="calls.transcribe_pending_chunks")
def transcribe_pending_call_chunks(limit: int = 50) -> dict[str, str]:
    return asyncio.run(transcribe_pending_call_chunks_once(limit=limit))


@celery_app.task(name="calls.finalize_meeting")
def finalize_call_meeting(call_session_id: str) -> dict[str, str]:
    return asyncio.run(finalize_call_meeting_once(UUID(call_session_id)))


@celery_app.task(name="calls.recover_stale")
def recover_stale_call_sessions(audio_timeout_seconds: int = 15) -> dict[str, str]:
    return asyncio.run(recover_stale_call_sessions_once(audio_timeout_seconds))


async def upload_pending_call_chunks_once(limit: int = 50) -> dict[str, str]:
    uploaded = 0
    failed = 0
    storage = AudioStorageService()
    async with AsyncSessionFactory() as session:
        repository = CallAudioChunkRepository(session)
        for chunk in await repository.pending_upload(limit=limit):
            try:
                object_ref = storage.upload_chunk_file(
                    workspace_id=chunk.workspace_id,
                    call_session_id=chunk.call_session_id,
                    sequence_number=chunk.sequence_number,
                    local_path=chunk.local_path,
                    content_type=chunk.content_type,
                )
            except Exception as exc:
                await repository.mark_failed(
                    chunk,
                    status="UPLOAD_FAILED",
                    failure_code=exc.__class__.__name__,
                    failure_message=str(exc),
                )
                failed += 1
                continue
            await repository.mark_uploaded(chunk, object_ref)
            uploaded += 1
        await session.commit()
    return {"status": "ok", "uploaded": str(uploaded), "failed": str(failed)}


async def transcribe_pending_call_chunks_once(limit: int = 50) -> dict[str, str]:
    transcribed = 0
    failed = 0
    stt_service = SpeechToTextService()
    async with AsyncSessionFactory() as session:
        repository = CallAudioChunkRepository(session)
        for chunk in await repository.pending_transcription(limit=limit):
            if chunk.transcript:
                await repository.mark_transcribed(chunk, chunk.transcript)
                transcribed += 1
                continue
            try:
                content = await asyncio.to_thread(Path(chunk.local_path).read_bytes)
                transcript = await stt_service.transcribe(
                    content,
                    Path(chunk.local_path).name,
                    chunk.content_type,
                )
            except Exception as exc:
                await repository.mark_failed(
                    chunk,
                    status="TRANSCRIBE_FAILED",
                    failure_code=exc.__class__.__name__,
                    failure_message=str(exc),
                )
                failed += 1
                continue
            await repository.mark_transcribed(chunk, transcript)
            transcribed += 1
        await session.commit()
    return {"status": "ok", "transcribed": str(transcribed), "failed": str(failed)}


async def finalize_call_meeting_once(call_session_id: UUID) -> dict[str, str]:
    async with AsyncSessionFactory() as session:
        call_session = await session.get(CallSession, call_session_id)
        if call_session is None:
            return {"status": "missing_call_session"}
        if call_session.live_meeting_session_id is None:
            return {"status": "missing_live_meeting_session"}
        live_session = await session.get(LiveMeetingSession, call_session.live_meeting_session_id)
        if live_session is None:
            return {"status": "missing_live_meeting_session"}
        chunk_repository = CallAudioChunkRepository(session)
        transcript = "\n".join(await chunk_repository.ordered_transcripts(call_session.id)).strip()
        if not transcript:
            return {"status": "waiting_for_transcripts"}
        workspace = await session.get(Workspace, call_session.workspace_id)
        if workspace is None:
            return {"status": "missing_workspace"}
        context = BotContext(
            organization_id=call_session.organization_id,
            workspace_id=call_session.workspace_id,
            user_id=call_session.requested_by_user_id,
            telegram_chat_id=call_session.telegram_chat_id,
            chat_type="group",
        )
        live_session.transcript = transcript
        live_session.status = "analyzing"
        await session.commit()
        try:
            report = await TelegramProductService(
                session,
                ai_client=ProductAIClient(),
            ).ingest_meeting(context, transcript)
        except Exception as exc:
            live_session.status = "failed"
            live_session.error_message = _listener_error_message(exc)
            await CallSessionRepository(session).transition(
                call_session,
                "FAILED",
                failure_code=exc.__class__.__name__,
                failure_message=live_session.error_message,
            )
            await session.commit()
            return {"status": "failed", "reason": live_session.error_message}
        live_session.report_text = report
        live_session.status = "completed"
        if call_session.status != "FINALIZING":
            await CallSessionRepository(session).transition(call_session, "FINALIZING")
        await CallSessionRepository(session).transition(call_session, "COMPLETED")
        await session.commit()
    return {"status": "completed", "call_session_id": str(call_session_id)}


async def recover_stale_call_sessions_once(audio_timeout_seconds: int) -> dict[str, str]:
    recovered = 0
    failed = 0
    async with AsyncSessionFactory() as session:
        repository = CallSessionRepository(session)
        for call_session in await repository.stale_recording_sessions(
            audio_timeout_seconds=audio_timeout_seconds
        ):
            if call_session.status == "RECORDING":
                await repository.transition(
                    call_session,
                    "CONNECTED_NO_AUDIO",
                    failure_code="NO_AUDIO_FRAMES",
                    failure_message="Listener joined the call but no audio frames were received.",
                )
                recovered += 1
            elif call_session.status == "CONNECTED_NO_AUDIO":
                await repository.transition(call_session, "RECONNECTING")
                recovered += 1
            elif call_session.status == "RECONNECTING":
                await repository.transition(
                    call_session,
                    "FAILED",
                    failure_code="audio_timeout",
                    failure_message="No audio frames were received before reconnect timeout.",
                )
                failed += 1
        await session.commit()
    return {"status": "ok", "reconnecting": str(recovered), "failed": str(failed)}


async def dispatch_due_reminders_to_telegram() -> dict[str, str]:
    settings = get_settings()
    if not settings.telegram_bot_token:
        return {
            "status": "telegram_not_configured",
            "reason": "TELEGRAM_BOT_TOKEN is required to dispatch Telegram reminders.",
        }

    sent_count = 0
    async with AsyncSessionFactory() as session:
        candidates = await find_task_reminder_candidates(session)
        if not candidates:
            return {"status": "ok", "sent": "0"}
        bot = Bot(token=settings.telegram_bot_token)
        try:
            for candidate in candidates:
                chats = (
                    await session.scalars(
                        select(TelegramChat).where(
                            TelegramChat.workspace_id == candidate.workspace_id
                        )
                    )
                ).all()
                workspace = (
                    await session.scalars(
                        select(Workspace).where(Workspace.id == candidate.workspace_id)
                    )
                ).one()
                for chat in chats:
                    await bot.send_message(
                        chat.telegram_chat_id,
                        format_task_reminder(candidate.title, candidate.hours_until_due),
                    )
                    sent_count += 1
                session.add(
                    AuditLog(
                        organization_id=workspace.organization_id,
                        workspace_id=candidate.workspace_id,
                        action="task.reminder_dispatched",
                        resource_type="task",
                        resource_id=candidate.task_id,
                        metadata_json={
                            "telegram_chats": len(chats),
                            "hours_until_due": candidate.hours_until_due,
                        },
                    )
                )
            await session.commit()
        finally:
            await bot.session.close()
    return {"status": "ok", "sent": str(sent_count)}


def format_task_reminder(title: str, hours_until_due: float) -> str:
    return (
        "🔔 Task reminder\n"
        f"{title}\n"
        f"Due in about {hours_until_due:g} hours.\n\n"
        "Use /tasks to review work or /task_done to close it."
    )
