from __future__ import annotations

import logging
import time

from sqlalchemy.exc import OperationalError

from app.core.config import get_settings
from app.db import SessionLocal, init_db
from app.services.rag import RagService
from app.services.youtube import YouTubeService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gtu-ai-worker")


def main() -> None:
    settings = get_settings()
    init_db()
    logger.info("YouTube worker started.")
    while True:
        try:
            with SessionLocal() as db:
                youtube = YouTubeService(db)
                queued = youtube.poll_active_streams()
                answered = RagService(db).process_pending_questions(max_items=1)
                if queued:
                    logger.info("Queued %s live chat messages.", queued)
                if answered:
                    logger.info("Answered %s queued questions.", answered)
        except OperationalError as exc:
            if "database is locked" in str(exc).lower():
                logger.warning("Database is busy; worker will retry on the next tick.")
            else:
                logger.exception("Worker database error.")
        except Exception:
            logger.exception("Worker loop failed; retrying on the next tick.")
        time.sleep(settings.youtube_poll_interval_seconds)


if __name__ == "__main__":
    main()
