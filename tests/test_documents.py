from __future__ import annotations

from app.services.documents import chunk_text


def test_chunk_text_respects_overlap() -> None:
    text = "a" * 100 + "\n\n" + "b" * 100
    chunks = chunk_text(text, chunk_size=120, overlap=20)

    assert len(chunks) == 2
    assert chunks[0].endswith("b" * 18)
    assert chunks[1].startswith("b" * 20)


def test_chunk_text_drops_empty_lines() -> None:
    assert chunk_text("\n\n  \n") == []
