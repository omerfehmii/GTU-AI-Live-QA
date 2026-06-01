from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import AppSetting
from app.schemas import AdminSettingsRead, AdminSettingsUpdate


class RuntimeSettingsService:
    TTS_ENABLED_KEY = "tts_enabled"

    def __init__(self, db: Session, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()

    def read(self) -> AdminSettingsRead:
        return AdminSettingsRead(
            tts_enabled=self.tts_enabled(),
            tts_provider=self.settings.tts_provider,
            tts_model=self.settings.tts_model,
            tts_voice=self.settings.tts_voice,
        )

    def update(self, payload: AdminSettingsUpdate) -> AdminSettingsRead:
        if payload.tts_enabled is not None:
            self._set_value(self.TTS_ENABLED_KEY, self._serialize_bool(payload.tts_enabled))
        self.db.commit()
        return self.read()

    def tts_enabled(self) -> bool:
        stored_value = self._get_value(self.TTS_ENABLED_KEY)
        if stored_value is None:
            return self.settings.tts_enabled
        return stored_value == "true"

    def _get_value(self, key: str) -> str | None:
        row = self.db.get(AppSetting, key)
        return row.value if row else None

    def _set_value(self, key: str, value: str) -> None:
        row = self.db.get(AppSetting, key)
        if row:
            row.value = value
            return
        self.db.add(AppSetting(key=key, value=value))

    def _serialize_bool(self, value: bool) -> str:
        return "true" if value else "false"
