from __future__ import annotations

import pytest
import pytest_asyncio
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.db.session as db_session_module
from app.db.models import MeetingSummary, Risk
from app.main import create_app

# ---------------------------------------------------------------------------
# Full end-to-end demo flow integration test.
#
# Requires:
#   RHAPSODY_INTEGRATION_DATABASE_URL=postgresql+asyncpg://rhapsody:rhapsody@localhost:5432/rhapsody
#
# Run with:
#   RHAPSODY_INTEGRATION_DATABASE_URL=postgresql+asyncpg://... \
#     pytest tests/integration/ -v -m integration
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_engine(integration_database_url: str):
    engine = create_async_engine(integration_database_url, pool_pre_ping=True)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_engine, integration_database_url: str):
    integration_engine = create_async_engine(integration_database_url, pool_pre_ping=True)
    integration_session_factory = async_sessionmaker(
        integration_engine, expire_on_commit=False, class_=AsyncSession
    )

    async def _get_integration_session():
        async with integration_session_factory() as session:
            yield session

    fastapi_app = create_app()
    fastapi_app.dependency_overrides[db_session_module.get_db_session] = (
        _get_integration_session
    )

    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    await integration_engine.dispose()


HEADERS = {"X-API-Key": "local-dev-key", "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# The full demo flow — one test, sequential steps
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_local_demo_flow(client: AsyncClient, db_engine) -> None:
    # 1. Create organization
    r = await client.post(
        "/api/v1/workspaces/organizations",
        headers=HEADERS,
        json={
            "name": "Demo Org",
            "deployment_mode": "cloud",
            "retention_mode": "standard",
        },
    )
    assert r.status_code == 201, r.text
    org_id = r.json()["id"]

    # 2. Create workspace
    r = await client.post(
        "/api/v1/workspaces",
        headers=HEADERS,
        json={"organization_id": org_id, "name": "Demo Workspace"},
    )
    assert r.status_code == 201, r.text
    workspace_id = r.json()["id"]

    # 3. Create user
    r = await client.post(
        "/api/v1/workspaces/users",
        headers=HEADERS,
        json={"display_name": "Demo Admin", "email": "admin@example.com"},
    )
    assert r.status_code == 201, r.text
    user_id = r.json()["id"]

    # 4. Add user as admin member of the workspace
    r = await client.post(
        f"/api/v1/workspaces/{workspace_id}/members",
        headers=HEADERS,
        json={"user_id": user_id, "role": "admin"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["role"] == "admin"

    # 5. Ingest meeting transcript
    transcript = (
        "We decided to launch the beta next Friday. "
        "I will prepare the launch checklist. "
        "The main risk is blocked vendor approval. "
        "We agreed to choose Supplier X."
    )
    r = await client.post(
        "/api/v1/meetings/ingest",
        headers=HEADERS,
        json={
            "workspace_id": workspace_id,
            "title": "Launch planning",
            "source": "upload",
            "transcript_text": transcript,
        },
    )
    assert r.status_code == 202, r.text
    meeting_data = r.json()
    assert meeting_data["status"] == "processed"
    meeting_id = meeting_data["meeting_id"]

    async with db_engine.connect() as conn:
        summary_count = await conn.scalar(
            sa.select(sa.func.count())
            .select_from(MeetingSummary)
            .where(MeetingSummary.meeting_id == meeting_id)
        )
        risk_count = await conn.scalar(
            sa.select(sa.func.count()).select_from(Risk).where(Risk.workspace_id == workspace_id)
        )

    assert summary_count == 1, "Expected one meeting summary to be persisted"
    assert risk_count >= 1, "Expected at least one risk extracted from meeting"

    # 6. Verify tasks were persisted (from meeting extraction)
    r = await client.get(
        "/api/v1/tasks",
        headers=HEADERS,
        params={"workspace_id": workspace_id, "actor_user_id": user_id},
    )
    assert r.status_code == 200, r.text
    tasks = r.json()
    assert len(tasks) >= 1, "Expected at least one task extracted from meeting"
    assert any(
        "checklist" in t["title"].lower() or "i will" in t["title"].lower()
        for t in tasks
    )

    # 7. Verify decisions were persisted
    r = await client.get(
        "/api/v1/decisions",
        headers=HEADERS,
        params={"workspace_id": workspace_id, "actor_user_id": user_id},
    )
    assert r.status_code == 200, r.text
    decisions = r.json()
    assert len(decisions) >= 1, "Expected at least one decision extracted from meeting"
    assert any(
        "supplier" in d["title"].lower()
        or "decided" in d["title"].lower()
        or "launch" in d["title"].lower()
        for d in decisions
    )

    # 8. Ingest a document
    r = await client.post(
        "/api/v1/documents/ingest",
        headers=HEADERS,
        params={"actor_user_id": user_id},
        json={
            "workspace_id": workspace_id,
            "name": "Supplier Notes",
            "content_type": "text/plain",
            "storage_key": (
                f"workspaces/{workspace_id}/documents/supplier-notes.txt"
            ),
            "extracted_text": (
                "Supplier X was selected because it met compliance and delivery needs."
            ),
        },
    )
    assert r.status_code == 202, r.text
    doc_data = r.json()
    assert doc_data["chunks_created"] >= 1

    # 9. Ask memory — answer must include sources
    r = await client.post(
        "/api/v1/memory/ask",
        headers=HEADERS,
        params={"actor_user_id": user_id},
        json={
            "workspace_id": workspace_id,
            "question": "Why did we choose Supplier X?",
            "top_k": 5,
        },
    )
    assert r.status_code == 200, r.text
    memory_data = r.json()
    assert "answer" in memory_data
    assert "sources" in memory_data
    assert len(memory_data["sources"]) >= 1, (
        "Memory Q&A must return at least one source"
    )
    source_types = {s["source_type"] for s in memory_data["sources"]}
    assert source_types & {"document", "decision", "meeting"}, (
        f"Expected a document/decision/meeting source, got: {source_types}"
    )

    # 10. List audit logs — must include meeting.ingested and document.ingested
    r = await client.get(
        "/api/v1/audit",
        headers=HEADERS,
        params={"workspace_id": workspace_id, "actor_user_id": user_id},
    )
    assert r.status_code == 200, r.text
    audit_logs = r.json()
    actions = {log["action"] for log in audit_logs}
    assert "meeting.ingested" in actions, (
        f"Expected meeting.ingested in audit, got: {actions}"
    )
    assert "document.ingested" in actions, (
        f"Expected document.ingested in audit, got: {actions}"
    )

    # 11. Verify workspace member list
    r = await client.get(
        f"/api/v1/workspaces/{workspace_id}/members",
        headers=HEADERS,
    )
    assert r.status_code == 200, r.text
    members = r.json()
    assert any(m["user_id"] == user_id for m in members)