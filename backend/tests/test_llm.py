from __future__ import annotations

from app.services.llm import LLMService


def test_local_answer_prefers_clean_title_hint_for_navigation_questions() -> None:
    service = LLMService()

    answer = service._local_answer(
        "Akademik takvim sayfasina nasil ulasirim?",
        [
            "Kaynak: 2024-2025 akademik takvim.pdf\nIcerik: GEBZE TEKNIK UNIVERSITESI Etkinlik Takvimi English Kategori Seminer (431) Festival (4) Akademik Takvim (40)"
        ],
    )

    assert "Kaynak:" not in answer
    assert "Seminer (431)" not in answer
    assert "akademik takvim" in answer.lower()


def test_llm_parses_display_and_speech_answers() -> None:
    class FakeMessage:
        content = '{"display_answer":"Hazirlik bir akademik yil surer.", "speech_answer":"Evet, hazirlik normalde bir akademik yil suruyor."}'

    class FakeChoice:
        message = FakeMessage()

    class FakeCompletions:
        @staticmethod
        def create(**kwargs):
            return type("Response", (), {"choices": [FakeChoice()]})()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    service = LLMService()
    service.client = FakeClient()

    draft = service.answer("Hazirlik ne kadar surer?", ["Kaynak: Hazirlik\nIcerik: Hazirlik bir akademik yil surer."])

    assert draft.display_text == "Hazirlik bir akademik yil surer."
    assert draft.speech_text == "Evet, hazirlik normalde bir akademik yil suruyor."
    assert draft.fallback_used is False
