from __future__ import annotations

import types

import pytest

import app.services.stt as stt_module
from app.core.config import Settings
from app.services.stt import (
    LOCAL_MODEL_CACHE,
    SpeechToTextService,
    STTConfigurationError,
    STTResponseError,
)
from app.services.vision import ImageUnderstandingService, VisionConfigurationError


@pytest.mark.asyncio
async def test_stt_requires_configured_provider() -> None:
    service = SpeechToTextService(settings=Settings(_env_file=None, stt_mode=None))

    with pytest.raises(STTConfigurationError, match="Audio transcription is not configured"):
        await service.transcribe(b"audio", "meeting.ogg", "audio/ogg")


@pytest.mark.asyncio
async def test_openai_stt_requires_openai_key() -> None:
    service = SpeechToTextService(
        settings=Settings(_env_file=None, stt_mode="openai", openai_api_key=None)
    )

    with pytest.raises(STTConfigurationError, match="OPENAI_API_KEY"):
        await service.transcribe(b"audio", "meeting.ogg", "audio/ogg")


@pytest.mark.asyncio
async def test_openai_stt_success_path_uses_configured_provider() -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, str]:
            return {"text": "OpenAI transcript"}

    class FakeClient:
        async def post(self, url: str, **kwargs):
            assert url == "https://api.openai.com/v1/audio/transcriptions"
            assert kwargs["data"] == {"model": "whisper-1"}
            assert kwargs["files"]["file"][0] == "meeting.ogg"
            return FakeResponse()

    service = SpeechToTextService(
        settings=Settings(_env_file=None, stt_mode="openai", openai_api_key="sk-test"),
        http_client=FakeClient(),
    )

    assert await service.transcribe(b"audio", "meeting.ogg", "audio/ogg") == "OpenAI transcript"


@pytest.mark.asyncio
async def test_local_whisper_transcribes_telegram_ogg_with_russian_language(monkeypatch) -> None:
    calls: dict[str, object] = {}

    class FakeSegment:
        text = " Привет команда "

    class FakeWhisperModel:
        def __init__(self, model: str, device: str, compute_type: str) -> None:
            calls["model"] = model
            calls["device"] = device
            calls["compute_type"] = compute_type

        def transcribe(self, path: str, language: str | None = None):
            calls["path"] = path
            calls["language"] = language
            return [FakeSegment()], object()

    monkeypatch.setattr(
        stt_module,
        "import_module",
        lambda name: types.SimpleNamespace(WhisperModel=FakeWhisperModel),
    )
    monkeypatch.setattr(
        SpeechToTextService,
        "_normalize_audio",
        lambda _self, _input_path, output_path: output_path.write_bytes(b"wav"),
    )
    LOCAL_MODEL_CACHE.clear()
    service = SpeechToTextService(
        settings=Settings(
            _env_file=None,
            stt_mode="local_whisper",
            local_whisper_model="small",
            local_whisper_device="cpu",
            local_whisper_compute_type="int8",
            local_whisper_language="ru",
        )
    )

    text = await service.transcribe(b"audio", "voice.oga", "audio/ogg")

    assert text == "Привет команда"
    assert calls["model"] == "small"
    assert calls["device"] == "cpu"
    assert calls["compute_type"] == "int8"
    assert calls["language"] == "ru"


@pytest.mark.asyncio
async def test_local_whisper_allows_language_auto_detection(monkeypatch) -> None:
    calls: dict[str, object] = {}

    class FakeSegment:
        text = "Mixed speech"

    class FakeWhisperModel:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def transcribe(self, path: str, language: str | None = None):
            calls["language"] = language
            return [FakeSegment()], object()

    monkeypatch.setattr(
        stt_module,
        "import_module",
        lambda name: types.SimpleNamespace(WhisperModel=FakeWhisperModel),
    )
    monkeypatch.setattr(
        SpeechToTextService,
        "_normalize_audio",
        lambda _self, _input_path, output_path: output_path.write_bytes(b"wav"),
    )
    LOCAL_MODEL_CACHE.clear()
    service = SpeechToTextService(
        settings=Settings(
            _env_file=None,
            stt_mode="local_whisper",
            local_whisper_language="",
        )
    )

    assert await service.transcribe(b"audio", "meeting.webm", "video/webm") == "Mixed speech"
    assert calls["language"] is None


@pytest.mark.asyncio
async def test_local_whisper_missing_dependency_returns_clean_error(monkeypatch) -> None:
    def raise_import_error(name: str):
        raise ImportError(name)

    monkeypatch.setattr(stt_module, "import_module", raise_import_error)
    service = SpeechToTextService(
        settings=Settings(_env_file=None, stt_mode="local_whisper")
    )

    with pytest.raises(STTConfigurationError, match="faster-whisper"):
        await service.transcribe(b"audio", "voice.ogg", "audio/ogg")


@pytest.mark.asyncio
async def test_local_whisper_rejects_unsupported_file_format() -> None:
    service = SpeechToTextService(
        settings=Settings(_env_file=None, stt_mode="local_whisper")
    )

    with pytest.raises(STTResponseError, match="Unsupported audio format"):
        await service.transcribe(b"audio", "archive.zip", "application/zip")


@pytest.mark.asyncio
async def test_local_whisper_ffmpeg_failure_returns_clean_error(monkeypatch) -> None:
    class FakeWhisperModel:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

    def fail_normalize(_self, _input_path, _output_path) -> None:
        raise STTResponseError("Audio conversion failed. Please send a supported audio file.")

    monkeypatch.setattr(
        stt_module,
        "import_module",
        lambda name: types.SimpleNamespace(WhisperModel=FakeWhisperModel),
    )
    monkeypatch.setattr(SpeechToTextService, "_normalize_audio", fail_normalize)
    service = SpeechToTextService(
        settings=Settings(_env_file=None, stt_mode="local_whisper")
    )

    with pytest.raises(STTResponseError, match="Audio conversion failed"):
        await service.transcribe(b"audio", "voice.ogg", "audio/ogg")


@pytest.mark.asyncio
async def test_vision_requires_configured_provider() -> None:
    service = ImageUnderstandingService(settings=Settings(_env_file=None, vision_mode=None))

    with pytest.raises(VisionConfigurationError, match="Image understanding is not configured"):
        await service.describe_image(b"image", "image/png")


@pytest.mark.asyncio
async def test_openai_vision_requires_openai_key() -> None:
    service = ImageUnderstandingService(
        settings=Settings(_env_file=None, vision_mode="openai", openai_api_key=None)
    )

    with pytest.raises(VisionConfigurationError, match="OPENAI_API_KEY"):
        await service.describe_image(b"image", "image/png")
