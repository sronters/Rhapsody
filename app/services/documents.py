from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, Document, MemoryChunk
from app.repositories.workspace import WorkspaceRepository
from app.schemas.documents import DocumentIngestRequest
from app.services.embeddings import EmbeddingService


class DocumentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.workspace_repository = WorkspaceRepository(session)
        self.embedding_service = EmbeddingService()

    async def ingest(self, payload: DocumentIngestRequest) -> tuple[Document, int]:
        workspace = await self.workspace_repository.get(payload.workspace_id)
        document = Document(
            workspace_id=payload.workspace_id,
            uploaded_by_user_id=payload.uploaded_by_user_id,
            telegram_chat_id=payload.telegram_chat_id,
            telegram_message_id=payload.telegram_message_id,
            name=payload.name,
            content_type=payload.content_type,
            storage_key=payload.storage_key,
        )
        self.session.add(document)
        await self.session.flush()

        chunks = chunk_text(payload.extracted_text)
        for index, chunk in enumerate(chunks):
            self.session.add(
                MemoryChunk(
                    workspace_id=payload.workspace_id,
                    source_type="document",
                    source_id=document.id,
                    source_title=f"{payload.name} - chunk {index + 1}",
                    content=chunk,
                    embedding=self.embedding_service.embed_for_storage(f"{payload.name}\n{chunk}"),
                )
            )
        self.session.add(
            AuditLog(
                organization_id=workspace.organization_id,
                workspace_id=payload.workspace_id,
                action="document.ingested",
                resource_type="document",
                resource_id=document.id,
                metadata_json={"content_type": payload.content_type, "chunks": len(chunks)},
            )
        )
        await self.session.commit()
        return document, len(chunks)


def chunk_text(text: str, chunk_size: int = 1600, overlap: int = 160) -> list[str]:
    normalized = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if not normalized:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(start + chunk_size, len(normalized))
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(normalized):
            break
        start = max(0, end - overlap)
    return chunks
