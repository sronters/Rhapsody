from __future__ import annotations

import asyncio
import logging
import platform
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from app.core.config import Settings
from app.services.stt import SpeechToTextService

logger = logging.getLogger(__name__)


class ListenerError(RuntimeError):
    pass


class ListenerConfigurationError(ListenerError):
    pass


class ListenerJoinError(ListenerError):
    pass


class NoActiveGroupCallError(ListenerJoinError):
    pass


@dataclass(frozen=True)
class ListenerStartResult:
    audio_object_ref: str | None = None


@dataclass(frozen=True)
class ListenerStopResult:
    transcript: str
    audio_object_ref: str | None = None


@dataclass(frozen=True)
class ListenerRuntimeStatus:
    active: bool
    detail: str


class MeetingListenerAdapter(Protocol):
    async def start(
        self,
        session_id: UUID,
        telegram_chat_id: int,
        workspace_id: UUID,
    ) -> ListenerStartResult:
        ...

    async def stop(self, session_id: UUID) -> ListenerStopResult:
        ...

    async def status(self, session_id: UUID) -> ListenerRuntimeStatus:
        ...


@dataclass
class LiveRuntimeDiagnostics:
    python_version: str
    os: str
    architecture: str
    pyrogram_version: str | None
    telethon_version: str | None
    py_tgcalls_version: str | None
    ntgcalls_version: str | None
    pytgcalls_importable: bool
    ntgcalls_importable: bool
    live_runtime_available: bool
    listener_config_valid: bool
    session_is_bot: bool | None
    error: str | None = None

    def lines(self) -> list[str]:
        return [
            f"Python: {self.python_version}",
            f"OS: {self.os}",
            f"Architecture: {self.architecture}",
            f"pyrogram: {self.pyrogram_version or 'not installed'}",
            f"telethon: {self.telethon_version or 'not installed'}",
            f"py-tgcalls: {self.py_tgcalls_version or 'not installed'}",
            f"ntgcalls: {self.ntgcalls_version or 'not installed'}",
            f"pytgcalls importable: {self.pytgcalls_importable}",
            f"ntgcalls importable: {self.ntgcalls_importable}",
            f"live runtime available: {self.live_runtime_available}",
            f"listener config valid: {self.listener_config_valid}",
            f"session is bot: {self.session_is_bot}",
            f"error: {self.error or 'none'}",
        ]


@dataclass
class _ActiveCall:
    session_id: UUID
    telegram_chat_id: int
    call_client: Any
    telegram_client: Any
    audio_path: Path
    sample_rate: int
    channels: int
    chunk_seconds: int
    stt_service: SpeechToTextService
    frames: bytearray = field(default_factory=bytearray)
    transcript_parts: list[str] = field(default_factory=list)
    transcribe_tasks: set[asyncio.Task] = field(default_factory=set)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    stopped: bool = False
    frames_seen: int = 0

    @property
    def chunk_bytes(self) -> int:
        return self.sample_rate * self.channels * 2 * self.chunk_seconds

    def append_frame(self, frame: bytes) -> bytes | None:
        self.frames_seen += 1
        self.frames.extend(frame)
        with self.audio_path.open("ab") as audio_file:
            audio_file.write(frame)
        if len(self.frames) < self.chunk_bytes:
            return None
        chunk = bytes(self.frames)
        self.frames.clear()
        return chunk

    def drain_frames(self) -> bytes | None:
        if not self.frames:
            return None
        chunk = bytes(self.frames)
        self.frames.clear()
        return chunk


class MTProtoMeetingListenerAdapter:
    _active_calls: dict[UUID, _ActiveCall] = {}

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def start(
        self,
        session_id: UUID,
        telegram_chat_id: int,
        workspace_id: UUID,
    ) -> ListenerStartResult:
        self._ensure_runtime_available()
        if session_id in self._active_calls:
            raise ListenerJoinError("A listener runtime is already attached to this session.")

        from pytgcalls import PyTgCalls
        from pytgcalls import filters as call_filters
        from pytgcalls.exceptions import NoActiveGroupCall as PyTgNoActiveGroupCall
        from pytgcalls.types import AudioQuality, Device, Direction, RecordStream, StreamFrames
        from telethon import TelegramClient
        from telethon.sessions import StringSession

        storage_dir = Path(self.settings.listener_storage_dir)
        await asyncio.to_thread(storage_dir.mkdir, parents=True, exist_ok=True)
        audio_path = storage_dir / f"{session_id}.pcm"
        await asyncio.to_thread(audio_path.write_bytes, b"")

        telegram_client = TelegramClient(
            StringSession(self.settings.telegram_user_session),
            int(self.settings.telegram_api_id or 0),
            self.settings.telegram_api_hash or "",
        )
        call_client = PyTgCalls(telegram_client)
        active_call = _ActiveCall(
            session_id=session_id,
            telegram_chat_id=telegram_chat_id,
            call_client=call_client,
            telegram_client=telegram_client,
            audio_path=audio_path,
            sample_rate=AudioQuality.HIGH.value[0],
            channels=AudioQuality.HIGH.value[1],
            chunk_seconds=self.settings.live_transcription_chunk_seconds,
            stt_service=SpeechToTextService(self.settings),
        )

        @call_client.on_update(
            call_filters.stream_frame(
                Direction.INCOMING,
                Device.MICROPHONE,
            )
        )
        async def audio_data(_: PyTgCalls, update: StreamFrames) -> None:
            for frame in update.frames:
                chunk = active_call.append_frame(frame.frame)
                if chunk is not None:
                    task = asyncio.create_task(self._transcribe_chunk(active_call, chunk))
                    active_call.transcribe_tasks.add(task)
                    task.add_done_callback(active_call.transcribe_tasks.discard)

        try:
            await call_client.start()
            await call_client.record(
                telegram_chat_id,
                RecordStream(
                    audio=True,
                    audio_parameters=AudioQuality.HIGH,
                ),
            )
        except PyTgNoActiveGroupCall as exc:
            await self._close_runtime(call_client, telegram_client, telegram_chat_id)
            raise NoActiveGroupCallError(
                "No active Telegram group call exists in this chat."
            ) from exc
        except Exception as exc:
            await self._close_runtime(call_client, telegram_client, telegram_chat_id)
            raise ListenerJoinError(
                f"Could not join or capture the Telegram group call: {exc}"
            ) from exc

        self._active_calls[session_id] = active_call
        return ListenerStartResult(audio_object_ref=str(audio_path))

    async def stop(self, session_id: UUID) -> ListenerStopResult:
        self._ensure_runtime_available()
        active_call = self._active_calls.get(session_id)
        if active_call is None:
            raise ListenerJoinError("No active MTProto listener session is running for this call.")
        active_call.stopped = True

        final_chunk = active_call.drain_frames()
        if final_chunk is not None:
            await self._transcribe_chunk(active_call, final_chunk)
        if active_call.transcribe_tasks:
            await asyncio.gather(*active_call.transcribe_tasks)

        try:
            await active_call.call_client.leave_call(active_call.telegram_chat_id)
        except Exception as exc:
            logger.info("Ignoring live listener leave_call cleanup error: %s", exc)
        await self._close_runtime(
            active_call.call_client,
            active_call.telegram_client,
            active_call.telegram_chat_id,
        )
        self._active_calls.pop(session_id, None)

        transcript = "\n".join(
            part for part in active_call.transcript_parts if part.strip()
        ).strip()
        if not active_call.frames_seen:
            raise ListenerJoinError("The listener joined but did not capture any audio frames.")
        if not transcript:
            raise ListenerJoinError(
                "Audio was captured, but speech-to-text produced no transcript."
            )
        return ListenerStopResult(
            transcript=transcript,
            audio_object_ref=str(active_call.audio_path),
        )

    async def status(self, session_id: UUID) -> ListenerRuntimeStatus:
        active_call = self._active_calls.get(session_id)
        if active_call is None:
            return ListenerRuntimeStatus(active=False, detail="No MTProto listener is connected.")
        return ListenerRuntimeStatus(
            active=True,
            detail=(
                "Connected to Telegram group call. "
                f"Captured frames: {active_call.frames_seen}. "
                f"Transcript chunks: {len(active_call.transcript_parts)}."
            ),
        )

    def _ensure_runtime_available(self) -> None:
        try:
            import ntgcalls  # noqa: F401
            import pytgcalls  # noqa: F401
            import telethon  # noqa: F401
        except ImportError as exc:
            raise ListenerConfigurationError(
                "Live Telegram call listening requires MTProto runtime dependencies "
                "(py-tgcalls, NTgCalls, Telethon) plus a Telegram user session."
            ) from exc

    async def _transcribe_chunk(self, active_call: _ActiveCall, chunk: bytes) -> None:
        wav_content = pcm_to_wav(chunk, active_call.sample_rate, active_call.channels)
        chunk_name = f"{active_call.session_id}-{len(active_call.transcript_parts) + 1}.wav"
        text = await active_call.stt_service.transcribe(wav_content, chunk_name, "audio/wav")
        if text.strip():
            active_call.transcript_parts.append(text.strip())

    async def _close_runtime(self, call_client: Any, telegram_client: Any, chat_id: int) -> None:
        try:
            if hasattr(call_client, "leave_call"):
                await call_client.leave_call(chat_id)
        except Exception as exc:
            logger.info("Ignoring live listener call cleanup error: %s", exc)
        try:
            if getattr(telegram_client, "is_connected", False):
                await telegram_client.disconnect()
        except Exception as exc:
            logger.info("Ignoring live listener MTProto cleanup error: %s", exc)


def pcm_to_wav(pcm_data: bytes, sample_rate: int, channels: int) -> bytes:
    import struct

    byte_rate = sample_rate * channels * 2
    block_align = channels * 2
    data_size = len(pcm_data)
    chunk_size = 36 + data_size
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        chunk_size,
        b"WAVE",
        b"fmt ",
        16,
        1,
        channels,
        sample_rate,
        byte_rate,
        block_align,
        16,
        b"data",
        data_size,
    )
    return header + pcm_data


def package_version(distribution: str) -> str | None:
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return None


async def collect_listener_diagnostics(settings: Settings) -> LiveRuntimeDiagnostics:
    error: str | None = None
    config_valid = True
    session_is_bot: bool | None = None
    try:
        validate_listener_configuration(settings)
    except ListenerConfigurationError as exc:
        config_valid = False
        error = str(exc)

    pytgcalls_importable = _module_importable("pytgcalls")
    ntgcalls_importable = _module_importable("ntgcalls")
    live_runtime_available = pytgcalls_importable and ntgcalls_importable and _module_importable(
        "telethon"
    )

    if config_valid and settings.telegram_user_session:
        try:
            from telethon import TelegramClient
            from telethon.sessions import StringSession

            client = TelegramClient(
                StringSession(settings.telegram_user_session),
                int(settings.telegram_api_id or 0),
                settings.telegram_api_hash or "",
            )
            await client.connect()
            try:
                user = await client.get_me()
                session_is_bot = bool(getattr(user, "bot", False))
            finally:
                await client.disconnect()
        except Exception as exc:
            error = f"{error + '; ' if error else ''}session check failed: {exc}"

    return LiveRuntimeDiagnostics(
        python_version=sys.version.split()[0],
        os=f"{platform.system()} {platform.release()}",
        architecture=platform.machine(),
        pyrogram_version=package_version("Pyrogram"),
        telethon_version=package_version("Telethon"),
        py_tgcalls_version=package_version("py-tgcalls"),
        ntgcalls_version=package_version("ntgcalls"),
        pytgcalls_importable=pytgcalls_importable,
        ntgcalls_importable=ntgcalls_importable,
        live_runtime_available=live_runtime_available,
        listener_config_valid=config_valid,
        session_is_bot=session_is_bot,
        error=error,
    )


def _module_importable(module: str) -> bool:
    try:
        __import__(module)
    except ImportError:
        return False
    return True


def validate_listener_configuration(settings: Settings) -> None:
    missing: list[str] = []
    if not settings.listener_enabled:
        missing.append("LISTENER_ENABLED=true")
    if settings.telegram_api_id is None:
        missing.append("TELEGRAM_API_ID")
    if not settings.telegram_api_hash:
        missing.append("TELEGRAM_API_HASH")
    if not settings.telegram_user_session:
        missing.append("TELEGRAM_USER_SESSION")
    if settings.stt_mode is None:
        missing.append("STT_MODE")
    if settings.stt_mode == "openai" and not settings.openai_api_key:
        missing.append("OPENAI_API_KEY")
    if missing:
        raise ListenerConfigurationError(
            "Live call listening is not configured. Missing: " + ", ".join(missing) + "."
        )
