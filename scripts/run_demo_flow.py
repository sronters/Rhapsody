from __future__ import annotations

import sys
from typing import Any

import httpx

API_BASE_URL = "http://localhost:8000"
HEADERS = {"X-API-Key": "local-dev-key", "Content-Type": "application/json"}


def request(
    client: httpx.Client,
    method: str,
    path: str,
    **kwargs: Any,
) -> dict[str, Any] | list[dict[str, Any]]:
    response = client.request(method, path, headers=HEADERS, **kwargs)
    response.raise_for_status()
    if response.status_code == 204:
        return {}
    return response.json()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    with httpx.Client(base_url=API_BASE_URL, timeout=20.0) as client:
        health = client.get("/api/v1/health")
        health.raise_for_status()

        organization = request(
            client,
            "POST",
            "/api/v1/workspaces/organizations",
            json={
                "name": "Demo Org",
                "deployment_mode": "cloud",
                "retention_mode": "standard",
            },
        )
        organization_id = organization["id"]
        print("Organization created")

        workspace = request(
            client,
            "POST",
            "/api/v1/workspaces",
            json={"organization_id": organization_id, "name": "Demo Workspace"},
        )
        workspace_id = workspace["id"]
        print("Workspace created")

        user = request(
            client,
            "POST",
            "/api/v1/workspaces/users",
            json={"display_name": "Demo Admin", "email": "admin@example.com"},
        )
        user_id = user["id"]
        print("User created")

        member = request(
            client,
            "POST",
            f"/api/v1/workspaces/{workspace_id}/members",
            json={"user_id": user_id, "role": "admin"},
        )
        require(member["role"] == "admin", "Workspace member was not created as admin")
        print("Member added")

        transcript = (
            "We decided to launch the beta next Friday. "
            "I will prepare the launch checklist. "
            "The main risk is blocked vendor approval. "
            "We agreed to choose Supplier X because it met compliance and delivery needs."
        )
        meeting = request(
            client,
            "POST",
            "/api/v1/meetings/ingest",
            json={
                "workspace_id": workspace_id,
                "title": "Launch planning",
                "source": "upload",
                "transcript_text": transcript,
            },
        )
        require(meeting["status"] == "processed", "Meeting transcript was not processed")
        print("Meeting ingested")

        audit_logs = request(
            client,
            "GET",
            "/api/v1/audit",
            params={"workspace_id": workspace_id, "actor_user_id": user_id},
        )
        actions = {entry["action"] for entry in audit_logs}
        require("meeting.ingested" in actions, "Meeting audit log was not persisted")
        print("Summary persisted")

        tasks = request(
            client,
            "GET",
            "/api/v1/tasks",
            params={"workspace_id": workspace_id, "actor_user_id": user_id},
        )
        require(any("checklist" in task["title"].lower() for task in tasks), "No task persisted")
        print("Tasks persisted")

        decisions = request(
            client,
            "GET",
            "/api/v1/decisions",
            params={"workspace_id": workspace_id, "actor_user_id": user_id},
        )
        require(decisions, "No decision persisted")
        print("Decisions persisted")

        memory_from_meeting = request(
            client,
            "POST",
            "/api/v1/memory/ask",
            params={"actor_user_id": user_id},
            json={
                "workspace_id": workspace_id,
                "question": "What risks did we identify?",
                "top_k": 5,
            },
        )
        require(memory_from_meeting["sources"], "Meeting/risk memory sources were not persisted")
        print("Risks persisted")

        document = request(
            client,
            "POST",
            "/api/v1/documents/ingest",
            params={"actor_user_id": user_id},
            json={
                "workspace_id": workspace_id,
                "name": "Supplier Notes",
                "content_type": "text/plain",
                "storage_key": f"workspaces/{workspace_id}/documents/supplier-notes.txt",
                "extracted_text": (
                    "Supplier X was selected because it met compliance and delivery needs. "
                    "The supplier can support the beta launch next Friday."
                ),
            },
        )
        require(document["chunks_created"] >= 1, "Document did not create memory chunks")
        print("Document ingested")

        memory_answer = request(
            client,
            "POST",
            "/api/v1/memory/ask",
            params={"actor_user_id": user_id},
            json={
                "workspace_id": workspace_id,
                "question": "Why did we choose Supplier X?",
                "top_k": 5,
            },
        )
        require(memory_answer["sources"], "Memory answer did not include sources")
        print("Memory answer returned with sources")

        require(tasks, "Task list is empty")
        print("Tasks listed")

        require(decisions, "Decision list is empty")
        print("Decisions listed")

        audit_logs = request(
            client,
            "GET",
            "/api/v1/audit",
            params={"workspace_id": workspace_id, "actor_user_id": user_id},
        )
        audit_actions = {entry["action"] for entry in audit_logs}
        require("document.ingested" in audit_actions, "Document audit log was not persisted")
        print("Audit logs listed")

    print("DEMO FLOW PASSED")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"DEMO FLOW FAILED: {exc}", file=sys.stderr)
        raise