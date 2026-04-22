from __future__ import annotations

import logging
import time

from app.core.config import get_settings
from app.db import SessionLocal, init_db
from app.services.youtube import YouTubeService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gtu-ai-worker")


def main() -> None:
    settings = get_settings()
    init_db()
    logger.info("YouTube worker started.")
    while True:
        with SessionLocal() as db:
            service = YouTubeService(db)
            processed = service.poll_active_streams()
            if processed:
                logger.info("Processed %s live chat messages.", processed)
        time.sleep(settings.youtube_poll_interval_seconds)


if __name__ == "__main__":
    main()
