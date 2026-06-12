from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AuditLog,
    Decision,
    Document,
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
MANAGE_ROLES = {"owner", "admin"}
WRITE_ROLES = {"owner", "admin", "member"}
READ_ROLES = {"owner", "admin", "member", "viewer"}


@dataclass(frozen=True)
class BotContext:
    organization_id: UUID
    workspace_id: UUID
    user_id: UUID
    role: str = "member"
    workspace_name: str = "Workspace"
    telegram_chat_id: int | None = None
    chat_type: str = "private"


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
        chat_type: str = "private",
    ) -> BotContext | None:
        organization = await self._get_or_create_organization()
        user = await self._get_or_create_user(telegram_user_id, display_name)
        context = await self.context_for_chat(
            telegram_user_id,
            telegram_chat_id,
            chat_type,
        )
        if context is not None:
            return context

        if is_group_chat_type(chat_type):
            await self.session.commit()
            return None

        return await self._create_project_for_user(
            organization,
            user,
            name=build_workspace_name(telegram_chat_id, chat_title),
            telegram_chat_id=telegram_chat_id,
            chat_title=chat_title,
            chat_type=chat_type,
            audit_source="telegram_setup",
        )

    async def context_for_chat(
        self,
        telegram_user_id: int,
        telegram_chat_id: int,
        chat_type: str = "private",
    ) -> BotContext | None:
        user = (
            await self.session.scalars(
                select(User).where(User.telegram_user_id == telegram_user_id)
            )
        ).first()
        if user is None:
            return None
        chat = await self._active_chat_for_telegram_chat(telegram_chat_id, user.id, chat_type)
        if chat is None:
            return None
        workspace = (
            await self.session.scalars(
                select(Workspace).where(
                    Workspace.id == chat.workspace_id,
                    Workspace.status == "active",
                )
            )
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
            return None
        return BotContext(
            workspace.organization_id,
            workspace.id,
            user.id,
            member.role,
            workspace.name,
            telegram_chat_id,
            chat_type,
        )

    async def ingest_meeting(self, context: BotContext, transcript: str) -> str:
        require_write_access(context)
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
        require_write_access(context)
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
        telegram_message_id: int | None = None,
    ) -> str:
        require_write_access(context)
        if not text.strip():
            return "I could not find indexable text in this document. Please send readable text."
        request = DocumentIngestRequest(
            workspace_id=context.workspace_id,
            name=name,
            content_type="text/plain",
            storage_key=f"telegram/{context.workspace_id}/{uuid.uuid4()}.txt",
            extracted_text=text,
            uploaded_by_user_id=context.user_id,
            telegram_chat_id=context.telegram_chat_id,
            telegram_message_id=telegram_message_id,
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
        telegram_message_id: int | None = None,
    ) -> str:
        if is_image_file(filename, content_type):
            return await self.ingest_image(
                context,
                content,
                filename,
                content_type,
                telegram_message_id,
            )
        extracted_text = extract_supported_document_text(content, filename, content_type)
        return await self.ingest_document_text(
            context,
            extracted_text,
            name=filename,
            telegram_message_id=telegram_message_id,
        )

    async def ingest_image(
        self,
        context: BotContext,
        content: bytes,
        filename: str,
        content_type: str | None,
        telegram_message_id: int | None = None,
    ) -> str:
        require_write_access(context)
        extracted_text = await self.image_service.describe_image(content, content_type)
        request = DocumentIngestRequest(
            workspace_id=context.workspace_id,
            name=filename,
            content_type=content_type or "image/jpeg",
            storage_key=f"telegram/{context.workspace_id}/{uuid.uuid4()}-{filename}",
            extracted_text=extracted_text,
            uploaded_by_user_id=context.user_id,
            telegram_chat_id=context.telegram_chat_id,
            telegram_message_id=telegram_message_id,
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
        rows = await self._ordered_tasks(context)
        if not rows:
            return "Задач пока нет."
        return "Задачи\n" + "\n".join(
            f"{index}. {task.title}\n   Статус: {task.status}"
            f"{(' — срок ' + format_datetime(task.due_at)) if task.due_at else ''}"
            for index, task in enumerate(rows, start=1)
        )

    async def task_detail(self, context: BotContext, task_number: int) -> str:
        rows = await self._ordered_tasks(context)
        if task_number < 1 or task_number > len(rows):
            return "Не нашёл задачу с таким номером. Используй /tasks."
        task = rows[task_number - 1]
        return "\n".join(
            part
            for part in [
                f"Задача {task_number}",
                task.title,
                f"Статус: {task.status}",
                f"Срок: {format_datetime(task.due_at)}" if task.due_at else "Срок: не указан",
                task.description or None,
            ]
            if part
        )

    async def update_task_status(
        self,
        context: BotContext,
        task_number: int,
        status: str,
    ) -> str:
        require_write_access(context)
        normalized = status.strip().lower().replace(" ", "_")
        allowed = {"open", "in_progress", "blocked", "done", "cancelled"}
        if normalized not in allowed:
            return "Используй один из статусов: open, in_progress, blocked, done, cancelled."
        tasks = await self._ordered_tasks(context)
        if task_number < 1 or task_number > len(tasks):
            return "Не нашёл задачу с таким номером. Используй /tasks."
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
        return f"Задача обновлена.\n{task.title}\nСтатус: {normalized}"

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
            return "Ближайших напоминаний по задачам нет."
        return "Ближайшие напоминания\n" + "\n".join(
            f"{index}. {task.title}\n"
            f"   Срок: {format_datetime(task.due_at)}\n"
            f"   Статус: {task.status}"
            for index, task in enumerate(rows, start=1)
        )

    async def task_status_summary(self, context: BotContext) -> str:
        rows = await self._ordered_tasks(context)
        if not rows:
            return "Задач пока нет."
        counts: dict[str, int] = {}
        for task in rows:
            counts[task.status] = counts.get(task.status, 0) + 1
        lines = [f"{status}: {count}" for status, count in sorted(counts.items())]
        return "Статусы задач\n" + "\n".join(lines)

    async def list_decisions(self, context: BotContext) -> str:
        rows = await self._ordered_decisions(context)
        if not rows:
            return "Решений пока нет."
        return "Решения\n" + "\n".join(
            f"{index}. {decision.title}\n"
            f"   {decision.rationale or 'Обоснование не указано.'}\n"
            f"   Источник: {format_source_type(decision.source_type)}"
            f"{(' - ' + format_datetime(decision.created_at)) if decision.created_at else ''}"
            for index, decision in enumerate(rows, start=1)
        )

    async def decision_detail(self, context: BotContext, decision_number: int) -> str:
        rows = await self._ordered_decisions(context)
        if decision_number < 1 or decision_number > len(rows):
            return "Не нашёл решение с таким номером. Используй /decisions."
        decision = rows[decision_number - 1]
        return "\n".join(
            part
            for part in [
                f"Решение {decision_number}",
                decision.title,
                decision.rationale or "Обоснование не указано.",
                f"Источник: {format_source_type(decision.source_type)}",
            ]
            if part
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
        return "рџ§ѕ Audit events\n" + "\n".join(
            f"{index}. {entry.action} вЂ” {entry.resource_type}"
            for index, entry in enumerate(rows, start=1)
        )

    async def list_available_projects(
        self,
        telegram_user_id: int,
        display_name: str,
        telegram_chat_id: int,
        chat_type: str = "private",
    ) -> str:
        user = await self._get_or_create_user(telegram_user_id, display_name)
        rows = await self._projects_for_user(user.id)
        selected = await self._active_chat_for_telegram_chat(telegram_chat_id, user.id, chat_type)
        await self.session.commit()
        if not rows:
            return "Проектов пока нет. Создайте новый: /new_project Название"
        lines = []
        for index, (workspace, member) in enumerate(rows, start=1):
            marker = "* " if selected is not None and selected.workspace_id == workspace.id else ""
            lines.append(f"{index}. {marker}{workspace.name} - роль: {member.role}")
        return "Проекты\n" + "\n".join(lines) + "\n\n* - выбранный проект."

    async def create_project_for_telegram_user(
        self,
        telegram_user_id: int,
        display_name: str,
        telegram_chat_id: int,
        chat_type: str,
        name: str,
        chat_title: str | None = None,
    ) -> str:
        organization = await self._get_or_create_organization()
        user = await self._get_or_create_user(telegram_user_id, display_name)
        workspace_name = name.strip()
        if not workspace_name:
            return "Напишите название проекта: /new_project Название"
        if is_group_chat_type(chat_type):
            await self._require_group_project_manager(user, telegram_chat_id)
        context = await self._create_project_for_user(
            organization,
            user,
            name=workspace_name,
            telegram_chat_id=telegram_chat_id,
            chat_title=chat_title,
            chat_type=chat_type,
            audit_source="telegram_new_project",
        )
        return f"Проект {context.workspace_name} создан и выбран."

    async def use_project_for_telegram_user(
        self,
        telegram_user_id: int,
        display_name: str,
        telegram_chat_id: int,
        chat_type: str,
        selector: str,
        chat_title: str | None = None,
    ) -> str:
        user = await self._get_or_create_user(telegram_user_id, display_name)
        if is_group_chat_type(chat_type):
            await self._require_group_project_manager(user, telegram_chat_id)
        rows = await self._projects_for_user(user.id)
        if not rows:
            await self.session.commit()
            return "У вас пока нет проектов. Создайте новый: /new_project Название"
        selected = select_project_row(rows, selector)
        if selected is None:
            await self.session.commit()
            return "Не нашёл проект. Используйте /projects и выберите номер, id или название."
        workspace, member = selected
        if is_group_chat_type(chat_type) and member.role not in MANAGE_ROLES:
            await self.session.commit()
            raise PermissionError(
                "Привязать группу к проекту может только owner или admin этого проекта."
            )
        await self._select_workspace_for_chat(
            workspace,
            user,
            telegram_chat_id,
            chat_title,
            chat_type,
            member.role,
            action="workspace.activated",
        )
        await self.session.commit()
        if is_group_chat_type(chat_type):
            return f"Группа привязана к проекту {workspace.name}."
        return f"Выбран проект: {workspace.name}"

    async def list_projects(self, context: BotContext, telegram_chat_id: int) -> str:
        rows = (
            await self.session.execute(
                select(Workspace, TelegramChat, WorkspaceMember)
                .join(TelegramChat, TelegramChat.workspace_id == Workspace.id)
                .join(
                    WorkspaceMember,
                    (WorkspaceMember.workspace_id == Workspace.id)
                    & (WorkspaceMember.user_id == context.user_id),
                )
                .where(TelegramChat.telegram_chat_id == telegram_chat_id)
                .order_by(TelegramChat.is_active.desc(), Workspace.name.asc())
            )
        ).all()
        if not rows:
            return "Проекты в этом чате не найдены. Используй /setup."
        lines = [
            f"{index}. {'* ' if chat.is_active else ''}{workspace.name} — роль: {member.role}"
            for index, (workspace, chat, member) in enumerate(rows, start=1)
        ]
        return "Проекты\n" + "\n".join(lines) + "\n\n* — активный проект."

    async def create_project(
        self,
        context: BotContext,
        telegram_chat_id: int,
        name: str,
        chat_title: str | None = None,
    ) -> str:
        require_manage_access(context)
        cleaned = name.strip()
        if not cleaned:
            return "Напиши название проекта: /project_new Название проекта"
        await self._deactivate_chat_projects(telegram_chat_id, context.user_id, context.chat_type)
        workspace = Workspace(
            organization_id=context.organization_id,
            name=cleaned[:160],
            created_by_user_id=context.user_id,
            status="active",
        )
        self.session.add(workspace)
        await self.session.flush()
        self.session.add(
            TelegramChat(
                workspace_id=workspace.id,
                telegram_chat_id=telegram_chat_id,
                selected_by_user_id=None
                if is_group_chat_type(context.chat_type)
                else context.user_id,
                chat_type=normalize_chat_type(context.chat_type),
                title=chat_title,
                is_active=True,
            )
        )
        self.session.add(
            WorkspaceMember(workspace_id=workspace.id, user_id=context.user_id, role="owner")
        )
        self.session.add(
            AuditLog(
                organization_id=context.organization_id,
                workspace_id=workspace.id,
                actor_user_id=context.user_id,
                action="workspace.created",
                resource_type="workspace",
                resource_id=workspace.id,
                metadata_json={"source": "telegram_project_new"},
            )
        )
        await self.session.commit()
        return f"Проект создан и выбран.\nАктивный проект: {workspace.name}"

    async def use_project(
        self,
        context: BotContext,
        telegram_chat_id: int,
        selector: str,
    ) -> str:
        require_manage_access(context)
        rows = (
            await self.session.execute(
                select(Workspace, TelegramChat, WorkspaceMember)
                .join(TelegramChat, TelegramChat.workspace_id == Workspace.id)
                .join(
                    WorkspaceMember,
                    (WorkspaceMember.workspace_id == Workspace.id)
                    & (WorkspaceMember.user_id == context.user_id),
                )
                .where(TelegramChat.telegram_chat_id == telegram_chat_id)
                .order_by(TelegramChat.is_active.desc(), Workspace.name.asc())
            )
        ).all()
        if not rows:
            return "Проекты в этом чате не найдены."
        selected = None
        if selector.strip().isdigit():
            index = int(selector.strip())
            if 1 <= index <= len(rows):
                selected = rows[index - 1]
        if selected is None:
            lowered = selector.strip().lower()
            selected = next(
                (
                    row
                    for row in rows
                    if row[0].name.lower() == lowered or lowered in row[0].name.lower()
                ),
                None,
            )
        if selected is None:
            return "Не нашёл проект. Используй /projects и выбери номер."
        workspace, chat, _member = selected
        await self._deactivate_chat_projects(telegram_chat_id, context.user_id, context.chat_type)
        chat.is_active = True
        self.session.add(
            AuditLog(
                organization_id=context.organization_id,
                workspace_id=workspace.id,
                actor_user_id=context.user_id,
                action="workspace.activated",
                resource_type="workspace",
                resource_id=workspace.id,
                metadata_json={"telegram_chat_id": telegram_chat_id},
            )
        )
        await self.session.commit()
        return f"Активный проект: {workspace.name}"

    async def current_project(self, context: BotContext) -> str:
        return f"Активный проект: {context.workspace_name}\nТвоя роль: {context.role}"

    async def project_info(self, context: BotContext) -> str:
        workspace = await self.session.get(Workspace, context.workspace_id)
        if workspace is None:
            return "Проект не найден."
        member_count = await self.session.scalar(
            select(func.count())
            .select_from(WorkspaceMember)
            .where(WorkspaceMember.workspace_id == context.workspace_id)
        )
        return "\n".join(
            [
                f"Проект: {workspace.name}",
                f"ID: {workspace.id}",
                f"Статус: {workspace.status}",
                f"Роль: {context.role}",
                f"Участников: {member_count or 0}",
                f"Создан: {format_datetime(workspace.created_at)}",
            ]
        )

    async def invite_user_placeholder(self, context: BotContext) -> str:
        require_manage_access(context)
        return (
            "Инвайты ещё не включены. Доступ к проекту сейчас выдаётся только через "
            "явное добавление участника администратором."
        )

    async def list_members(self, context: BotContext) -> str:
        rows = (
            await self.session.execute(
                select(User, WorkspaceMember)
                .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
                .where(WorkspaceMember.workspace_id == context.workspace_id)
                .order_by(WorkspaceMember.role.asc(), User.display_name.asc())
            )
        ).all()
        if not rows:
            return "У проекта пока нет участников."
        return "Участники проекта\n" + "\n".join(
            f"{index}. {user.display_name} — {member.role}"
            for index, (user, member) in enumerate(rows, start=1)
        )

    async def set_member_role(
        self,
        context: BotContext,
        telegram_user_id: int,
        role: str,
    ) -> str:
        require_manage_access(context)
        normalized = role.strip().lower()
        if normalized not in {"owner", "admin", "member", "viewer"}:
            return "Роль должна быть owner, admin, member или viewer."
        user = (
            await self.session.scalars(
                select(User).where(User.telegram_user_id == telegram_user_id)
            )
        ).first()
        if user is None:
            return "Этот пользователь ещё не делал /setup в проекте."
        member = await self._ensure_membership(context.workspace_id, user.id, role=normalized)
        member.role = normalized
        self.session.add(
            AuditLog(
                organization_id=context.organization_id,
                workspace_id=context.workspace_id,
                actor_user_id=context.user_id,
                action="member.role_updated",
                resource_type="user",
                resource_id=user.id,
                metadata_json={"role": normalized},
            )
        )
        await self.session.commit()
        return f"Роль обновлена.\n{user.display_name}: {normalized}"

    async def digest(self, context: BotContext, days: int) -> str:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        meetings_count = await self._count_since(Meeting, context.workspace_id, since)
        documents_count = await self._count_since(Document, context.workspace_id, since)
        tasks = (
            await self.session.scalars(
                select(Task)
                .where(Task.workspace_id == context.workspace_id, Task.created_at >= since)
                .order_by(Task.created_at.desc())
                .limit(8)
            )
        ).all()
        decisions = (
            await self.session.scalars(
                select(Decision)
                .where(Decision.workspace_id == context.workspace_id, Decision.created_at >= since)
                .order_by(Decision.created_at.desc())
                .limit(8)
            )
        ).all()
        risks = (
            await self.session.scalars(
                select(Risk)
                .where(Risk.workspace_id == context.workspace_id, Risk.created_at >= since)
                .order_by(Risk.created_at.desc())
                .limit(8)
            )
        ).all()
        title = "Дайджест за сегодня" if days == 1 else f"Дайджест за {days} дней"
        return "\n\n".join(
            [
                title,
                f"Встречи: {meetings_count}\nДокументы: {documents_count}",
                format_compact_rows("Новые задачи", [task.title for task in tasks]),
                format_compact_rows("Новые решения", [decision.title for decision in decisions]),
                format_compact_rows("Риски", [risk.title for risk in risks]),
            ]
        )

    async def attention(self, context: BotContext) -> str:
        now = datetime.now(timezone.utc)
        overdue = (
            await self.session.scalars(
                select(Task)
                .where(
                    Task.workspace_id == context.workspace_id,
                    Task.status != "done",
                    Task.due_at.is_not(None),
                    Task.due_at < now,
                )
                .order_by(Task.due_at.asc())
                .limit(8)
            )
        ).all()
        blocked = (
            await self.session.scalars(
                select(Task)
                .where(Task.workspace_id == context.workspace_id, Task.status == "blocked")
                .order_by(Task.created_at.desc())
                .limit(8)
            )
        ).all()
        risks = (
            await self.session.scalars(
                select(Risk)
                .where(Risk.workspace_id == context.workspace_id)
                .order_by(Risk.created_at.desc())
                .limit(8)
            )
        ).all()
        if not overdue and not blocked and not risks:
            return "Сейчас нет явных блокеров, просроченных задач или открытых рисков."
        return "\n\n".join(
            [
                "Что требует внимания",
                format_compact_rows("Просроченные задачи", [task.title for task in overdue]),
                format_compact_rows("Заблокированные задачи", [task.title for task in blocked]),
                format_compact_rows("Открытые риски", [risk.title for risk in risks]),
            ]
        )

    async def topics(self, context: BotContext) -> str:
        rows = (
            await self.session.scalars(
                select(MemoryChunk.source_title)
                .where(MemoryChunk.workspace_id == context.workspace_id)
                .order_by(MemoryChunk.created_at.desc())
                .limit(40)
            )
        ).all()
        titles = []
        for row in rows:
            title = row.strip()
            if title and title not in titles:
                titles.append(title)
        if not titles:
            return "Тем пока нет. Добавь встречу, документ или сообщения."
        return "Темы в памяти\n" + "\n".join(
            f"{index}. {title}" for index, title in enumerate(titles[:12], start=1)
        )

    async def topic_detail(self, context: BotContext, query: str) -> str:
        cleaned = query.strip()
        if not cleaned:
            return "Напиши тему: /topic Acciolytix"
        pattern = f"%{cleaned}%"
        chunks = (
            await self.session.scalars(
                select(MemoryChunk)
                .where(
                    MemoryChunk.workspace_id == context.workspace_id,
                    or_(
                        MemoryChunk.source_title.ilike(pattern),
                        MemoryChunk.content.ilike(pattern),
                    ),
                )
                .order_by(MemoryChunk.created_at.desc())
                .limit(6)
            )
        ).all()
        if not chunks:
            return "Не нашёл эту тему в памяти проекта."
        return f"Тема: {cleaned}\n" + "\n\n".join(
            f"{index}. {format_source_type(chunk.source_type)} — {chunk.source_title}\n"
            f"{chunk.content[:420]}"
            for index, chunk in enumerate(chunks, start=1)
        )

    async def people(self, context: BotContext) -> str:
        return await self.list_members(context)

    async def person(self, context: BotContext, name: str) -> str:
        cleaned = name.strip()
        if not cleaned:
            return "Напиши имя: /person Иван"
        member_row = (
            await self.session.execute(
                select(User, WorkspaceMember)
                .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
                .where(
                    WorkspaceMember.workspace_id == context.workspace_id,
                    User.display_name.ilike(f"%{cleaned}%"),
                )
            )
        ).first()
        tasks = (
            await self.session.scalars(
                select(Task)
                .where(
                    Task.workspace_id == context.workspace_id,
                    or_(
                        Task.description.ilike(f"%Owner: {cleaned}%"),
                        Task.description.ilike(f"%Ответственный: {cleaned}%"),
                        Task.title.ilike(f"%{cleaned}%"),
                    ),
                )
                .order_by(Task.created_at.desc())
                .limit(8)
            )
        ).all()
        if member_row is None and not tasks:
            return "Не нашёл человека или задачи по этому имени."
        lines = [f"Профиль: {cleaned}"]
        if member_row is not None:
            user, member = member_row
            lines.append(f"Участник: {user.display_name}\nРоль: {member.role}")
        lines.append(format_compact_rows("Связанные задачи", [task.title for task in tasks]))
        return "\n\n".join(lines)

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

    async def _active_chat_for_telegram_chat(
        self,
        telegram_chat_id: int,
        user_id: UUID,
        chat_type: str = "private",
    ) -> TelegramChat | None:
        conditions = [
            TelegramChat.telegram_chat_id == telegram_chat_id,
            TelegramChat.is_active.is_(True),
        ]
        if is_group_chat_type(chat_type):
            conditions.append(TelegramChat.selected_by_user_id.is_(None))
        else:
            conditions.append(TelegramChat.selected_by_user_id == user_id)
        return (
            await self.session.scalars(
                select(TelegramChat)
                .where(*conditions)
                .order_by(TelegramChat.is_active.desc())
            )
        ).first()

    async def _deactivate_chat_projects(
        self,
        telegram_chat_id: int,
        user_id: UUID,
        chat_type: str = "private",
    ) -> None:
        conditions = [TelegramChat.telegram_chat_id == telegram_chat_id]
        if is_group_chat_type(chat_type):
            conditions.append(TelegramChat.selected_by_user_id.is_(None))
        else:
            conditions.append(TelegramChat.selected_by_user_id == user_id)
        chats = (
            await self.session.scalars(
                select(TelegramChat).where(*conditions)
            )
        ).all()
        for chat in chats:
            chat.is_active = False

    async def _projects_for_user(
        self,
        user_id: UUID,
    ) -> list[tuple[Workspace, WorkspaceMember]]:
        return list(
            (
                await self.session.execute(
                    select(Workspace, WorkspaceMember)
                    .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
                    .where(
                        WorkspaceMember.user_id == user_id,
                        Workspace.status == "active",
                    )
                    .order_by(Workspace.created_at.asc(), Workspace.name.asc())
                )
            ).all()
        )

    async def _require_group_project_manager(
        self,
        user: User,
        telegram_chat_id: int,
    ) -> None:
        active_chat = (
            await self.session.scalars(
                select(TelegramChat).where(
                    TelegramChat.telegram_chat_id == telegram_chat_id,
                    TelegramChat.selected_by_user_id.is_(None),
                    TelegramChat.is_active.is_(True),
                )
            )
        ).first()
        if active_chat is None:
            return
        member = (
            await self.session.scalars(
                select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == active_chat.workspace_id,
                    WorkspaceMember.user_id == user.id,
                )
            )
        ).first()
        if member is None or member.role not in MANAGE_ROLES:
            raise PermissionError(
                "Создать или сменить проект в уже привязанной группе может только owner "
                "или admin текущего проекта."
            )

    async def _create_project_for_user(
        self,
        organization: Organization,
        user: User,
        name: str,
        telegram_chat_id: int,
        chat_title: str | None,
        chat_type: str,
        audit_source: str,
    ) -> BotContext:
        cleaned = name.strip()
        if not cleaned:
            cleaned = build_workspace_name(telegram_chat_id, chat_title)
        workspace = Workspace(
            organization_id=organization.id,
            name=cleaned[:160],
            created_by_user_id=user.id,
            status="active",
        )
        self.session.add(workspace)
        await self.session.flush()
        member = WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner")
        self.session.add(member)
        await self.session.flush()
        await self._select_workspace_for_chat(
            workspace,
            user,
            telegram_chat_id,
            chat_title,
            chat_type,
            member.role,
            action="telegram.setup" if audit_source == "telegram_setup" else "workspace.created",
        )
        self.session.add(
            AuditLog(
                organization_id=organization.id,
                workspace_id=workspace.id,
                actor_user_id=user.id,
                action="workspace.created",
                resource_type="workspace",
                resource_id=workspace.id,
                metadata_json={"source": audit_source, "telegram_chat_id": telegram_chat_id},
            )
        )
        await self.session.commit()
        return BotContext(
            organization.id,
            workspace.id,
            user.id,
            member.role,
            workspace.name,
            telegram_chat_id,
            chat_type,
        )

    async def _select_workspace_for_chat(
        self,
        workspace: Workspace,
        user: User,
        telegram_chat_id: int,
        chat_title: str | None,
        chat_type: str,
        role: str,
        action: str,
    ) -> TelegramChat:
        await self._deactivate_chat_projects(telegram_chat_id, user.id, chat_type)
        selected_by_user_id = None if is_group_chat_type(chat_type) else user.id
        chat = (
            await self.session.scalars(
                select(TelegramChat).where(
                    TelegramChat.workspace_id == workspace.id,
                    TelegramChat.telegram_chat_id == telegram_chat_id,
                    TelegramChat.selected_by_user_id == selected_by_user_id,
                )
            )
        ).first()
        if chat is None:
            chat = TelegramChat(
                workspace_id=workspace.id,
                telegram_chat_id=telegram_chat_id,
                selected_by_user_id=selected_by_user_id,
                chat_type=normalize_chat_type(chat_type),
                title=chat_title,
                is_active=True,
            )
            self.session.add(chat)
            await self.session.flush()
        else:
            chat.title = chat_title or chat.title
            chat.chat_type = normalize_chat_type(chat_type)
            chat.is_active = True
        self.session.add(
            AuditLog(
                organization_id=workspace.organization_id,
                workspace_id=workspace.id,
                actor_user_id=user.id,
                action=action,
                resource_type="telegram_chat",
                resource_id=chat.id,
                metadata_json={
                    "telegram_chat_id": telegram_chat_id,
                    "chat_type": normalize_chat_type(chat_type),
                    "role": role,
                },
            )
        )
        return chat

    async def _ordered_tasks(self, context: BotContext) -> list[Task]:
        return list(
            (
                await self.session.scalars(
                    select(Task)
                    .where(Task.workspace_id == context.workspace_id)
                    .order_by(Task.created_at.desc())
                )
            ).all()
        )

    async def _ordered_decisions(self, context: BotContext) -> list[Decision]:
        return list(
            (
                await self.session.scalars(
                    select(Decision)
                    .where(Decision.workspace_id == context.workspace_id)
                    .order_by(Decision.created_at.desc())
                )
            ).all()
        )

    async def _count_since(self, model, workspace_id: UUID, since: datetime) -> int:
        return int(
            (
                await self.session.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(model.workspace_id == workspace_id, model.created_at >= since)
                )
            )
            or 0
        )

    async def _ensure_membership(
        self,
        workspace_id: UUID,
        user_id: UUID,
        role: str = "member",
    ) -> WorkspaceMember:
        member = (
            await self.session.scalars(
                select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.user_id == user_id,
                )
            )
        ).first()
        if member is None:
            member = WorkspaceMember(workspace_id=workspace_id, user_id=user_id, role=role)
            self.session.add(member)
            await self.session.flush()
        return member

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


def require_write_access(context: BotContext) -> None:
    if context.role not in WRITE_ROLES:
        raise PermissionError("В этой роли можно читать память, но нельзя изменять проект.")


def require_manage_access(context: BotContext) -> None:
    if context.role not in MANAGE_ROLES:
        raise PermissionError("Управлять проектами и ролями могут только owner или admin.")


def is_group_chat_type(chat_type: str) -> bool:
    return chat_type in {"group", "supergroup"}


def normalize_chat_type(chat_type: str) -> str:
    return "group" if is_group_chat_type(chat_type) else "private"


def select_project_row(
    rows: list[tuple[Workspace, WorkspaceMember]],
    selector: str,
) -> tuple[Workspace, WorkspaceMember] | None:
    cleaned = selector.strip()
    if not cleaned:
        return None
    if cleaned.isdigit():
        index = int(cleaned)
        if 1 <= index <= len(rows):
            return rows[index - 1]
    lowered = cleaned.lower()
    return next(
        (
            row
            for row in rows
            if str(row[0].id) == cleaned
            or row[0].name.lower() == lowered
            or lowered in row[0].name.lower()
        ),
        None,
    )


def format_compact_rows(title: str, rows: list[str]) -> str:
    if not rows:
        return f"{title}: нет"
    return title + "\n" + "\n".join(f"{index}. {row}" for index, row in enumerate(rows, start=1))


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
            f"   Ответственный: {item.assignee or 'не указан'}\n"
            f"   Срок: {item.deadline or 'не указан'}\n"
            f"   Приоритет: {item.priority or 'не указан'}"
            for index, item in enumerate(extraction.tasks, start=1)
        )
        or "Задачи не найдены."
    )
    decisions = (
        "\n".join(
            f"{index}. {item.title}" for index, item in enumerate(extraction.decisions, start=1)
        )
        or "Решения не найдены."
    )
    risks = (
        "\n".join(
            f"{index}. {item.title} ({item.severity})"
            for index, item in enumerate(extraction.risks, start=1)
        )
        or "Риски не найдены."
    )
    return (
        f"Итоги встречи\n\n{extraction.summary}\n\n"
        f"Задачи\n{tasks}\n\n"
        f"Решения\n{decisions}\n\n"
        f"Риски\n{risks}\n\n"
        f"Следующие шаги\n{extraction.follow_up or 'Не указаны.'}"
    )


def format_answer(answer: str, sources: list[MemorySource]) -> str:
    source_lines = "\n".join(
        f"{index}. {format_source_type(source.source_type)} — {source.source_title}"
        for index, source in enumerate(sources, start=1)
    )
    return f"Ответ:\n{answer}\n\nИсточники:\n{source_lines}"


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
    if isinstance(exc, PermissionError):
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
