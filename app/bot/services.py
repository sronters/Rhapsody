from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AuditLog,
    Decision,
    Meeting,
    MeetingSummary,
    MemoryChunk,
    Message,
    Organization,
    Risk,
    Task,
    TelegramChat,
    User,
    Workspace,
    WorkspaceMember,
)
from app.schemas.documents import DocumentIngestRequest
from app.schemas.memory import MemoryQuestion, MemorySource
from app.services.document_parsing import UnsupportedDocumentTypeError, extract_text_from_document
from app.services.documents import DocumentService
from app.services.embeddings import EmbeddingService
from app.services.memory import rank_memory_chunks
from app.services.product_ai import AIConfigurationError, AIResponseError, ProductAIClient
from app.services.stt import SpeechToTextService, STTConfigurationError, STTResponseError
from app.services.vision import (
    ImageUnderstandingService,
    VisionConfigurationError,
    VisionResponseError,
)

LOCAL_ORG_NAME = "Rhapsody Telegram"
SUPPORTED_DOCUMENT_TYPES = ".txt, .md, .csv, .docx, .xlsx, .pdf"
EMPTY_MEMORY_MESSAGE = (
    "No meetings, documents, or chat messages are indexed yet. Add a meeting or document first."
)


@dataclass(frozen=True)
class BotContext:
    organization_id: UUID
    workspace_id: UUID
    user_id: UUID


class TelegramProductService:
    def __init__(
        self,
        session: AsyncSession,
        ai_client: ProductAIClient | None = None,
        embedding_service: EmbeddingService | None = None,
        stt_service: SpeechToTextService | None = None,
        image_service: ImageUnderstandingService | None = None,
    ) -> None:
        self.session = session
        self.ai_client = ai_client or ProductAIClient()
        self.embedding_service = embedding_service or EmbeddingService()
        self.stt_service = stt_service or SpeechToTextService()
        self.image_service = image_service or ImageUnderstandingService()

    async def setup(
        self,
        telegram_user_id: int,
        display_name: str,
        telegram_chat_id: int,
        chat_title: str | None = None,
    ) -> BotContext:
        organization = await self._get_or_create_organization()
        user = await self._get_or_create_user(telegram_user_id, display_name)
        chat = (
            await self.session.scalars(
                select(TelegramChat).where(TelegramChat.telegram_chat_id == telegram_chat_id)
            )
        ).first()

        if chat is None:
            workspace_name = build_workspace_name(telegram_chat_id, chat_title)
            workspace = Workspace(organization_id=organization.id, name=workspace_name)
            self.session.add(workspace)
            await self.session.flush()
            self.session.add(
                AuditLog(
                    organization_id=organization.id,
                    workspace_id=workspace.id,
                    actor_user_id=user.id,
                    action="workspace.created",
                    resource_type="workspace",
                    resource_id=workspace.id,
                    metadata_json={
                        "source": "telegram_setup",
                        "telegram_chat_id": telegram_chat_id,
                    },
                )
            )
            chat = TelegramChat(
                workspace_id=workspace.id,
                telegram_chat_id=telegram_chat_id,
                title=chat_title,
            )
            self.session.add(chat)
        else:
            workspace = (
                await self.session.scalars(
                    select(Workspace).where(Workspace.id == chat.workspace_id)
                )
            ).one()
            chat.title = chat_title or chat.title

        await self._ensure_membership(workspace.id, user.id)
        self.session.add(
            AuditLog(
                organization_id=organization.id,
                workspace_id=workspace.id,
                actor_user_id=user.id,
                action="telegram.setup",
                resource_type="telegram_chat",
                resource_id=chat.id,
                metadata_json={"telegram_chat_id": telegram_chat_id},
            )
        )
        await self.session.commit()
        return BotContext(organization.id, workspace.id, user.id)

    async def context_for_chat(
        self,
        telegram_user_id: int,
        telegram_chat_id: int,
    ) -> BotContext | None:
        user = (
            await self.session.scalars(
                select(User).where(User.telegram_user_id == telegram_user_id)
            )
        ).first()
        if user is None:
            return None
        chat = (
            await self.session.scalars(
                select(TelegramChat).where(TelegramChat.telegram_chat_id == telegram_chat_id)
            )
        ).first()
        if chat is None:
            return None
        workspace = (
            await self.session.scalars(select(Workspace).where(Workspace.id == chat.workspace_id))
        ).one_or_none()
        if workspace is None:
            return None
        member = (
            await self.session.scalars(
                select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == workspace.id,
                    WorkspaceMember.user_id == user.id,
                )
            )
        ).first()
        if member is None:
            await self._ensure_membership(workspace.id, user.id, role="member")
            await self.session.commit()
        return BotContext(workspace.organization_id, workspace.id, user.id)

    async def ingest_meeting(self, context: BotContext, transcript: str) -> str:
        if not transcript.strip():
            return "Please send meeting notes with readable text."
        extraction = await self.ai_client.extract_meeting(transcript)
        meeting = Meeting(
            workspace_id=context.workspace_id,
            title="Telegram meeting notes",
            source="telegram",
            status="processed",
            started_at=datetime.now(timezone.utc),
        )
        self.session.add(meeting)
        await self.session.flush()
        self.session.add(
            MeetingSummary(meeting_id=meeting.id, summary=extraction.summary, topics=[])
        )

        for item in extraction.tasks:
            task = Task(
                workspace_id=context.workspace_id,
                title=item.title,
                description=format_task_description(
                    item.assignee,
                    item.deadline,
                    item.priority,
                    item.source_text,
                ),
                status="open",
                due_at=parse_deadline(item.deadline),
                source_type="meeting",
                source_id=meeting.id,
            )
            self.session.add(task)
            await self.session.flush()
            self._add_memory(
                "task",
                task.id,
                task.title,
                format_task_memory(
                    item.title,
                    item.assignee,
                    item.deadline,
                    item.priority,
                    item.source_text,
                ),
                context.workspace_id,
            )

        for item in extraction.decisions:
            decision = Decision(
                workspace_id=context.workspace_id,
                title=item.title,
                rationale=item.rationale,
                source_type="meeting",
                source_id=meeting.id,
            )
            self.session.add(decision)
            await self.session.flush()
            self._add_memory(
                "decision",
                decision.id,
                decision.title,
                format_decision_memory(item.title, item.rationale, item.source_text),
                context.workspace_id,
            )

        for item in extraction.risks:
            risk = Risk(
                workspace_id=context.workspace_id,
                title=item.title,
                severity=item.severity,
                mitigation=item.mitigation,
            )
            self.session.add(risk)
            await self.session.flush()
            self._add_memory(
                "risk",
                risk.id,
                risk.title,
                format_risk_memory(item.title, item.severity, item.mitigation, item.source_text),
                context.workspace_id,
            )

        self._add_memory(
            "meeting",
            meeting.id,
            meeting.title,
            f"{extraction.summary}\n\nTranscript excerpt:\n{transcript[:4000]}",
            context.workspace_id,
        )
        self.session.add(
            AuditLog(
                organization_id=context.organization_id,
                workspace_id=context.workspace_id,
                actor_user_id=context.user_id,
                action="meeting.ingested",
                resource_type="meeting",
                resource_id=meeting.id,
                metadata_json={"source": "telegram", "ai_mode": self.ai_client.settings.ai_mode},
            )
        )
        await self.session.commit()
        return format_meeting_extraction(extraction)

    async def ingest_meeting_media(
        self,
        context: BotContext,
        content: bytes,
        filename: str,
        content_type: str | None,
    ) -> str:
        transcript = await self.stt_service.transcribe(content, filename, content_type)
        return await self.ingest_meeting(context, transcript)

    async def ingest_chat_message(
        self,
        context: BotContext,
        telegram_message_id: int | None,
        text: str,
    ) -> None:
        cleaned = text.strip()
        if not cleaned:
            return
        message = Message(
            workspace_id=context.workspace_id,
            telegram_message_id=telegram_message_id,
            sender_user_id=context.user_id,
            content=cleaned,
            importance="normal",
        )
        self.session.add(message)
        await self.session.flush()
        self._add_memory("chat", message.id, "Telegram chat", cleaned, context.workspace_id)
        self.session.add(
            AuditLog(
                organization_id=context.organization_id,
                workspace_id=context.workspace_id,
                actor_user_id=context.user_id,
                action="chat.memory_saved",
                resource_type="message",
                resource_id=message.id,
                metadata_json={"source": "telegram"},
            )
        )
        await self.session.commit()

    async def ingest_media_message(
        self,
        context: BotContext,
        telegram_message_id: int | None,
        content: bytes,
        filename: str,
        content_type: str | None,
    ) -> str:
        transcript = await self.stt_service.transcribe(content, filename, content_type)
        await self.ingest_chat_message(
            context,
            telegram_message_id,
            f"Transcribed Telegram media ({filename}):\n{transcript}",
        )
        return "Recording transcribed and saved into team memory."

    async def ingest_document_text(
        self,
        context: BotContext,
        text: str,
        name: str = "Telegram document",
    ) -> str:
        if not text.strip():
            return "I could not find indexable text in this document. Please send readable text."
        request = DocumentIngestRequest(
            workspace_id=context.workspace_id,
            name=name,
            content_type="text/plain",
            storage_key=f"telegram/{context.workspace_id}/{uuid.uuid4()}.txt",
            extracted_text=text,
        )
        document, chunks_created = await DocumentService(self.session).ingest(request)
        if chunks_created == 0:
            return "I could not find indexable text in this document. Please send readable text."
        self.session.add(
            AuditLog(
                organization_id=context.organization_id,
                workspace_id=context.workspace_id,
                actor_user_id=context.user_id,
                action="telegram.document_saved",
                resource_type="document",
                resource_id=document.id,
                metadata_json={"chunks": chunks_created},
            )
        )
        await self.session.commit()
        return "Document saved and indexed.\nYou can now ask questions about it with /ask."

    async def ingest_document_file(
        self,
        context: BotContext,
        content: bytes,
        filename: str,
        content_type: str | None,
    ) -> str:
        if is_image_file(filename, content_type):
            return await self.ingest_image(context, content, filename, content_type)
        extracted_text = extract_supported_document_text(content, filename, content_type)
        return await self.ingest_document_text(context, extracted_text, name=filename)

    async def ingest_image(
        self,
        context: BotContext,
        content: bytes,
        filename: str,
        content_type: str | None,
    ) -> str:
        extracted_text = await self.image_service.describe_image(content, content_type)
        request = DocumentIngestRequest(
            workspace_id=context.workspace_id,
            name=filename,
            content_type=content_type or "image/jpeg",
            storage_key=f"telegram/{context.workspace_id}/{uuid.uuid4()}-{filename}",
            extracted_text=extracted_text,
        )
        document, chunks_created = await DocumentService(self.session).ingest(request)
        if chunks_created == 0:
            return "I could not find indexable content in this image."
        self.session.add(
            AuditLog(
                organization_id=context.organization_id,
                workspace_id=context.workspace_id,
                actor_user_id=context.user_id,
                action="telegram.image_saved",
                resource_type="document",
                resource_id=document.id,
                metadata_json={"chunks": chunks_created, "content_type": request.content_type},
            )
        )
        await self.session.commit()
        return "Image saved and indexed.\nYou can now ask questions about it with /ask."

    async def ask(self, context: BotContext, question: str) -> str:
        memory_question = MemoryQuestion(
            workspace_id=context.workspace_id,
            question=question,
            top_k=6,
        )
        candidate_chunks = list(
            (
                await self.session.scalars(
                    select(MemoryChunk)
                    .where(MemoryChunk.workspace_id == context.workspace_id)
                    .order_by(MemoryChunk.created_at.desc())
                    .limit(48)
                )
            ).all()
        )
        chunks = rank_memory_chunks(
            memory_question.question,
            candidate_chunks,
            top_k=memory_question.top_k,
            embedding_service=self.embedding_service,
        )
        if not chunks:
            return EMPTY_MEMORY_MESSAGE
        sources = [
            MemorySource(
                id=chunk.id,
                source_type=chunk.source_type,
                source_title=chunk.source_title,
                source_url=chunk.source_url,
                excerpt=chunk.content[:320],
            )
            for chunk in chunks
        ]
        ai_answer = await self.ai_client.answer_question(question, sources)
        return format_answer(ai_answer, sources)

    async def list_tasks(self, context: BotContext) -> str:
        rows = (
            await self.session.scalars(
                select(Task)
                .where(Task.workspace_id == context.workspace_id)
                .order_by(Task.created_at.desc())
            )
        ).all()
        if not rows:
            return "No tasks are saved yet."
        return "✅ Tasks\n" + "\n".join(
            f"{index}. {task.title}\n   Status: {task.status}"
            f"{(' — due ' + format_datetime(task.due_at)) if task.due_at else ''}"
            for index, task in enumerate(rows, start=1)
        )

    async def update_task_status(
        self,
        context: BotContext,
        task_number: int,
        status: str,
    ) -> str:
        normalized = status.strip().lower().replace(" ", "_")
        allowed = {"open", "in_progress", "blocked", "done", "cancelled"}
        if normalized not in allowed:
            return "Please use one of these statuses: open, in_progress, blocked, done, cancelled."
        tasks = list(
            (
                await self.session.scalars(
                    select(Task)
                    .where(Task.workspace_id == context.workspace_id)
                    .order_by(Task.created_at.desc())
                )
            ).all()
        )
        if task_number < 1 or task_number > len(tasks):
            return "I could not find that task number. Use /tasks to see the current list."
        task = tasks[task_number - 1]
        previous_status = task.status
        task.status = normalized
        self.session.add(
            AuditLog(
                organization_id=context.organization_id,
                workspace_id=context.workspace_id,
                actor_user_id=context.user_id,
                action="task.status_updated",
                resource_type="task",
                resource_id=task.id,
                metadata_json={"from": previous_status, "to": normalized, "source": "telegram"},
            )
        )
        await self.session.commit()
        return f"Task updated.\n{task.title}\nStatus: {normalized}"

    async def list_reminders(self, context: BotContext) -> str:
        now = datetime.now(timezone.utc)
        upcoming = now + timedelta(days=14)
        rows = (
            await self.session.scalars(
                select(Task)
                .where(
                    Task.workspace_id == context.workspace_id,
                    Task.status != "done",
                    Task.due_at.is_not(None),
                    Task.due_at <= upcoming,
                )
                .order_by(Task.due_at.asc())
            )
        ).all()
        if not rows:
            return "No upcoming task reminders are scheduled."
        return "🔔 Upcoming reminders\n" + "\n".join(
            f"{index}. {task.title}\n"
            f"   Due: {format_datetime(task.due_at)}\n"
            f"   Status: {task.status}"
            for index, task in enumerate(rows, start=1)
        )

    async def task_status_summary(self, context: BotContext) -> str:
        rows = (
            await self.session.scalars(
                select(Task).where(Task.workspace_id == context.workspace_id)
            )
        ).all()
        if not rows:
            return "No tasks are saved yet."
        counts: dict[str, int] = {}
        for task in rows:
            counts[task.status] = counts.get(task.status, 0) + 1
        lines = [f"{status}: {count}" for status, count in sorted(counts.items())]
        return "📊 Task status\n" + "\n".join(lines)

    async def list_decisions(self, context: BotContext) -> str:
        rows = (
            await self.session.scalars(
                select(Decision)
                .where(Decision.workspace_id == context.workspace_id)
                .order_by(Decision.created_at.desc())
            )
        ).all()
        if not rows:
            return "No decisions are saved yet."
        return "📌 Decisions\n" + "\n".join(
            f"{index}. {decision.title}\n   {decision.rationale}"
            for index, decision in enumerate(rows, start=1)
        )

    async def list_audit(self, context: BotContext) -> str:
        rows = (
            await self.session.scalars(
                select(AuditLog)
                .where(AuditLog.workspace_id == context.workspace_id)
                .order_by(AuditLog.created_at.desc())
                .limit(10)
            )
        ).all()
        if not rows:
            return "No audit events are available."
        return "🧾 Audit events\n" + "\n".join(
            f"{index}. {entry.action} — {entry.resource_type}"
            for index, entry in enumerate(rows, start=1)
        )

    async def _get_or_create_organization(self) -> Organization:
        organization = (
            await self.session.scalars(
                select(Organization).where(Organization.name == LOCAL_ORG_NAME)
            )
        ).first()
        if organization is not None:
            return organization
        organization = Organization(
            name=LOCAL_ORG_NAME,
            deployment_mode="cloud",
            retention_mode="standard",
        )
        self.session.add(organization)
        await self.session.flush()
        self.session.add(
            AuditLog(
                organization_id=organization.id,
                action="organization.created",
                resource_type="organization",
                resource_id=organization.id,
                metadata_json={"source": "telegram_setup"},
            )
        )
        return organization

    async def _get_or_create_user(self, telegram_user_id: int, display_name: str) -> User:
        user = (
            await self.session.scalars(
                select(User).where(User.telegram_user_id == telegram_user_id)
            )
        ).first()
        if user is None:
            user = User(telegram_user_id=telegram_user_id, display_name=display_name)
            self.session.add(user)
            await self.session.flush()
        else:
            user.display_name = display_name
        return user

    async def _ensure_membership(
        self,
        workspace_id: UUID,
        user_id: UUID,
        role: str = "admin",
    ) -> None:
        member = (
            await self.session.scalars(
                select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.user_id == user_id,
                )
            )
        ).first()
        if member is None:
            self.session.add(WorkspaceMember(workspace_id=workspace_id, user_id=user_id, role=role))

    def _add_memory(
        self,
        source_type: str,
        source_id: UUID,
        source_title: str,
        content: str,
        workspace_id: UUID,
    ) -> None:
        self.session.add(
            MemoryChunk(
                workspace_id=workspace_id,
                source_type=source_type,
                source_id=source_id,
                source_title=source_title,
                content=content,
                embedding=self.embedding_service.embed_for_storage(f"{source_title}\n{content}"),
            )
        )


def extract_supported_document_text(content: bytes, filename: str, content_type: str | None) -> str:
    try:
        extracted_text = extract_text_from_document(content, filename, content_type)
    except UnsupportedDocumentTypeError as exc:
        raise UnsupportedDocumentTypeError(
            f"Unsupported file type. Please send one of: {SUPPORTED_DOCUMENT_TYPES}."
        ) from exc
    if not extracted_text.strip():
        raise UnsupportedDocumentTypeError("I could not extract readable text from this file.")
    return extracted_text


def is_image_file(filename: str, content_type: str | None) -> bool:
    normalized_type = (content_type or "").split(";", maxsplit=1)[0].lower()
    return normalized_type.startswith("image/") or filename.lower().endswith(
        (".jpg", ".jpeg", ".png", ".webp")
    )


def build_workspace_name(telegram_chat_id: int, chat_title: str | None) -> str:
    title = (chat_title or "Telegram chat").strip()
    return f"{title} ({telegram_chat_id})"[:160]


def format_task_description(
    assignee: str | None,
    deadline: str | None,
    priority: str | None,
    source_text: str | None,
) -> str:
    return "\n".join(
        part
        for part in [
            f"Owner: {assignee}" if assignee else None,
            f"Deadline: {deadline}" if deadline else None,
            f"Priority: {priority}" if priority else None,
            f"Source: {source_text}" if source_text else None,
        ]
        if part
    )


def format_task_memory(
    title: str,
    assignee: str | None,
    deadline: str | None,
    priority: str | None,
    source_text: str | None,
) -> str:
    return "\n".join(
        part
        for part in [
            title,
            f"Owner: {assignee}" if assignee else None,
            f"Deadline: {deadline}" if deadline else None,
            f"Priority: {priority}" if priority else None,
            f"Source: {source_text}" if source_text else None,
        ]
        if part
    )


def format_decision_memory(title: str, rationale: str, source_text: str | None) -> str:
    return "\n".join(
        part
        for part in [
            title,
            f"Rationale: {rationale}",
            f"Source: {source_text}" if source_text else None,
        ]
        if part
    )


def format_risk_memory(
    title: str,
    severity: str,
    mitigation: str | None,
    source_text: str | None,
) -> str:
    return "\n".join(
        part
        for part in [
            title,
            f"Severity: {severity}",
            f"Mitigation: {mitigation}" if mitigation else None,
            f"Source: {source_text}" if source_text else None,
        ]
        if part
    )


def parse_deadline(value: str | None) -> datetime | None:
    if not value:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    iso_match = re.search(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?", candidate)
    if not iso_match:
        return None
    normalized = iso_match.group(0).replace(" ", "T")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def format_meeting_extraction(extraction) -> str:
    tasks = (
        "\n".join(
            f"{index}. {item.title}\n"
            f"   Owner: {item.assignee or 'Not specified'}\n"
            f"   Deadline: {item.deadline or 'Not specified'}\n"
            f"   Priority: {item.priority or 'Not specified'}"
            for index, item in enumerate(extraction.tasks, start=1)
        )
        or "No tasks identified."
    )
    decisions = (
        "\n".join(
            f"{index}. {item.title}" for index, item in enumerate(extraction.decisions, start=1)
        )
        or "No decisions identified."
    )
    risks = (
        "\n".join(
            f"{index}. {item.title} ({item.severity})"
            for index, item in enumerate(extraction.risks, start=1)
        )
        or "No risks identified."
    )
    return (
        f"🧠 Meeting Summary\n\n{extraction.summary}\n\n"
        f"✅ Tasks\n{tasks}\n\n"
        f"📌 Decisions\n{decisions}\n\n"
        f"⚠️ Risks\n{risks}\n\n"
        f"➡️ Follow-up\n{extraction.follow_up or 'No follow-up suggested.'}"
    )


def format_answer(answer: str, sources: list[MemorySource]) -> str:
    source_lines = "\n".join(
        f"{index}. {format_source_type(source.source_type)} — {source.source_title}"
        for index, source in enumerate(sources, start=1)
    )
    return f"Answer:\n{answer}\n\nSources:\n{source_lines}"


def format_source_type(source_type: str) -> str:
    return source_type.replace("_", " ").title()


def provider_error_message(exc: Exception) -> str:
    if isinstance(
        exc,
        AIConfigurationError
        | AIResponseError
        | UnsupportedDocumentTypeError
        | STTConfigurationError
        | STTResponseError
        | VisionConfigurationError
        | VisionResponseError,
    ):
        return str(exc)
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        if status_code == 401:
            return "The selected AI provider rejected the API key. Check the configured API key."
        if status_code == 402:
            return (
                "The selected AI provider requires billing or credits before this request can run."
            )
        if status_code == 429:
            return (
                "The selected AI provider rate limit or quota was reached. "
                "Check billing, credits, and usage limits."
            )
        if status_code >= 500:
            return "The selected AI provider is temporarily unavailable. Try again shortly."
        return (
            "The selected AI provider returned an error. Check the provider key, model access, "
            "and service status."
        )
    if isinstance(exc, httpx.HTTPError):
        return "The selected AI provider is unavailable. Check the provider connection settings."
    return "The request could not be completed. Please try again or check the service logs."
