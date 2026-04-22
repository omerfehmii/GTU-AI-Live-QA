from __future__ import annotations

import re
from urllib.parse import unquote

from app.core.config import get_settings
from app.services.chunker import tokenize
from app.services.provider_client import create_openai_compatible_client


SYSTEM_PROMPT = """
Sen Gebze Teknik Universitesi icin kurum odakli bir canli soru-cevap asistanisin.
Once verilen resmi GTU baglamini kullan.
Baglamda cevap varsa soruyu dogrudan ve dogal Turkce ile cevapla.
Ilk cumlede net cevabi ver, gerekirse en fazla iki kisa cumle daha ekle.
Baglam eksikse kullaniciya yine yardimci olacak sekilde cevap ver; kuruma ozgu net bir bilgi vermen gerektiginde emin olmadigini dogal bicimde belirt.
"Verilen baglamda", "baglama gore", "kaynaklarda", "dokumana gore" gibi yapay kaliplarla baslama.
Kaynak adi, URL, "Baglam 1", "Kaynak:" veya ham dokuman alintisi yazma.
Kullaniciya ic sistem detaylarini gosterme.
""".strip()


class LLMService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = create_openai_compatible_client(self.settings)

    def answer(self, question: str, contexts: list[str]) -> tuple[str, str, bool]:
        if self.client:
            try:
                response = self.client.chat.completions.create(
                    model=self.settings.active_chat_model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": self._build_user_prompt(question, contexts),
                        },
                    ],
                    temperature=0.2,
                    max_tokens=self.settings.llm_max_output_tokens,
                    timeout=self.settings.llm_timeout_seconds,
                )
                message = response.choices[0].message.content if response.choices else ""
                text = self._clean_model_answer(message if isinstance(message, str) else "")
                if text:
                    return text, self.settings.active_chat_model, False
            except Exception:
                pass
        return self._local_answer(question, contexts), "local-summary", False

    def _build_user_prompt(self, question: str, contexts: list[str]) -> str:
        prepared_contexts: list[str] = []
        for index, context in enumerate(contexts, start=1):
            title, body = self._parse_context(context)
            parts = [f"Belge {index}:"]
            if title:
                parts.append(f"Baslik: {title}")
            parts.append(f"Icerik: {body}")
            prepared_contexts.append("\n".join(parts))
        compiled_context = "\n\n".join(prepared_contexts) if prepared_contexts else "Resmi GTU baglami bulunmuyor."
        return (
            f"Soru:\n{question}\n\n"
            f"Resmi GTU baglami:\n{compiled_context}\n\n"
            "YanIt kurallari:\n"
            "- Sorunun cevabi baglamda varsa onu esas al.\n"
            "- Dogal Turkce kullan.\n"
            "- Baglam eksikse en yardimci cevabi ver; kuruma ozel kesin bilgi gerektiginde emin olmadigini dogal bicimde belirt.\n"
            '- "Verilen baglamda" diye baslama.\n'
            "- Kaynak listesi, URL veya teknik not yazma.\n\n"
            "Cevap:"
        )

    def _local_answer(self, question: str, contexts: list[str]) -> str:
        if not contexts:
            return (
                "Bu konuda net bir resmi GTU baglami bulamadim. Yine de en dogru bilgi icin ilgili GTU biriminin resmi sayfasini kontrol etmeniz iyi olur."
            )
        summary = self._summarize_contexts(question, contexts)
        if summary:
            return summary
        return (
            "Bu soru icin ilgili GTU baglamini buldum ancak daha net bir resmi bilgi icin ilgili GTU sayfasini kontrol etmeniz iyi olur."
        )

    def _summarize_contexts(self, question: str, contexts: list[str]) -> str:
        title_hint = self._build_title_hint(question, contexts)
        query_tokens = set(tokenize(question))
        sentences: list[tuple[float, str]] = []

        for context in contexts:
            _, body = self._parse_context(context)
            for sentence in self._split_sentences(body):
                tokens = set(tokenize(sentence))
                overlap = len(query_tokens & tokens) / len(query_tokens) if query_tokens else 0.0
                if overlap == 0 and sentences:
                    continue
                sentences.append((overlap, sentence.strip()))

        if not sentences:
            return ""

        sentences.sort(key=lambda item: (item[0], len(item[1])), reverse=True)
        selected: list[str] = []
        seen: set[str] = set()
        for _, sentence in sentences:
            cleaned = self._clean_sentence(sentence)
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            selected.append(cleaned)
            if len(selected) == 2:
                break

        if not selected:
            return title_hint

        answer = " ".join(selected)
        if self._looks_like_listing(answer):
            return title_hint
        if len(answer) > 520:
            answer = answer[:517].rstrip(" ,;:") + "..."
        if answer[-1] not in ".!?":
            answer += "."
        return answer

    def _build_title_hint(self, question: str, contexts: list[str]) -> str:
        question_lower = question.lower()
        question_tokens = set(tokenize(question_lower))
        best_title = ""
        best_score = 0.0

        for context in contexts:
            title, _ = self._parse_context(context)
            cleaned_title = self._clean_title(title)
            if not cleaned_title:
                continue
            title_tokens = set(tokenize(cleaned_title.lower()))
            overlap = len(question_tokens & title_tokens) / len(question_tokens) if question_tokens else 0.0
            if "takvim" in question_lower and "takvim" in cleaned_title.lower():
                overlap += 0.35
            if "akts" in question_lower and "akts" in cleaned_title.lower():
                overlap += 0.35
            if overlap > best_score:
                best_score = overlap
                best_title = cleaned_title

        if not best_title:
            return ""

        if self._is_navigation_question(question_lower):
            if "pdf" in best_title.lower() or "yonetmelik" in best_title.lower() or "yonerge" in best_title.lower():
                return f"Bu bilgiye GTU'nun {best_title} belgesi uzerinden ulasabilirsiniz."
            return f"Bu bilgiye GTU'nun {best_title} sayfasi uzerinden ulasabilirsiniz."

        if "yonetmelik" in best_title.lower() or "yonerge" in best_title.lower() or "kilavuz" in best_title.lower():
            return f"Bu konuda esas alinabilecek resmi belge {best_title}."

        return ""

    def _parse_context(self, context: str) -> tuple[str, str]:
        title = ""
        body = context.strip()
        if "\nIcerik:" in context:
            title_part, body_part = context.split("\nIcerik:", 1)
            title = title_part.replace("Kaynak:", "", 1).strip()
            body = body_part.strip()
        return title, body

    def _split_sentences(self, text: str) -> list[str]:
        collapsed = re.sub(r"\s+", " ", text).strip()
        if not collapsed:
            return []
        sentences = re.split(r"(?<=[.!?])\s+", collapsed)
        if len(sentences) == 1:
            return re.split(r"\s{2,}", collapsed)
        return sentences

    def _clean_sentence(self, sentence: str) -> str:
        cleaned = sentence.strip()
        cleaned = re.sub(r"^(Kaynak|Icerik)\s*:\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned

    def _clean_model_answer(self, text: str) -> str:
        cleaned = text.strip()
        cleaned = re.sub(r"^\s*(Cevap|Yanit)\s*:\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned)
        cleaned = cleaned.strip("`\"' ")
        return cleaned

    def _clean_title(self, title: str) -> str:
        cleaned = unquote(title).replace("_", " ").strip()
        cleaned = re.sub(r"\.pdf$", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned)
        cleaned = re.sub(r"^Gebze Teknik Universitesi\s+", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^Gebze Technical University\s+", "", cleaned, flags=re.IGNORECASE)
        if len(cleaned) > 90:
            cleaned = cleaned[:87].rstrip(" ,;:") + "..."
        return cleaned

    def _is_navigation_question(self, question: str) -> bool:
        navigation_patterns = (
            "nerede",
            "nasil ulas",
            "ulasirim",
            "ulaş",
            "hangi sayfa",
            "hangi belge",
            "link",
            "adres",
        )
        return any(pattern in question for pattern in navigation_patterns)

    def _ascii_fold(self, value: str) -> str:
        return (
            value.lower()
            .replace("ç", "c")
            .replace("ğ", "g")
            .replace("ı", "i")
            .replace("ö", "o")
            .replace("ş", "s")
            .replace("ü", "u")
        )

    def _looks_like_listing(self, text: str) -> bool:
        compact = text.strip()
        if not compact:
            return True
        uppercase_ratio = sum(character.isupper() for character in compact) / max(len(compact), 1)
        punctuation_count = sum(character in ".!?" for character in compact)
        listing_markers = compact.count("(") + compact.count("#")
        return (
            len(compact) > 60
            and punctuation_count <= 1
            and (listing_markers >= 2 or uppercase_ratio > 0.18)
        )
