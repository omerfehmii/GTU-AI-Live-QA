from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from openai import OpenAI

from app.core.config import Settings, get_settings
from app.models import Answer
from app.services.provider_client import create_openai_compatible_client
from app.services.runtime_settings import RuntimeSettingsService

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class TTSService:
    def __init__(
        self,
        settings: Settings | None = None,
        client: OpenAI | None = None,
        db: "Session | None" = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.db = db
        self.client = client
        if self.tts_enabled() and self.client is None:
            self.client = create_openai_compatible_client(self.settings, provider=self.settings.tts_provider)

    def synthesize_answer(self, answer: Answer) -> None:
        speech_text = self._answer_speech_text(answer)
        if not self.tts_enabled() or self.client is None or not speech_text:
            return

        output_path = self._output_path(answer.id)
        try:
            duration_ms = self.synthesize_text_to_path(speech_text, output_path)
            answer.audio_url = f"/media/answers/{output_path.name}"
            answer.audio_duration_ms = duration_ms or self.estimate_duration_ms(speech_text)
            answer.audio_model_name = self.settings.tts_model
            answer.audio_error_message = None
        except Exception as exc:
            answer.audio_model_name = self.settings.tts_model
            answer.audio_error_message = str(exc)[:1000]

    def synthesize_text_to_path(self, text: str, output_path: Path) -> int | None:
        if not self.tts_enabled() or self.client is None or not text.strip():
            return None

        output_path.parent.mkdir(parents=True, exist_ok=True)
        response = self.client.audio.speech.create(
            model=self.settings.tts_model,
            input=text[:4096],
            voice=self.settings.tts_voice,
            instructions=self.settings.tts_instructions,
            response_format=self.settings.tts_response_format,
            timeout=self.settings.llm_timeout_seconds,
        )
        self._write_response(response, output_path)
        return self.audio_duration_ms(output_path) or self.estimate_duration_ms(text)

    def _output_path(self, answer_id: str) -> Path:
        output_dir = self.settings.generated_audio_path / "answers"
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir / f"{answer_id}.{self.settings.tts_response_format}"

    def _answer_speech_text(self, answer: Answer) -> str:
        return (answer.speech_content or answer.content).strip()

    def tts_enabled(self) -> bool:
        if self.db is None:
            return self.settings.tts_enabled
        return RuntimeSettingsService(self.db, self.settings).tts_enabled()

    def _write_response(self, response: object, output_path: Path) -> None:
        if hasattr(response, "write_to_file"):
            response.write_to_file(output_path)
            return

        content = getattr(response, "content", None)
        if content is None and hasattr(response, "read"):
            content = response.read()
        if not content:
            raise ValueError("TTS response did not include audio bytes.")
        output_path.write_bytes(content)

    def audio_duration_ms(self, output_path: Path) -> int | None:
        if self.settings.tts_response_format != "mp3":
            return None

        try:
            data = output_path.read_bytes()
        except OSError:
            return None

        duration_seconds = self._mp3_duration_seconds(data)
        if duration_seconds <= 0:
            return None
        return int(duration_seconds * 1000)

    def estimate_duration_ms(self, text: str) -> int:
        words = re.findall(r"\w+", text, re.UNICODE)
        sentence_breaks = len(re.findall(r"[.!?;:]\s+", text))
        estimated_ms = (len(words) * 520) + (sentence_breaks * 280)
        return min(max(int(estimated_ms), 3500), 45000)

    def _mp3_duration_seconds(self, data: bytes) -> float:
        offset = 0
        if data.startswith(b"ID3") and len(data) >= 10:
            offset = 10 + self._synchsafe_int(data[6:10])

        duration = 0.0
        index = offset
        frame_count = 0
        while index + 4 <= len(data):
            header = data[index : index + 4]
            frame = self._read_mp3_frame(header)
            if frame is None:
                index += 1
                continue

            frame_length, samples_per_frame, sample_rate = frame
            if frame_length <= 0:
                index += 1
                continue

            duration += samples_per_frame / sample_rate
            frame_count += 1
            index += frame_length

        return duration if frame_count else 0.0

    def _read_mp3_frame(self, header: bytes) -> tuple[int, int, int] | None:
        if len(header) < 4 or header[0] != 0xFF or (header[1] & 0xE0) != 0xE0:
            return None

        version_bits = (header[1] >> 3) & 0x03
        layer_bits = (header[1] >> 1) & 0x03
        bitrate_index = (header[2] >> 4) & 0x0F
        sample_rate_index = (header[2] >> 2) & 0x03
        padding = (header[2] >> 1) & 0x01

        if version_bits == 1 or layer_bits == 0 or bitrate_index in (0, 15) or sample_rate_index == 3:
            return None

        version = {0: "2.5", 2: "2", 3: "1"}[version_bits]
        layer = {1: "3", 2: "2", 3: "1"}[layer_bits]
        sample_rate = self._sample_rate(version, sample_rate_index)
        bitrate = self._bitrate_kbps(version, layer, bitrate_index)
        if sample_rate <= 0 or bitrate <= 0:
            return None

        if layer == "1":
            frame_length = int(((12 * bitrate * 1000) / sample_rate + padding) * 4)
            samples_per_frame = 384
        elif layer == "3" and version != "1":
            frame_length = int((72 * bitrate * 1000) / sample_rate + padding)
            samples_per_frame = 576
        else:
            frame_length = int((144 * bitrate * 1000) / sample_rate + padding)
            samples_per_frame = 1152
        return frame_length, samples_per_frame, sample_rate

    def _sample_rate(self, version: str, index: int) -> int:
        rates = {
            "1": [44100, 48000, 32000],
            "2": [22050, 24000, 16000],
            "2.5": [11025, 12000, 8000],
        }
        return rates[version][index]

    def _bitrate_kbps(self, version: str, layer: str, index: int) -> int:
        mpeg1 = {
            "1": [0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448],
            "2": [0, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384],
            "3": [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320],
        }
        mpeg2 = {
            "1": [0, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256],
            "2": [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],
            "3": [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],
        }
        table = mpeg1 if version == "1" else mpeg2
        return table[layer][index]

    def _synchsafe_int(self, value: bytes) -> int:
        total = 0
        for byte in value:
            total = (total << 7) | (byte & 0x7F)
        return total
