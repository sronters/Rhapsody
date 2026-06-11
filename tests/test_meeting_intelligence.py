from __future__ import annotations

import uuid

import pytest

from app.db.models import Decision, MeetingSummary, MemoryChunk, Risk, Task, Workspace
from app.schemas.meetings import MeetingIngestRequest
from app.services.meetings import (
    MeetingService,
    extract_meeting_intelligence,
    infer_risk_severity,
    trim_title,
)


class _ScalarResult:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows

    def one(self) -> object:
        return self.rows[0]


class _FakeMeetingSession:
    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace
        self.added: list[object] = []
        self.committed = False

    async def scalars(self, statement: object) -> _ScalarResult:
        return _ScalarResult([self.workspace])

    def add(self, item: object) -> None:
        self.added.append(item)

    async def flush(self) -> None:
        for item in self.added:
            if getattr(item, "id", None) is None:
                item.id = uuid.uuid4()

    async def commit(self) -> None:
        self.committed = True


def test_extract_meeting_intelligence_detects_decisions_tasks_and_risks() -> None:
    result = extract_meeting_intelligence(
        "We decided to choose option B. I will prepare the CRM integration by Friday. "
        "There is a risk that the provider blocks the API."
    )

    assert "decided" in result.decisions[0].lower()
    assert "integration" in result.tasks[0].title.lower()
    assert "risk" in result.risks[0].lower()
    assert result.follow_up


def test_meeting_helpers_are_input_adaptive() -> None:
    assert trim_title("  Decide launch path. ") == "Decide launch path"
    assert infer_risk_severity("blocked by vendor") == "high"
    assert infer_risk_severity("minor concern") == "low"


@pytest.mark.asyncio
async def test_meeting_ingestion_persists_extracted_operational_records() -> None:
    workspace = Workspace(id=uuid.uuid4(), organization_id=uuid.uuid4(), name="Ops")
    session = _FakeMeetingSession(workspace)
    payload = MeetingIngestRequest(
        workspace_id=workspace.id,
        title="Launch planning",
        source="upload",
        transcript_text=(
            "We decided to launch beta. I will prepare checklist. "
            "The main risk is blocked vendor approval."
        ),
    )

    meeting = await MeetingService(session).enqueue_ingestion(payload)  # type: ignore[arg-type]

    assert meeting.status == "processed"
    assert session.committed
    assert any(isinstance(item, MeetingSummary) for item in session.added)
    assert any(isinstance(item, Task) for item in session.added)
    assert any(isinstance(item, Decision) for item in session.added)
    assert any(isinstance(item, Risk) for item in session.added)
    assert any(isinstance(item, MemoryChunk) for item in session.added)
