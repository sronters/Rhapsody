from __future__ import annotations

import asyncio
import logging
import sys

from app.core.config import get_settings
from app.db.session import AsyncSessionFactory
from app.listener.adapters import (
    ListenerConfigurationError,
    collect_listener_diagnostics,
    validate_listener_configuration,
)
from app.listener.service import LiveMeetingListenerService

logger = logging.getLogger(__name__)
POLL_SECONDS = 1


async def main() -> None:
    settings = get_settings()
    validate_listener_configuration(settings)
    diagnostics = await collect_listener_diagnostics(settings)
    print("Rhapsody listener diagnostics:")
    for line in diagnostics.lines():
        print(f"- {line}")
    print(
        "Rhapsody listener service is configured. "
        "Start/stop is controlled through Telegram /listen and /stop_listen commands."
    )
    while True:
        try:
            async with AsyncSessionFactory() as session:
                await LiveMeetingListenerService(session, settings=settings).process_pending_once()
        except Exception:
            logger.exception("Listener polling cycle failed.")
        await asyncio.sleep(POLL_SECONDS)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except ListenerConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
