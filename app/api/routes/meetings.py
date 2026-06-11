from __future__ import annotations

from fastapi import APIRouter, status

from app.api.deps import DBSession, ServiceAuth
from app.schemas.meetings import MeetingIngestRequest, MeetingIngestResponse
from app.services.meetings import MeetingService

router = APIRouter()


@router.post("/ingest", response_model=MeetingIngestResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest_meeting(
    payload: MeetingIngestRequest, session: DBSession, _: ServiceAuth
) -> MeetingIngestResponse:
    service = MeetingService(session)
    meeting = await service.enqueue_ingestion(payload)
    return MeetingIngestResponse(meeting_id=meeting.id, status=meeting.status)
