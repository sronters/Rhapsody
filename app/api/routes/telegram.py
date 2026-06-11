from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status

from app.api.deps import DBSession, ServiceAuth
from app.core.config import get_settings
from app.schemas.telegram import TelegramEvent, TelegramEventAccepted
from app.services.telegram import (
    TelegramIngestService,
    TelegramWebhookVerificationError,
    verify_telegram_webhook_secret,
)

router = APIRouter()


@router.post("/events", response_model=TelegramEventAccepted, status_code=status.HTTP_202_ACCEPTED)
async def ingest_telegram_event(
    payload: TelegramEvent,
    session: DBSession,
    _: ServiceAuth,
    x_telegram_bot_api_secret_token: Annotated[str | None, Header()] = None,
) -> TelegramEventAccepted:
    try:
        verify_telegram_webhook_secret(
            get_settings().telegram_webhook_secret,
            x_telegram_bot_api_secret_token,
        )
    except TelegramWebhookVerificationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    service = TelegramIngestService(session)
    event_id = await service.ingest(payload)
    return TelegramEventAccepted(event_id=event_id, status="accepted")
