from __future__ import annotations

import uuid

import pytest

from app.services.files import (
    build_storage_key,
    ensure_storage_key_belongs_to_workspace,
    sanitize_filename,
)


def test_sanitize_filename_removes_paths_and_unsafe_characters() -> None:
    assert sanitize_filename("../meeting notes ?.mp3") == "meeting-notes-.mp3"
    assert sanitize_filename("   ") == "upload.bin"


def test_build_storage_key_scopes_to_workspace() -> None:
    workspace_id = uuid.uuid4()
    key = build_storage_key(workspace_id, "document", "Roadmap.pdf")

    assert key.startswith(f"workspaces/{workspace_id}/document/")
    assert key.endswith("-Roadmap.pdf")


def test_rejects_cross_workspace_storage_key() -> None:
    workspace_id = uuid.uuid4()
    other_workspace_id = uuid.uuid4()
    storage_key = build_storage_key(other_workspace_id, "document", "Roadmap.pdf")

    with pytest.raises(ValueError, match="Storage key does not belong"):
        ensure_storage_key_belongs_to_workspace(workspace_id, storage_key)
