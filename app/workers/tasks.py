from __future__ import annotations

import asyncio

from aiogram import Bot
from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import AuditLog, TelegramChat, Workspace
from app.db.session import AsyncSessionFactory
from app.services.scheduling import find_task_reminder_candidates
from app.workers.celery_app import celery_app


@celery_app.task(name="meetings.process_recording")
def process_recording(meeting_id: str) -> dict[str, str]:
    return {"meeting_id": meeting_id, "status": "queued_for_stt"}


@celery_app.task(name="documents.index_document")
def index_document(document_id: str) -> dict[str, str]:
    return {"document_id": document_id, "status": "queued_for_embedding"}


@celery_app.task(name="tasks.dispatch_due_reminders")
def dispatch_due_reminders() -> dict[str, str]:
    return asyncio.run(dispatch_due_reminders_to_telegram())


@celery_app.task(name="retention.sweep_workspace")
def sweep_workspace_retention(workspace_id: str, older_than_iso: str) -> dict[str, str]:
    return {
        "workspace_id": workspace_id,
        "older_than": older_than_iso,
        "status": "queued_for_retention_sweep",
    }


async def dispatch_due_reminders_to_telegram() -> dict[str, str]:
    settings = get_settings()
    if not settings.telegram_bot_token:
        return {
            "status": "telegram_not_configured",
            "reason": "TELEGRAM_BOT_TOKEN is required to dispatch Telegram reminders.",
        }

    sent_count = 0
    async with AsyncSessionFactory() as session:
        candidates = await find_task_reminder_candidates(session)
        if not candidates:
            return {"status": "ok", "sent": "0"}
        bot = Bot(token=settings.telegram_bot_token)
        try:
            for candidate in candidates:
                chats = (
                    await session.scalars(
                        select(TelegramChat).where(
                            TelegramChat.workspace_id == candidate.workspace_id
                        )
                    )
                ).all()
                workspace = (
                    await session.scalars(
                        select(Workspace).where(Workspace.id == candidate.workspace_id)
                    )
                ).one()
                for chat in chats:
                    await bot.send_message(
                        chat.telegram_chat_id,
                        format_task_reminder(candidate.title, candidate.hours_until_due),
                    )
                    sent_count += 1
                session.add(
                    AuditLog(
                        organization_id=workspace.organization_id,
                        workspace_id=candidate.workspace_id,
                        action="task.reminder_dispatched",
                        resource_type="task",
                        resource_id=candidate.task_id,
                        metadata_json={
                            "telegram_chats": len(chats),
                            "hours_until_due": candidate.hours_until_due,
                        },
                    )
                )
            await session.commit()
        finally:
            await bot.session.close()
    return {"status": "ok", "sent": str(sent_count)}


def format_task_reminder(title: str, hours_until_due: float) -> str:
    return (
        "🔔 Task reminder\n"
        f"{title}\n"
        f"Due in about {hours_until_due:g} hours.\n\n"
        "Use /tasks to review work or /task_done to close it."
    )
