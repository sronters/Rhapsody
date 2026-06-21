from __future__ import annotations

import asyncio
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import boto3
from fastapi import APIRouter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DBSession, ServiceAuth
from app.calls.metrics import (
    rhapsody_active_calls,
    rhapsody_audio_chunks_total,
    rhapsody_available_listeners,
    rhapsody_call_reconnects_total,
    rhapsody_failed_transcription_chunks,
    rhapsody_last_audio_age_seconds,
    rhapsody_listener_heartbeat_age_seconds,
    rhapsody_oldest_pending_chunk_age_seconds,
    rhapsody_pending_upload_chunks,
    rhapsody_spool_size_bytes,
)
from app.calls.state_machine import ACTIVE_CALL_SESSION_STATUSES
from app.core.config import get_settings
from app.db.models import CallAudioChunk, CallSession, ListenerAccount
from app.listener.adapters import collect_listener_diagnostics, validate_listener_configuration

router = APIRouter()


@router.get("/ops-status")
async def call_ops_status(
    session: DBSession,
    _: ServiceAuth,
    audio_timeout_seconds: int = 15,
) -> dict[str, object]:
    stale_cutoff = datetime.now(timezone.utc) - timedelta(seconds=audio_timeout_seconds)
    active_calls = await _count(
        session,
        select(func.count())
        .select_from(CallSession)
        .where(CallSession.status.in_(ACTIVE_CALL_SESSION_STATUSES)),
    )
    stale_audio = await _count(
        session,
        select(func.count())
        .select_from(CallSession)
        .where(
            CallSession.status.in_({"RECORDING", "RECONNECTING"}),
            CallSession.last_audio_at.is_not(None),
            CallSession.last_audio_at < stale_cutoff,
        ),
    )
    chunk_statuses = dict(
        (
            await session.execute(
                select(CallAudioChunk.status, func.count())
                .group_by(CallAudioChunk.status)
                .order_by(CallAudioChunk.status.asc())
            )
        ).all()
    )
    listener_statuses = dict(
        (
            await session.execute(
                select(ListenerAccount.status, func.count())
                .group_by(ListenerAccount.status)
                .order_by(ListenerAccount.status.asc())
            )
        ).all()
    )
    oldest_audio_age = await _oldest_active_audio_age(session)
    listener_heartbeat_age = await _oldest_listener_heartbeat_age(session)
    reconnects_total = await _reconnects_total(session)
    total_chunks = await _count(session, select(func.count()).select_from(CallAudioChunk))
    pending_upload = int(chunk_statuses.get("SPOOLED", 0))
    failed_transcription = int(chunk_statuses.get("TRANSCRIBE_FAILED", 0))
    oldest_pending_age = await _oldest_pending_chunk_age(session)
    spool_size = await _spool_size_bytes()
    _update_call_metrics(
        active_calls=active_calls,
        available_listeners=int(listener_statuses.get("AVAILABLE", 0)),
        last_audio_age_seconds=oldest_audio_age,
        listener_heartbeat_age_seconds=listener_heartbeat_age,
        call_reconnects_total=reconnects_total,
        audio_chunks_total=total_chunks,
        pending_upload_chunks=pending_upload,
        failed_transcription_chunks=failed_transcription,
        oldest_pending_chunk_age_seconds=oldest_pending_age,
        spool_size_bytes=spool_size,
    )
    return {
        "active_calls": active_calls,
        "stale_audio_calls": stale_audio,
        "oldest_active_audio_age_seconds": oldest_audio_age,
        "oldest_listener_heartbeat_age_seconds": listener_heartbeat_age,
        "call_reconnects_total": reconnects_total,
        "audio_chunks": chunk_statuses,
        "audio_chunks_total": total_chunks,
        "pending_upload_chunks": pending_upload,
        "failed_transcription_chunks": failed_transcription,
        "oldest_pending_chunk_age_seconds": oldest_pending_age,
        "spool_size_bytes": spool_size,
        "listener_accounts": listener_statuses,
    }


@router.get("/ready")
async def call_readiness(session: DBSession, _: ServiceAuth) -> dict[str, object]:
    settings = get_settings()
    checks: dict[str, object] = {
        "listener_enabled": "ok" if settings.listener_enabled else "disabled",
    }
    if not settings.listener_enabled:
        return {"status": "disabled", "checks": checks}

    try:
        validate_listener_configuration(settings)
        checks["configuration"] = "ok"
    except Exception as exc:
        checks["configuration"] = str(exc)

    diagnostics = await _listener_diagnostics(settings)
    checks["mtproto"] = _diagnostic_status(diagnostics.listener_config_valid, diagnostics.error)
    checks["audio_engine"] = "ok" if diagnostics.live_runtime_available else "missing"
    checks["session_is_bot"] = diagnostics.session_is_bot
    checks["spool"] = await _spool_status(settings.listener_storage_dir)
    checks["ffmpeg"] = "ok" if shutil.which("ffmpeg") else "missing"
    checks["postgres"] = "ok"
    checks["redis"] = await _redis_status(settings.redis_url)
    checks["minio"] = await _minio_status()
    checks["stt"] = _stt_status(settings)
    checks["available_recorders"] = await _count(
        session,
        select(func.count())
        .select_from(ListenerAccount)
        .where(ListenerAccount.status == "AVAILABLE"),
    )
    return {"status": _readiness_status(checks), "checks": checks}


async def _count(session: AsyncSession, statement) -> int:
    return int(await session.scalar(statement) or 0)


async def _oldest_active_audio_age(session: AsyncSession) -> int:
    oldest_audio = await session.scalar(
        select(func.min(CallSession.last_audio_at)).where(
            CallSession.status.in_({"RECORDING", "CONNECTED_NO_AUDIO", "RECONNECTING"}),
            CallSession.last_audio_at.is_not(None),
        )
    )
    if oldest_audio is None:
        return 0
    return max(0, int((datetime.now(timezone.utc) - oldest_audio).total_seconds()))


async def _oldest_pending_chunk_age(session: AsyncSession) -> int:
    oldest_chunk = await session.scalar(
        select(func.min(CallAudioChunk.created_at)).where(
            CallAudioChunk.status.in_({"SPOOLED", "UPLOADED", "TRANSCRIBE_FAILED"})
        )
    )
    if oldest_chunk is None:
        return 0
    return max(0, int((datetime.now(timezone.utc) - oldest_chunk).total_seconds()))


async def _oldest_listener_heartbeat_age(session: AsyncSession) -> int:
    oldest_heartbeat = await session.scalar(
        select(func.min(ListenerAccount.last_heartbeat_at)).where(
            ListenerAccount.status.in_({"BUSY", "RESERVED", "CONNECTING"}),
            ListenerAccount.last_heartbeat_at.is_not(None),
        )
    )
    if oldest_heartbeat is None:
        return 0
    return max(0, int((datetime.now(timezone.utc) - oldest_heartbeat).total_seconds()))


async def _reconnects_total(session: AsyncSession) -> int:
    statement = select(func.coalesce(func.sum(CallSession.reconnect_count), 0))
    return int(await session.scalar(statement))


def _update_call_metrics(
    *,
    active_calls: int,
    available_listeners: int,
    last_audio_age_seconds: int,
    listener_heartbeat_age_seconds: int,
    call_reconnects_total: int,
    audio_chunks_total: int,
    pending_upload_chunks: int,
    failed_transcription_chunks: int,
    oldest_pending_chunk_age_seconds: int,
    spool_size_bytes: int,
) -> None:
    rhapsody_active_calls.set(active_calls)
    rhapsody_available_listeners.set(available_listeners)
    rhapsody_last_audio_age_seconds.set(last_audio_age_seconds)
    rhapsody_listener_heartbeat_age_seconds.set(listener_heartbeat_age_seconds)
    rhapsody_call_reconnects_total.set(call_reconnects_total)
    rhapsody_audio_chunks_total.set(audio_chunks_total)
    rhapsody_pending_upload_chunks.set(pending_upload_chunks)
    rhapsody_failed_transcription_chunks.set(failed_transcription_chunks)
    rhapsody_oldest_pending_chunk_age_seconds.set(oldest_pending_chunk_age_seconds)
    rhapsody_spool_size_bytes.set(spool_size_bytes)


async def _spool_size_bytes() -> int:
    path = Path(get_settings().listener_storage_dir)
    if not await asyncio.to_thread(path.exists):
        return 0

    def calculate() -> int:
        return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())

    return await asyncio.to_thread(calculate)


async def _listener_diagnostics(settings):
    try:
        return await asyncio.wait_for(collect_listener_diagnostics(settings), timeout=10)
    except Exception as exc:
        return type(
            "Diagnostics",
            (),
            {
                "listener_config_valid": False,
                "live_runtime_available": False,
                "session_is_bot": None,
                "error": str(exc),
            },
        )()


def _diagnostic_status(config_valid: bool, error: str | None) -> str:
    if not config_valid:
        return error or "not_ready"
    if error:
        return f"not_ready: {error}"
    return "ok"


async def _spool_status(storage_dir: str) -> dict[str, object]:
    path = Path(storage_dir)
    try:
        await asyncio.to_thread(path.mkdir, parents=True, exist_ok=True)
        probe = path / ".rhapsody-spool-probe"
        await asyncio.to_thread(probe.write_text, "ok", encoding="utf-8")
        await asyncio.to_thread(probe.unlink)
        usage = await asyncio.to_thread(shutil.disk_usage, path)
    except Exception as exc:
        return {"status": "not_ready", "error": str(exc)}
    return {
        "status": "ok" if usage.free > 0 else "not_ready",
        "path": str(path),
        "free_bytes": usage.free,
        "total_bytes": usage.total,
    }


async def _redis_status(redis_url: str) -> str:
    try:
        from redis.asyncio import Redis

        redis = Redis.from_url(redis_url)
        try:
            await redis.ping()
        finally:
            await redis.aclose()
    except Exception as exc:
        return f"not_ready: {exc}"
    return "ok"


async def _minio_status() -> str:
    settings = get_settings()
    try:
        client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
        )
        await asyncio.to_thread(client.head_bucket, Bucket=settings.s3_bucket)
    except Exception as exc:
        return f"degraded: {exc}"
    return "ok"


def _stt_status(settings) -> str:
    if settings.stt_mode is None:
        return "not_ready: STT_MODE is required"
    if settings.stt_mode == "openai" and not settings.openai_api_key:
        return "not_ready: OPENAI_API_KEY is required for OpenAI STT"
    return "ok"


def _readiness_status(checks: dict[str, object]) -> str:
    hard_checks = {"configuration", "mtproto", "audio_engine", "spool", "postgres", "redis", "stt"}
    for name in hard_checks:
        value = checks.get(name)
        status = value.get("status") if isinstance(value, dict) else value
        if isinstance(status, str) and (
            status.startswith("not_ready") or status in {"missing", "disabled"}
        ):
            return "not_ready"
    available_recorders = int(checks.get("available_recorders") or 0)
    if available_recorders < 1:
        return "not_ready"
    if any(str(value).startswith("degraded") for value in checks.values()):
        return "degraded"
    return "ready"
