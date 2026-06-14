from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import AppSetting
from app.schemas import AdminSettingsRead, AdminSettingsUpdate, LiveDisplaySettingsRead, PetVariant


class RuntimeSettingsService:
    TTS_ENABLED_KEY = "tts_enabled"
    LIVE_PET_ENABLED_KEY = "live_pet_enabled"
    LIVE_PET_VARIANT_KEY = "live_pet_variant"
    LIVE_PET_ANIMATION_SECONDS_KEY = "live_pet_animation_seconds"
    LIVE_PET_INTERVAL_SECONDS_KEY = "live_pet_interval_seconds"
    LIVE_PET_SIZE_PX_KEY = "live_pet_size_px"
    AVATAR_BLINK_INTERVAL_SECONDS_KEY = "avatar_blink_interval_seconds"
    AVATAR_BLINK_DURATION_SECONDS_KEY = "avatar_blink_duration_seconds"
    DEFAULT_LIVE_PET_ENABLED = True
    DEFAULT_LIVE_PET_VARIANT: PetVariant = "screen_touch"
    DEFAULT_LIVE_PET_ANIMATION_SECONDS = 6.0
    DEFAULT_LIVE_PET_INTERVAL_SECONDS = 120.0
    DEFAULT_LIVE_PET_SIZE_PX = 100
    DEFAULT_AVATAR_BLINK_INTERVAL_SECONDS = 6.8
    DEFAULT_AVATAR_BLINK_DURATION_SECONDS = 0.22
    PET_VARIANTS: set[PetVariant] = {"screen_touch", "yarn", "box"}

    def __init__(self, db: Session, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()

    def read(self) -> AdminSettingsRead:
        display_settings = self.display_settings()
        return AdminSettingsRead(
            tts_enabled=self.tts_enabled(),
            tts_provider=self.settings.tts_provider,
            tts_model=self.settings.tts_model,
            tts_voice=self.settings.tts_voice,
            live_pet_enabled=display_settings.live_pet_enabled,
            live_pet_variant=display_settings.live_pet_variant,
            live_pet_animation_seconds=display_settings.live_pet_animation_seconds,
            live_pet_interval_seconds=display_settings.live_pet_interval_seconds,
            live_pet_size_px=display_settings.live_pet_size_px,
            avatar_blink_interval_seconds=display_settings.avatar_blink_interval_seconds,
            avatar_blink_duration_seconds=display_settings.avatar_blink_duration_seconds,
        )

    def update(self, payload: AdminSettingsUpdate) -> AdminSettingsRead:
        if payload.tts_enabled is not None:
            self._set_value(self.TTS_ENABLED_KEY, self._serialize_bool(payload.tts_enabled))
        if payload.live_pet_enabled is not None:
            self._set_value(self.LIVE_PET_ENABLED_KEY, self._serialize_bool(payload.live_pet_enabled))
        if payload.live_pet_variant is not None:
            self._set_value(self.LIVE_PET_VARIANT_KEY, payload.live_pet_variant)
        if payload.live_pet_animation_seconds is not None:
            self._set_value(self.LIVE_PET_ANIMATION_SECONDS_KEY, self._serialize_float(payload.live_pet_animation_seconds))
        if payload.live_pet_interval_seconds is not None:
            self._set_value(self.LIVE_PET_INTERVAL_SECONDS_KEY, self._serialize_float(payload.live_pet_interval_seconds))
        if payload.live_pet_size_px is not None:
            self._set_value(self.LIVE_PET_SIZE_PX_KEY, str(payload.live_pet_size_px))
        if payload.avatar_blink_interval_seconds is not None:
            self._set_value(
                self.AVATAR_BLINK_INTERVAL_SECONDS_KEY,
                self._serialize_float(payload.avatar_blink_interval_seconds),
            )
        if payload.avatar_blink_duration_seconds is not None:
            self._set_value(
                self.AVATAR_BLINK_DURATION_SECONDS_KEY,
                self._serialize_float(payload.avatar_blink_duration_seconds),
            )
        self.db.commit()
        return self.read()

    def tts_enabled(self) -> bool:
        stored_value = self._get_value(self.TTS_ENABLED_KEY)
        if stored_value is None:
            return self.settings.tts_enabled
        return stored_value == "true"

    def display_settings(self) -> LiveDisplaySettingsRead:
        return LiveDisplaySettingsRead(
            live_pet_enabled=self._bool_setting(self.LIVE_PET_ENABLED_KEY, self.DEFAULT_LIVE_PET_ENABLED),
            live_pet_variant=self._pet_variant_setting(),
            live_pet_animation_seconds=self._float_setting(
                self.LIVE_PET_ANIMATION_SECONDS_KEY,
                self.DEFAULT_LIVE_PET_ANIMATION_SECONDS,
                minimum=1.5,
                maximum=12.0,
            ),
            live_pet_interval_seconds=self._float_setting(
                self.LIVE_PET_INTERVAL_SECONDS_KEY,
                self.DEFAULT_LIVE_PET_INTERVAL_SECONDS,
                minimum=15.0,
                maximum=300.0,
            ),
            live_pet_size_px=self._int_setting(
                self.LIVE_PET_SIZE_PX_KEY,
                self.DEFAULT_LIVE_PET_SIZE_PX,
                minimum=50,
                maximum=180,
            ),
            avatar_blink_interval_seconds=self._float_setting(
                self.AVATAR_BLINK_INTERVAL_SECONDS_KEY,
                self.DEFAULT_AVATAR_BLINK_INTERVAL_SECONDS,
                minimum=3.0,
                maximum=12.0,
            ),
            avatar_blink_duration_seconds=self._float_setting(
                self.AVATAR_BLINK_DURATION_SECONDS_KEY,
                self.DEFAULT_AVATAR_BLINK_DURATION_SECONDS,
                minimum=0.1,
                maximum=0.5,
            ),
        )

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

    def _serialize_float(self, value: float) -> str:
        return f"{value:.3f}".rstrip("0").rstrip(".")

    def _bool_setting(self, key: str, default: bool) -> bool:
        stored_value = self._get_value(key)
        if stored_value is None:
            return default
        return stored_value == "true"

    def _float_setting(self, key: str, default: float, *, minimum: float, maximum: float) -> float:
        stored_value = self._get_value(key)
        if stored_value is None:
            return default
        try:
            value = float(stored_value)
        except ValueError:
            return default
        return min(max(value, minimum), maximum)

    def _int_setting(self, key: str, default: int, *, minimum: int, maximum: int) -> int:
        stored_value = self._get_value(key)
        if stored_value is None:
            return default
        try:
            value = int(stored_value)
        except ValueError:
            return default
        return min(max(value, minimum), maximum)

    def _pet_variant_setting(self) -> PetVariant:
        stored_value = self._get_value(self.LIVE_PET_VARIANT_KEY)
        if stored_value in self.PET_VARIANTS:
            return stored_value
        return self.DEFAULT_LIVE_PET_VARIANT
