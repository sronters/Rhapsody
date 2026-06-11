from __future__ import annotations

import asyncio
import subprocess
import tempfile
from importlib import import_module
from pathlib import Path
from typing import Any

import httpx

from app.core.config import Settings, get_settings

SUPPORTED_AUDIO_SUFFIXES = {
    ".oga",
    ".ogg",
    ".opus",
    ".mp3",
    ".wav",
    ".m4a",
    ".mp4",
    ".mpeg",
    ".mpga",
    ".webm",
    ".mov",
}
SUPPORTED_AUDIO_TYPES = ("audio/", "video/")
LOCAL_MODEL_CACHE: dict[tuple[str, str, str], Any] = {}


class STTConfigurationError(RuntimeError):
    pass


class STTResponseError(RuntimeError):
    pass


class SpeechToTextService:
    def __init__(
        self,
        settings: Settings | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.http_client = http_client

    async def transcribe(self, content: bytes, filename: str, content_type: str | None) -> str:
        if not content:
            raise STTResponseError("Audio transcription failed because the uploaded file is empty.")
        mode = self.settings.stt_mode
        if mode is None:
            raise STTConfigurationError(
                "Audio transcription is not configured. Set STT_MODE and send the recording again, "
                "or send transcript text instead."
            )
        if mode == "openai":
            return await self._transcribe_openai(content, filename, content_type)
        if mode == "local_whisper":
            return await asyncio.to_thread(
                self._transcribe_local_whisper,
                content,
                filename,
                content_type,
            )
        raise STTConfigurationError(f"Unsupported STT_MODE: {mode}")

    async def _transcribe_openai(
        self,
        content: bytes,
        filename: str,
        content_type: str | None,
    ) -> str:
        if not self.settings.openai_api_key:
            raise STTConfigurationError("OPENAI_API_KEY is required when STT_MODE=openai.")
        async with self._client() as client:
            response = await client.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {self.settings.openai_api_key}"},
                data={"model": "whisper-1"},
                files={
                    "file": (
                        filename,
                        content,
                        content_type or "application/octet-stream",
                    )
                },
            )
        response.raise_for_status()
        text = response.json().get("text", "").strip()
        if not text:
            raise STTResponseError("Audio transcription returned no readable text.")
        return text

    def _transcribe_local_whisper(
        self,
        content: bytes,
        filename: str,
        content_type: str | None,
    ) -> str:
        suffix = self._validated_suffix(filename, content_type)
        try:
            faster_whisper = import_module("faster_whisper")
        except ImportError as exc:
            raise STTConfigurationError(
                "Local faster-whisper is not installed. Install the local STT dependencies or "
                "use STT_MODE=openai."
            ) from exc

        with tempfile.TemporaryDirectory(prefix="teammind-stt-") as temp_dir:
            input_path = Path(temp_dir) / f"input{suffix}"
            output_path = Path(temp_dir) / "normalized.wav"
            input_path.write_bytes(content)
            self._normalize_audio(input_path, output_path)
            model = self._local_model(faster_whisper)
            segments, _info = model.transcribe(
                str(output_path),
                language=self.settings.local_whisper_language or None,
            )
            text = " ".join(segment.text.strip() for segment in segments if segment.text.strip())
        if not text:
            raise STTResponseError("Audio transcription returned no readable text.")
        return text

    def _validated_suffix(self, filename: str, content_type: str | None) -> str:
        suffix = Path(filename).suffix.lower()
        normalized_type = (content_type or "").split(";", maxsplit=1)[0].lower()
        if suffix in SUPPORTED_AUDIO_SUFFIXES:
            return suffix
        if any(normalized_type.startswith(prefix) for prefix in SUPPORTED_AUDIO_TYPES):
            return suffix or ".audio"
        raise STTResponseError(
            "Unsupported audio format. Please send .oga, .ogg, .mp3, .wav, .m4a, .mp4, or .webm."
        )

    def _normalize_audio(self, input_path: Path, output_path: Path) -> None:
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(input_path),
            "-ac",
            "1",
            "-ar",
            "16000",
            str(output_path),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)  # noqa: S603
        except FileNotFoundError as exc:
            raise STTConfigurationError(
                "ffmpeg is required for local transcription but is not installed."
            ) from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "").strip()
            message = "Audio conversion failed. Please send a supported audio or video file."
            if detail:
                message = f"{message} ffmpeg reported: {detail[:240]}"
            raise STTResponseError(message) from exc
        if not output_path.exists() or output_path.stat().st_size == 0:
            raise STTResponseError("Audio conversion produced no readable audio.")

    def _local_model(self, faster_whisper: Any) -> Any:
        cache_key = (
            self.settings.local_whisper_model,
            self.settings.local_whisper_device,
            self.settings.local_whisper_compute_type,
        )
        model = LOCAL_MODEL_CACHE.get(cache_key)
        if model is None:
            model = faster_whisper.WhisperModel(
                self.settings.local_whisper_model,
                device=self.settings.local_whisper_device,
                compute_type=self.settings.local_whisper_compute_type,
            )
            LOCAL_MODEL_CACHE[cache_key] = model
        return model

    def _client(self):
        if self.http_client is not None:
            return _ExternalClientContext(self.http_client)
        return httpx.AsyncClient(timeout=120)


class _ExternalClientContext:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def __aenter__(self) -> httpx.AsyncClient:
        return self.client

    async def __aexit__(self, *args: object) -> None:
        return None
