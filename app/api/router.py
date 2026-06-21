from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import (
    audit,
    calls,
    decisions,
    documents,
    files,
    health,
    meetings,
    memory,
    provider_keys,
    tasks,
    telegram,
    workspaces,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(workspaces.router, prefix="/workspaces", tags=["workspaces"])
api_router.include_router(meetings.router, prefix="/meetings", tags=["meetings"])
api_router.include_router(documents.router, prefix="/documents", tags=["documents"])
api_router.include_router(files.router, prefix="/files", tags=["files"])
api_router.include_router(memory.router, prefix="/memory", tags=["memory"])
api_router.include_router(provider_keys.router, prefix="/provider-keys", tags=["provider-keys"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
api_router.include_router(decisions.router, prefix="/decisions", tags=["decisions"])
api_router.include_router(audit.router, prefix="/audit", tags=["audit"])
api_router.include_router(telegram.router, prefix="/telegram", tags=["telegram"])
api_router.include_router(calls.router, prefix="/calls", tags=["calls"])
