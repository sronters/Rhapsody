from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AuditLog,
    Decision,
    Meeting,
    MeetingSummary,
    MemoryChunk,
    Risk,
    Task,
    Workspace,
)
from app.schemas.meetings import MeetingIngestRequest, MeetingIntelligence
from app.services.embeddings import EmbeddingService


class MeetingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.embedding_service = EmbeddingService()

    async def enqueue_ingestion(self, payload: MeetingIngestRequest) -> Meeting:
        workspace = (
            await self.session.scalars(
                select(Workspace).where(Workspace.id == payload.workspace_id)
            )
        ).one()
        meeting = Meeting(
            workspace_id=payload.workspace_id,
            title=payload.title,
            source=payload.source,
            status="queued",
            started_at=payload.started_at,
        )
        self.session.add(meeting)
        await self.session.flush()

        if payload.transcript_text:
            intelligence = extract_meeting_intelligence(payload.transcript_text)
            memory_content = f"{intelligence.summary}\n\n{payload.transcript_text[:4000]}"
            self.session.add(
                MeetingSummary(
                    meeting_id=meeting.id,
                    summary=intelligence.summary,
                    topics=intelligence.topics,
                )
            )
            for decision_text in intelligence.decisions:
                decision = Decision(
                    workspace_id=payload.workspace_id,
                    title=trim_title(decision_text),
                    rationale=f"Extracted from meeting transcript: {decision_text}",
                    source_type="meeting",
                    source_id=meeting.id,
                )
                self.session.add(decision)
                await self.session.flush()
                self.session.add(
                    MemoryChunk(
                        workspace_id=payload.workspace_id,
                        source_type="decision",
                        source_id=decision.id,
                        source_title=decision.title,
                        content=f"{decision.title}\n\nRationale: {decision.rationale}",
                        embedding=self.embedding_service.embed_for_storage(
                            f"{decision.title}\n{decision.rationale}"
                        ),
                    )
                )
            for extracted_task in intelligence.tasks:
                self.session.add(
                    Task(
                        workspace_id=payload.workspace_id,
                        title=trim_title(extracted_task.title),
                        description=extracted_task.title,
                        status="open",
                        source_type="meeting",
                        source_id=meeting.id,
                    )
                )
            for risk_text in intelligence.risks:
                self.session.add(
                    Risk(
                        workspace_id=payload.workspace_id,
                        title=trim_title(risk_text),
                        severity=infer_risk_severity(risk_text),
                        mitigation="Review and assign an owner.",
                    )
                )
            self.session.add(
                MemoryChunk(
                    workspace_id=payload.workspace_id,
                    source_type="meeting",
                    source_id=meeting.id,
                    source_title=payload.title,
                    content=memory_content,
                    embedding=self.embedding_service.embed_for_storage(
                        f"{payload.title}\n{memory_content}"
                    ),
                )
            )
            meeting.status = "processed"

        self.session.add(
            AuditLog(
                organization_id=workspace.organization_id,
                workspace_id=payload.workspace_id,
                action="meeting.ingested",
                resource_type="meeting",
                resource_id=meeting.id,
                metadata_json={
                    "source": payload.source,
                    "has_transcript": bool(payload.transcript_text),
                },
            )
        )
        await self.session.commit()
        return meeting


def extract_meeting_intelligence(transcript: str) -> MeetingIntelligence:
    normalized = " ".join(transcript.split())
    sentences = [part.strip() for part in normalized.replace("?", ".").split(".") if part.strip()]
    summary = ". ".join(sentences[:3]) or "No transcript content was available."
    decisions = [
        sentence
        for sentence in sentences
        if any(marker in sentence.lower() for marker in ["decided", "choose", "agreed", "решили"])
    ][:10]
    tasks = [
        {"title": sentence, "assignee_hint": None, "due_hint": None}
        for sentence in sentences
        if any(marker in sentence.lower() for marker in ["i will", "todo", "task", "сделаю"])
    ][:20]
    risks = [
        sentence
        for sentence in sentences
        if any(marker in sentence.lower() for marker in ["risk", "blocked", "problem", "риск"])
    ][:10]
    topics = sorted({word.strip(",:;").title() for word in normalized.split() if len(word) > 8})[:8]
    follow_up = "Confirm owners and due dates for every extracted task before the next meeting."
    return MeetingIntelligence(
        summary=summary,
        topics=topics,
        decisions=decisions,
        tasks=tasks,
        risks=risks,
        follow_up=follow_up,
    )


def trim_title(text: str, max_length: int = 320) -> str:
    cleaned = " ".join(text.split()).strip(" .")
    if len(cleaned) <= max_length:
        return cleaned or "Untitled extracted item"
    return cleaned[: max_length - 1].rstrip() + "…"


def infer_risk_severity(text: str) -> str:
    lowered = text.lower()
    if any(marker in lowered for marker in ["critical", "blocked", "blocker", "high"]):
        return "high"
    if any(marker in lowered for marker in ["medium", "risk", "problem"]):
        return "medium"
    return "low"
