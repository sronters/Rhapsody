from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AIRequest, AuditLog, MemoryChunk, Message, Task

OPEN_TASK_STATUSES = frozenset({"open", "in_progress", "blocked"})


@dataclass(frozen=True)
class TaskReminderCandidate:
    task_id: UUID
    workspace_id: UUID
    title: str
    due_at: datetime
    status: str
    hours_until_due: float


@dataclass(frozen=True)
class RetentionSweepResult:
    memory_chunks_deleted: int
    messages_deleted: int
    ai_requests_deleted: int
    audit_logs_deleted: int


async def find_task_reminder_candidates(
    session: AsyncSession,
    now: datetime | None = None,
    lookahead: timedelta = timedelta(hours=24),
) -> list[TaskReminderCandidate]:
    reference_time = normalize_utc(now or datetime.now(timezone.utc))
    due_before = reference_time + lookahead
    tasks = (
        await session.scalars(
            select(Task)
            .where(
                Task.due_at.is_not(None),
                Task.due_at >= reference_time,
                Task.due_at <= due_before,
                Task.status.in_(OPEN_TASK_STATUSES),
            )
            .order_by(Task.due_at.asc())
        )
    ).all()
    return [build_task_reminder_candidate(task, reference_time) for task in tasks]


async def sweep_workspace_retention(
    session: AsyncSession,
    workspace_id: UUID,
    older_than: datetime,
) -> RetentionSweepResult:
    cutoff = normalize_utc(older_than)
    memory_deleted = await execute_delete(
        session,
        delete(MemoryChunk).where(
            MemoryChunk.workspace_id == workspace_id,
            MemoryChunk.created_at < cutoff,
        ),
    )
    messages_deleted = await execute_delete(
        session,
        delete(Message).where(Message.workspace_id == workspace_id, Message.created_at < cutoff),
    )
    ai_requests_deleted = await execute_delete(
        session,
        delete(AIRequest).where(
            AIRequest.workspace_id == workspace_id,
            AIRequest.created_at < cutoff,
        ),
    )
    audit_logs_deleted = await execute_delete(
        session,
        delete(AuditLog).where(
            AuditLog.workspace_id == workspace_id,
            AuditLog.created_at < cutoff,
        ),
    )
    await session.commit()
    return RetentionSweepResult(
        memory_chunks_deleted=memory_deleted,
        messages_deleted=messages_deleted,
        ai_requests_deleted=ai_requests_deleted,
        audit_logs_deleted=audit_logs_deleted,
    )


def build_task_reminder_candidate(task: Task, now: datetime) -> TaskReminderCandidate:
    if task.due_at is None:
        raise ValueError("Task must have a due date to become a reminder candidate.")
    reference_time = normalize_utc(now)
    due_at = normalize_utc(task.due_at)
    return TaskReminderCandidate(
        task_id=task.id,
        workspace_id=task.workspace_id,
        title=task.title,
        due_at=due_at,
        status=task.status,
        hours_until_due=round((due_at - reference_time).total_seconds() / 3600, 2),
    )


def normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def execute_delete(session: AsyncSession, statement: object) -> int:
    result = await session.execute(statement)
    return int(result.rowcount or 0)
