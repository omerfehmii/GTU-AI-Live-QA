from __future__ import annotations

from app.core.config import Settings
from app.models import AppSetting
from app.models import Answer
from app.services.tts import TTSService


class FakeSpeechResponse:
    content = b"fake mp3 bytes"


class FakeSpeech:
    def __init__(self) -> None:
        self.payload: dict[str, object] | None = None

    def create(self, **kwargs: object) -> FakeSpeechResponse:
        self.payload = kwargs
        return FakeSpeechResponse()


class FakeClient:
    def __init__(self) -> None:
        self.audio = type("FakeAudio", (), {"speech": FakeSpeech()})()


def test_tts_generates_audio_file_and_answer_metadata(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        generated_audio_dir=str(tmp_path),
        tts_model="openai/gpt-4o-mini-tts-2025-12-15",
        tts_voice="nova",
        tts_response_format="mp3",
    )
    client = FakeClient()
    answer = Answer(
        id="answer-1",
        question_id="question-1",
        content="Merhaba, bu canlı yayın cevabıdır.",
        speech_content="Merhaba, bunu yayında daha doğal okuyorum.",
        model_name="test-model",
    )

    TTSService(settings=settings, client=client).synthesize_answer(answer)

    assert (tmp_path / "answers" / "answer-1.mp3").read_bytes() == b"fake mp3 bytes"
    assert answer.audio_url == "/media/answers/answer-1.mp3"
    assert answer.audio_model_name == "openai/gpt-4o-mini-tts-2025-12-15"
    assert answer.audio_duration_ms is not None
    assert client.audio.speech.payload is not None
    assert client.audio.speech.payload["voice"] == "nova"
    assert client.audio.speech.payload["input"] == "Merhaba, bunu yayında daha doğal okuyorum."


def test_tts_respects_runtime_disable_setting(tmp_path) -> None:
    settings = Settings(_env_file=None, generated_audio_dir=str(tmp_path), tts_enabled=True)
    answer = Answer(
        id="answer-disabled",
        question_id="question-disabled",
        content="Bu cevap seslendirilmemeli.",
        model_name="test-model",
    )

    class FakeDb:
        def get(self, model: object, key: str) -> AppSetting | None:
            if model is AppSetting and key == "tts_enabled":
                return AppSetting(key="tts_enabled", value="false")
            return None

    service = TTSService(settings=settings, client=FakeClient(), db=FakeDb())  # type: ignore[arg-type]
    service.synthesize_answer(answer)

    assert answer.audio_url is None
    assert not (tmp_path / "answers").exists()
