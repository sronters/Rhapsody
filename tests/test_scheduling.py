from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import Task
from app.services.scheduling import build_task_reminder_candidate, normalize_utc
from app.workers.tasks import (
    dispatch_due_reminders,
    format_task_reminder,
    sweep_workspace_retention,
)


def test_build_task_reminder_candidate_calculates_hours_until_due() -> None:
    now = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    task = Task(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        title="Send weekly summary",
        status="open",
        due_at=now + timedelta(hours=6, minutes=30),
        source_type="manual",
    )

    candidate = build_task_reminder_candidate(task, now)

    assert candidate.title == "Send weekly summary"
    assert candidate.hours_until_due == 6.5


def test_build_task_reminder_candidate_requires_due_at() -> None:
    task = Task(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        title="No due date",
        status="open",
        source_type="manual",
    )

    with pytest.raises(ValueError):
        build_task_reminder_candidate(task, datetime.now(timezone.utc))


def test_normalize_utc_handles_naive_datetime() -> None:
    assert normalize_utc(datetime(2026, 1, 1, 12)).tzinfo == timezone.utc


def test_worker_task_contracts() -> None:
    assert dispatch_due_reminders()["status"] == "telegram_not_configured"
    assert sweep_workspace_retention("workspace", "2026-01-01T00:00:00Z") == {
        "workspace_id": "workspace",
        "older_than": "2026-01-01T00:00:00Z",
        "status": "queued_for_retention_sweep",
    }


def test_format_task_reminder() -> None:
    message = format_task_reminder("Send weekly summary", 6.5)

    assert "Task reminder" in message
    assert "Send weekly summary" in message
    assert "/task_done" in message
