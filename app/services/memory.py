from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AIRequest, MemoryChunk
from app.schemas.memory import MemoryAnswer, MemoryQuestion, MemorySource
from app.services.ai import AIRouter, LLMRequest
from app.services.embeddings import EmbeddingService, tokenize
from app.services.redaction import redact_text


class MemoryService:
    def __init__(
        self,
        session: AsyncSession,
        ai_router: AIRouter | None = None,
        embedding_service: EmbeddingService | None = None,
    ) -> None:
        self.session = session
        self.ai_router = ai_router or AIRouter(session=session)
        self.embedding_service = embedding_service or EmbeddingService()

    async def answer_question(self, question: MemoryQuestion) -> MemoryAnswer:
        candidate_chunks = list(
            (
                await self.session.scalars(
                    select(MemoryChunk)
                    .where(MemoryChunk.workspace_id == question.workspace_id)
                    .order_by(MemoryChunk.created_at.desc())
                    .limit(max(question.top_k * 8, 40))
                )
            ).all()
        )
        chunks = rank_memory_chunks(
            question.question,
            candidate_chunks,
            top_k=question.top_k,
            embedding_service=self.embedding_service,
        )
        context = "\n\n".join(
            f"[{index + 1}] {chunk.source_type}: {chunk.source_title}\n{chunk.content[:1200]}"
            for index, chunk in enumerate(chunks)
        )
        prompt = build_grounded_memory_prompt(question.question, redact_text(context))
        llm_response = await self.ai_router.generate(
            LLMRequest(workspace_id=str(question.workspace_id), purpose="memory_qa", prompt=prompt)
        )
        self.session.add(
            AIRequest(
                workspace_id=question.workspace_id,
                provider=llm_response.provider,
                model=llm_response.model,
                purpose="memory_qa",
                prompt_hash=llm_response.prompt_hash,
                input_tokens=llm_response.input_tokens,
                output_tokens=llm_response.output_tokens,
                latency_ms=llm_response.latency_ms,
            )
        )
        await self.session.commit()
        return MemoryAnswer(
            answer=(
                llm_response.text
                if chunks
                else "I do not have enough sourced context to answer."
            ),
            sources=[
                MemorySource(
                    id=chunk.id,
                    source_type=chunk.source_type,
                    source_title=chunk.source_title,
                    source_url=chunk.source_url,
                    excerpt=chunk.content[:320],
                )
                for chunk in chunks
            ],
        )


def build_grounded_memory_prompt(question: str, context: str) -> str:
    return (
        "Answer only from the Rhapsody memory context. If the context is insufficient, "
        "say that clearly. Cite source numbers in every factual claim.\n\n"
        f"Context:\n{context or 'No context available.'}\n\nQuestion: {question}\nAnswer:"
    )


def rank_memory_chunks(
    question: str,
    chunks: list[MemoryChunk],
    top_k: int,
    embedding_service: EmbeddingService | None = None,
) -> list[MemoryChunk]:
    if not chunks:
        return []
    service = embedding_service or EmbeddingService()
    query_embedding = service.embed_text(question)
    ranked: list[tuple[float, int, MemoryChunk]] = []
    for index, chunk in enumerate(chunks):
        chunk_embedding = service.deserialize(chunk.embedding)
        if chunk_embedding is None:
            chunk_embedding = service.embed_text(f"{chunk.source_title}\n{chunk.content}")
        semantic_score = service.similarity(query_embedding, chunk_embedding)
        lexical_score = lexical_overlap_score(question, f"{chunk.source_title} {chunk.content}")
        ranked.append((semantic_score + lexical_score, index, chunk))
    ranked.sort(key=lambda item: (item[0], -item[1]), reverse=True)
    return [chunk for _, _, chunk in ranked[:top_k]]


def lexical_overlap_score(question: str, text: str) -> float:
    query_terms = set(tokenize(question))
    if not query_terms:
        return 0.0
    text_terms = set(tokenize(text))
    return len(query_terms & text_terms) / len(query_terms)
