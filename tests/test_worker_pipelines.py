from __future__ import annotations

import uuid

from app.services.worker_pipelines import (
    deterministic_meeting_extraction,
    deterministic_transcribe_audio_reference,
    deterministic_weekly_summary,
    plan_document_indexing,
    plan_telegram_file_transfer,
)


def test_plan_telegram_file_transfer_builds_private_storage_key() -> None:
    workspace_id = uuid.uuid4()

    plan = plan_telegram_file_transfer("token", "voice/file.ogg", workspace_id, "voice")

    assert plan.download_url == "https://api.telegram.org/file/bottoken/voice/file.ogg"
    assert plan.storage_key == f"workspaces/{workspace_id}/telegram/voice/file.ogg"


def test_plan_document_indexing_extracts_text_and_embedding_hint() -> None:
    plan = plan_document_indexing(b"hello document", "note.txt", "text/plain")

    assert plan.extracted_text == "hello document"
    assert plan.embedding_dimensions == 256
    assert plan.chunk_count_hint == 1


def test_deterministic_worker_placeholders() -> None:
    assert "audio.wav" in deterministic_transcribe_audio_reference("audio.wav")
    assert "Weekly summary" in deterministic_weekly_summary("Ops", ["Shipped release"])
    assert deterministic_meeting_extraction("We decided to launch. Risk is capacity.")["decisions"]