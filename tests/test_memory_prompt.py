from __future__ import annotations

import uuid

from app.db.models import MemoryChunk
from app.services.embeddings import EmbeddingService
from app.services.memory import (
    build_grounded_memory_prompt,
    lexical_overlap_score,
    rank_memory_chunks,
)


def test_memory_prompt_requires_grounding_and_citations() -> None:
    prompt = build_grounded_memory_prompt(
        "Why did we choose supplier X?", "[1] decision: Supplier X"
    )

    assert "Answer only from the TeamMind memory context" in prompt
    assert "Cite source numbers" in prompt
    assert "Supplier X" in prompt


def test_rank_memory_chunks_prefers_semantically_relevant_sources() -> None:
    workspace_id = uuid.uuid4()
    embedding_service = EmbeddingService(dimensions=64)
    supplier_chunk = MemoryChunk(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        source_type="decision",
        source_id=uuid.uuid4(),
        source_title="Supplier choice",
        content="We chose Supplier X because it met the compliance and delivery requirements.",
        embedding=embedding_service.embed_for_storage(
            "Supplier choice We chose Supplier X because it met compliance requirements."
        ),
    )
    unrelated_chunk = MemoryChunk(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        source_type="meeting",
        source_id=uuid.uuid4(),
        source_title="Office lunch",
        content="The team agreed to order pizza for Friday lunch.",
        embedding=embedding_service.embed_for_storage("Office lunch pizza Friday"),
    )

    ranked = rank_memory_chunks(
        "Why did we choose Supplier X?",
        [unrelated_chunk, supplier_chunk],
        top_k=1,
        embedding_service=embedding_service,
    )

    assert ranked == [supplier_chunk]


def test_rank_memory_chunks_falls_back_to_text_embedding_when_missing_stored_embedding() -> None:
    workspace_id = uuid.uuid4()
    embedding_service = EmbeddingService(dimensions=64)
    risk_chunk = MemoryChunk(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        source_type="message",
        source_id=uuid.uuid4(),
        source_title="Deployment risk",
        content="Release is blocked by database migration risk.",
        embedding=None,
    )
    task_chunk = MemoryChunk(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        source_type="task",
        source_id=uuid.uuid4(),
        source_title="Design review",
        content="Schedule a design review next week.",
        embedding=None,
    )

    ranked = rank_memory_chunks(
        "What is blocking release?",
        [task_chunk, risk_chunk],
        top_k=1,
        embedding_service=embedding_service,
    )

    assert ranked == [risk_chunk]


def test_lexical_overlap_uses_normalized_tokens() -> None:
    assert lexical_overlap_score("Supplier X?", "supplier x selected") == 1.0
