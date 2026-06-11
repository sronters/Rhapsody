from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import DBSession
from app.core.config import get_settings

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "mode": get_settings().deployment_mode}


@router.get("/ready")
async def ready(session: DBSession) -> dict[str, str]:
    await session.execute(text("SELECT 1"))
    return {"status": "ready"}
