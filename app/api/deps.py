from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_service_api_key
from app.db.session import get_db_session

DBSession = Annotated[AsyncSession, Depends(get_db_session)]
ServiceAuth = Annotated[str, Depends(require_service_api_key)]


def request_locale(request: Request) -> str:
    return getattr(request.state, "locale", "en")


RequestLocale = Annotated[str, Depends(request_locale)]
