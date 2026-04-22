from __future__ import annotations

from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import StreamSession, StreamStatus
from app.services.rag import RagService


YOUTUBE_BASE_URL = "https://www.googleapis.com/youtube/v3"


class YouTubeService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()

    def connect_stream(self, video_id: str) -> StreamSession:
        if not self.settings.youtube_api_key:
            raise ValueError("YOUTUBE_API_KEY tanimli degil.")
        details = self._get_video_details(video_id)
        stream = self.db.scalar(select(StreamSession).where(StreamSession.youtube_video_id == video_id))
        if not stream:
            stream = StreamSession(
                youtube_video_id=video_id,
                live_chat_id=details["live_chat_id"],
                title=details["title"],
                status=StreamStatus.CONNECTED,
            )
            self.db.add(stream)
        else:
            stream.live_chat_id = details["live_chat_id"]
            stream.title = details["title"]
            stream.status = StreamStatus.CONNECTED
            stream.error_message = None
        self.db.commit()
        self.db.refresh(stream)
        return stream

    def poll_active_streams(self) -> int:
        streams = self.db.scalars(select(StreamSession).where(StreamSession.status == StreamStatus.CONNECTED)).all()
        processed = 0
        rag = RagService(self.db)
        for stream in streams:
            try:
                processed += self._poll_stream(stream, rag)
                stream.error_message = None
            except Exception as exc:
                stream.status = StreamStatus.ERROR
                stream.error_message = str(exc)
            stream.last_polled_at = datetime.now(UTC)
        self.db.commit()
        return processed

    def _poll_stream(self, stream: StreamSession, rag: RagService) -> int:
        params = {
            "liveChatId": stream.live_chat_id,
            "part": "snippet,authorDetails",
            "maxResults": 50,
            "key": self.settings.youtube_api_key,
        }
        if stream.next_page_token:
            params["pageToken"] = stream.next_page_token
        with httpx.Client(timeout=20.0) as client:
            response = client.get(f"{YOUTUBE_BASE_URL}/liveChat/messages", params=params)
            response.raise_for_status()
            data = response.json()
        stream.next_page_token = data.get("nextPageToken")
        created = 0
        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            if snippet.get("type") != "textMessageEvent":
                continue
            content = snippet.get("displayMessage", "").strip()
            if not content:
                continue
            rag.upsert_youtube_question(
                content=content,
                author_name=item.get("authorDetails", {}).get("displayName"),
                source_message_id=item["id"],
                stream_session_id=stream.id,
            )
            created += 1
        return created

    def _get_video_details(self, video_id: str) -> dict[str, str]:
        params = {
            "id": video_id,
            "part": "liveStreamingDetails,snippet",
            "key": self.settings.youtube_api_key,
        }
        with httpx.Client(timeout=20.0) as client:
            response = client.get(f"{YOUTUBE_BASE_URL}/videos", params=params)
            response.raise_for_status()
            items = response.json().get("items", [])
        if not items:
            raise ValueError("Video bulunamadi.")
        item = items[0]
        live_chat_id = item.get("liveStreamingDetails", {}).get("activeLiveChatId")
        if not live_chat_id:
            raise ValueError("Bu video icin aktif live chat bulunamadi.")
        return {"live_chat_id": live_chat_id, "title": item.get("snippet", {}).get("title", video_id)}
