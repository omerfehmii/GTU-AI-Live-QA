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
