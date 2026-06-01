from __future__ import annotations

import base64
import os
import shutil
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select

sys.path.append(str(Path(__file__).resolve().parents[1]))

os.environ["DATABASE_URL"] = f"sqlite:///{Path(__file__).with_name('test.db')}"
os.environ["SOURCE_ARCHIVE_DIR"] = str(Path(__file__).with_name("source_archive"))
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "secret"
os.environ["AI_PROVIDER"] = "openai"
os.environ["AI_CHAT_MODEL"] = ""
os.environ["AI_EMBEDDING_MODEL"] = ""
os.environ["OPENAI_API_KEY"] = ""
os.environ["YOUTUBE_API_KEY"] = "demo"
os.environ["OPENROUTER_API_KEY"] = ""
os.environ["TTS_ENABLED"] = "true"

from fastapi.testclient import TestClient

from app.db import SessionLocal, init_db
from app.main import app
from app.models import Answer, AnswerTrace, Chunk, Document, Question, QuestionStatus, SourceType
from app.services.embeddings import EmbeddingService
from app.services.ingest import IngestService, ParsedDocument
from app.services.llm import LLMService
from app.services.rag import RagService, RetrievedChunk
from app.services.youtube import YouTubeService


def admin_headers() -> dict[str, str]:
    token = base64.b64encode(b"admin:secret").decode("utf-8")
    return {"Authorization": f"Basic {token}"}


def setup_module() -> None:
    db_file = Path(__file__).with_name("test.db")
    archive_dir = Path(__file__).with_name("source_archive")
    if db_file.exists():
        db_file.unlink()
    if archive_dir.exists():
        shutil.rmtree(archive_dir)
    init_db()


def teardown_module() -> None:
    db_file = Path(__file__).with_name("test.db")
    archive_dir = Path(__file__).with_name("source_archive")
    if db_file.exists():
        db_file.unlink()
    if archive_dir.exists():
        shutil.rmtree(archive_dir)


def test_ingest_and_manual_question(monkeypatch) -> None:
    def fake_fetch(
        self: IngestService,
        url: str,
        allowed_domains: list[str],
        include_patterns: list[str],
    ) -> ParsedDocument:
        return ParsedDocument(
            title="GTU Bilgisayar Muhendisligi",
            content=(
                "Gebze Teknik Universitesi Bilgisayar Muhendisligi bolumu ogrencilere yapay zeka, "
                "staj ve laboratuvar imkanlari sunar. Basvurular resmi akademik takvim ile duyurulur."
            ),
            source_url=url,
            metadata_json={"discovered_links": []},
        )

    monkeypatch.setattr(IngestService, "_fetch_web_document", fake_fetch)

    client = TestClient(app)

    ingest_response = client.post(
        "/api/admin/ingest/web",
        headers=admin_headers(),
        json={
            "seed_urls": ["https://www.gtu.edu.tr"],
            "allowed_domains": ["gtu.edu.tr"],
            "max_pages": 1,
        },
    )
    assert ingest_response.status_code == 200
    assert ingest_response.json()["documents_created"] == 1

    answer_response = client.post(
        "/api/questions/manual",
        json={"content": "Bilgisayar muhendisliginde staj ve laboratuvar imkanlari var mi?", "author_name": "Test"},
    )
    assert answer_response.status_code == 200
    body = answer_response.json()
    assert body["status"] == "answered"
    assert body["answer"] is not None
    assert "traces" not in body["answer"]
    assert "GTU" in body["answer"]["content"] or "staj" in body["answer"]["content"].lower()

    metrics_response = client.get("/api/metrics")
    assert metrics_response.status_code == 200
    assert metrics_response.json()["questions_answered"] >= 1


def test_manual_queue_feeds_live_state() -> None:
    client = TestClient(app)
    queue_response = client.post(
        "/api/questions/manual/queue",
        json={"content": "Yayin kuyrugu test sorusu nasil gorunur?", "author_name": "Queue Test"},
    )
    assert queue_response.status_code == 200
    queued_question = queue_response.json()
    assert queued_question["status"] == "pending"

    live_response = client.get("/api/live/state")
    assert live_response.status_code == 200
    live_body = live_response.json()
    assert live_body["queue_size"] >= 1
    assert any(question["id"] == queued_question["id"] for question in live_body["queue"])


def test_live_state_holds_recent_answer_before_next_question() -> None:
    with SessionLocal() as db:
        for answer in db.scalars(select(Answer)).all():
            answer.created_at = datetime.now(UTC) - timedelta(days=1)

        answered_question = Question(
            source_type=SourceType.MANUAL,
            author_name="Speaker",
            content="Cevabi henuz bitmeyen soru",
            normalized_content="cevabi henuz bitmeyen soru",
            status=QuestionStatus.ANSWERED,
        )
        db.add(answered_question)
        db.flush()
        db.add(
            Answer(
                question_id=answered_question.id,
                content="Bu cevap yayinda sonuna kadar okunmali.",
                model_name="test",
                latency_ms=10,
                fallback_used=False,
                audio_duration_ms=8000,
                created_at=datetime.now(UTC),
            )
        )
        processing_question = Question(
            source_type=SourceType.MANUAL,
            author_name="Next",
            content="Siradaki soru",
            normalized_content="siradaki soru",
            status=QuestionStatus.PROCESSING,
        )
        db.add(processing_question)
        db.commit()

        live_state = RagService(db).live_state()

    assert live_state.avatar_state == "speaking"
    assert live_state.current_question
    assert live_state.current_question.id == answered_question.id
    assert live_state.latest_answered
    assert live_state.latest_answered.id == answered_question.id


def test_live_state_keeps_answer_visible_during_handoff_pause() -> None:
    with SessionLocal() as db:
        for answer in db.scalars(select(Answer)).all():
            answer.created_at = datetime.now(UTC) - timedelta(days=1)

        answered_question = Question(
            source_type=SourceType.MANUAL,
            author_name="Speaker",
            content="Yeni bitmis cevap sorusu",
            normalized_content="yeni bitmis cevap sorusu",
            status=QuestionStatus.ANSWERED,
        )
        db.add(answered_question)
        db.flush()
        db.add(
            Answer(
                question_id=answered_question.id,
                content="Bu cevap yeni bitti ve kisa sure ekranda kalmali.",
                model_name="test",
                latency_ms=10,
                fallback_used=False,
                audio_duration_ms=8000,
                created_at=datetime.now(UTC) - timedelta(seconds=8.5),
            )
        )
        processing_question = Question(
            source_type=SourceType.MANUAL,
            author_name="Next",
            content="Hemen gorunmemesi gereken soru",
            normalized_content="hemen gorunmemesi gereken soru",
            status=QuestionStatus.PROCESSING,
        )
        db.add(processing_question)
        db.commit()

        live_state = RagService(db).live_state()

    assert live_state.avatar_state == "thinking"
    assert live_state.current_question
    assert live_state.current_question.id == answered_question.id


def test_admin_can_toggle_tts_setting() -> None:
    client = TestClient(app)

    settings_response = client.get("/api/admin/settings", headers=admin_headers())
    assert settings_response.status_code == 200
    assert settings_response.json()["tts_enabled"] is True

    disabled_response = client.post(
        "/api/admin/settings",
        headers=admin_headers(),
        json={"tts_enabled": False},
    )
    assert disabled_response.status_code == 200
    assert disabled_response.json()["tts_enabled"] is False

    enabled_response = client.post(
        "/api/admin/settings",
        headers=admin_headers(),
        json={"tts_enabled": True},
    )
    assert enabled_response.status_code == 200
    assert enabled_response.json()["tts_enabled"] is True


def test_ingest_accepts_remote_pdf_urls(monkeypatch) -> None:
    def fake_fetch(
        self: IngestService,
        url: str,
        allowed_domains: list[str],
        include_patterns: list[str],
    ) -> ParsedDocument:
        return ParsedDocument(
            title="GTU Akademik Takvim",
            content="Akademik takvim ve ders tarihlerinin ozet bilgileri bu sayfada yer alir.",
            source_url=url,
            metadata_json={"discovered_links": [], "discovered_pdfs": []},
        )

    def fake_remote_pdf(self: IngestService, url: str) -> ParsedDocument:
        return ParsedDocument(
            title="Ogrenci El Kitabi",
            content="Ogrenci el kitabi barinma, kampus imkanlari ve iletisim bilgileri icerir.",
            source_url=url,
            file_name="ogrenci-el-kitabi.pdf",
            source_type=SourceType.PDF,
            metadata_json={"pages": 12},
        )

    monkeypatch.setattr(IngestService, "_fetch_web_document", fake_fetch)
    monkeypatch.setattr(IngestService, "_fetch_remote_pdf", fake_remote_pdf)

    client = TestClient(app)
    response = client.post(
        "/api/admin/ingest/web",
        headers=admin_headers(),
        json={
            "seed_urls": ["https://www.gtu.edu.tr"],
            "pdf_urls": ["https://www.gtu.edu.tr/files/ogrenci-el-kitabi.pdf"],
            "allowed_domains": ["gtu.edu.tr"],
            "include_url_patterns": ["/icerik/", "/kategori/"],
            "prioritize_url_patterns": [".pdf", "/icerik/"],
            "max_pages": 2,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["documents_created"] >= 1
    assert body["chunks_created"] >= 1


def test_rag_prefers_prep_documents_for_duration_questions(monkeypatch) -> None:
    def fake_embed(self: EmbeddingService, text: str) -> list[float]:
        return [0.0] * 1536

    def fake_embed_many(self: EmbeddingService, texts) -> list[list[float]]:
        payload = list(texts)
        return [[0.0] * 1536 for _ in payload]

    monkeypatch.setattr(EmbeddingService, "embed", fake_embed)
    monkeypatch.setattr(EmbeddingService, "embed_many", fake_embed_many)

    def fake_answer(self: LLMService, question: str, contexts: list[str]) -> tuple[str, str, bool]:
        return "GTU hazirlik egitimi bir sene surer.", "test-llm", False

    monkeypatch.setattr(LLMService, "answer", fake_answer)

    with SessionLocal() as db:
        ingest = IngestService(db)
        ingest._upsert_document(
            ParsedDocument(
                title="Hazirlik Ogrenci El Kitabi",
                content=(
                    "Gebze Teknik Universitesi Lisans Ingilizce Hazirlik Programi ogrencileri icin hazirlanmistir. "
                    "Yabanci Diller Bolumu bunyesinde bir sene boyunca alacaginiz egitim suresince derslere etkin katilim beklenir."
                ),
                source_url="https://www.gtu.edu.tr/files/hazirlik-el-kitabi.pdf",
                source_type=SourceType.PDF,
                metadata_json={"pages": 8},
            )
        )
        ingest._upsert_document(
            ParsedDocument(
                title="Academic Calendar",
                content="Final sinavlari, bahar yarıyili ve akademik takvim detaylari bu sayfada listelenir.",
                source_url="https://www.gtu.edu.tr/academic-calendar",
                metadata_json={"page_kind": "content"},
            )
        )
        db.commit()

        service = RagService(db)
        retrieved = service.retrieve("Hazirlik suresi ne kadar?")
        assert retrieved
        top_title = retrieved[0].chunk.document.title.lower()
        assert "hazirlik" in top_title or "el kitabi" in top_title

        question = service.ask_manual_question("Hazirlik suresi ne kadar?", "Test")
        assert question.answer is not None
        assert question.answer.fallback_used is False
        assert "bir sene" in question.answer.content.lower()


def test_rag_extracts_relevant_excerpt_instead_of_chunk_prefix(monkeypatch) -> None:
    def fake_embed(self: EmbeddingService, text: str) -> list[float]:
        return [0.0] * 1536

    def fake_embed_many(self: EmbeddingService, texts) -> list[list[float]]:
        payload = list(texts)
        return [[0.0] * 1536 for _ in payload]

    monkeypatch.setattr(EmbeddingService, "embed", fake_embed)
    monkeypatch.setattr(EmbeddingService, "embed_many", fake_embed_many)

    with SessionLocal() as db:
        ingest = IngestService(db)
        created, _ = ingest._upsert_document(
            ParsedDocument(
                title="Hazirlik Bilgi Notu",
                content=(
                    "Genel bilgilendirme metni ve duyuru ozeti. "
                    "Bu kisim sorunun dogrudan cevabini icermiyor. "
                    "Hazirlik bolumu egitimi bir sene surmektedir ve gerekli durumlarda ikinci yil tekrar hakki bulunur."
                ),
                source_url="https://www.gtu.edu.tr/files/hazirlik-bilgi-notu.pdf",
                source_type=SourceType.PDF,
                metadata_json={"pages": 1},
            )
        )
        assert created == 1
        db.commit()

        service = RagService(db)
        chunk = db.scalar(select(Chunk).join(Chunk.document).where(Document.title == "Hazirlik Bilgi Notu"))
        assert chunk is not None
        item = RetrievedChunk(chunk=chunk, vector_score=0.0, keyword_score=0.0, final_score=0.0)
        context = service._format_context("Hazirlik suresi ne kadar?", item)
        assert "bir sene surmektedir" in context.lower()


def test_llm_replaces_context_refusal_with_local_summary() -> None:
    class FakeMessage:
        content = "Verilen baglamda hazirlik suresi bilgisi bulunmamaktadir."

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
    answer, model_name, fallback_used = service.answer(
        "Hazirlik suresi ne kadar?",
        [
            "Kaynak: Hazirlik Ogrenci El Kitabi\n"
            "Icerik: Hazirlik bolumu egitimi bir sene surmektedir. "
            "Gerekli durumlarda ikinci yil tekrar hakki bulunur."
        ],
    )
    assert fallback_used is False
    assert model_name == service.settings.active_chat_model
    assert "verilen baglamda" in answer.lower()


def test_llm_without_provider_marks_local_summary_as_fallback() -> None:
    service = LLMService()
    service.client = None
    answer, model_name, fallback_used = service.answer(
        "Hazirlik azami kac yil surer?",
        [
            "Kaynak: Hazirlik Ogrenci El Kitabi\n"
            "Icerik: Hazirlik bolumu egitimi bir sene surmektedir."
        ],
    )
    assert fallback_used is True
    assert model_name == "local-summary"
    assert "bir sene" in answer.lower()


def test_archive_crawl_then_index(monkeypatch) -> None:
    url = "https://cache-test.gtu.edu.tr/icerik/demo.aspx"

    def fake_fetch(
        self: IngestService,
        source_url: str,
        allowed_domains: list[str],
        include_patterns: list[str],
    ) -> ParsedDocument:
        return ParsedDocument(
            title="Cache Test",
            content="Bu sayfa ilk crawl sonrasi yerel kaynak arsivinden okunur.",
            source_url=source_url,
            metadata_json={"discovered_links": [], "discovered_pdfs": []},
        )

    monkeypatch.setattr(IngestService, "_fetch_web_document", fake_fetch)

    client = TestClient(app)
    first_response = client.post(
        "/api/admin/archive/crawl",
        headers=admin_headers(),
        json={
            "seed_urls": [url],
            "allowed_domains": ["cache-test.gtu.edu.tr"],
            "use_cached_sources": True,
            "max_pages": 1,
        },
    )
    assert first_response.status_code == 200
    assert first_response.json()["sources_archived"] == 1

    cache_dir = Path(__file__).with_name("source_archive")
    assert list(cache_dir.glob("*/parsed.json"))
    documents_response = client.get("/api/admin/documents", headers=admin_headers())
    assert documents_response.status_code == 200

    def fail_fetch(
        self: IngestService,
        source_url: str,
        allowed_domains: list[str],
        include_patterns: list[str],
    ) -> ParsedDocument:
        raise AssertionError(f"network fetch should not run for {source_url}")

    monkeypatch.setattr(IngestService, "_fetch_web_document", fail_fetch)

    second_response = client.post(
        "/api/admin/archive/crawl",
        headers=admin_headers(),
        json={
            "seed_urls": [url],
            "allowed_domains": ["cache-test.gtu.edu.tr"],
            "use_cached_sources": True,
            "max_pages": 1,
        },
    )
    assert second_response.status_code == 200
    assert second_response.json()["sources_loaded_from_cache"] == 1
    assert second_response.json()["skipped"] == 0

    index_response = client.post("/api/admin/archive/index", headers=admin_headers(), json={})
    assert index_response.status_code == 200
    assert index_response.json()["documents_created"] >= 1

    stats_response = client.get("/api/admin/archive/stats", headers=admin_headers())
    assert stats_response.status_code == 200
    stats_body = stats_response.json()
    assert stats_body["total_sources"] >= 1
    assert stats_body["indexed_documents"] >= 1


def test_archive_crawl_uses_sitemap_discovery(monkeypatch) -> None:
    def fake_discover(
        self: IngestService,
        request,
        allowed_domains: list[str],
        prioritize_patterns: list[str],
    ) -> tuple[list[str], list[str], int]:
        return (["https://cache-test.gtu.edu.tr/icerik/from-sitemap.aspx"], [], 1)

    def fake_fetch(
        self: IngestService,
        source_url: str,
        allowed_domains: list[str],
        include_patterns: list[str],
    ) -> ParsedDocument:
        return ParsedDocument(
            title="Sitemap Kaynagi",
            content=f"{source_url} robots ve sitemap kesfiyle eklendi.",
            source_url=source_url,
            metadata_json={"discovered_links": [], "discovered_pdfs": []},
        )

    monkeypatch.setattr(IngestService, "_discover_sitemap_urls", fake_discover)
    monkeypatch.setattr(IngestService, "_fetch_web_document", fake_fetch)

    client = TestClient(app)
    response = client.post(
        "/api/admin/archive/crawl",
        headers=admin_headers(),
        json={
            "seed_urls": ["https://cache-test.gtu.edu.tr/icerik/root.aspx"],
            "allowed_domains": ["cache-test.gtu.edu.tr"],
            "discover_sitemaps": True,
            "max_pages": 2,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["sitemap_urls_discovered"] == 1
    assert body["sources_archived"] >= 2


def test_manual_question_prefers_string_relevance_for_specific_page(monkeypatch) -> None:
    sources = {
        "https://www.gtu.edu.tr/tr/icerik/demo/akademik-takvim-erisim-kapisi.aspx": ParsedDocument(
            title="GTU Akademik Takvim Erisim Kapisi",
            content="Bu sayfa ders, sinav ve kayit tarihlerine yonlendirir.",
            source_url="https://www.gtu.edu.tr/tr/icerik/demo/akademik-takvim-erisim-kapisi.aspx",
            metadata_json={"discovered_links": [], "discovered_pdfs": []},
        ),
        "https://www.gtu.edu.tr/tr/kategori/demo/ogrenci.aspx": ParsedDocument(
            title="GTU Ogrenci Portali",
            content=(
                "Ogrenci isleri, duyurular, akademik bilgiler ve takvim baglantilari burada ozet olarak listelenir."
            ),
            source_url="https://www.gtu.edu.tr/tr/kategori/demo/ogrenci.aspx",
            metadata_json={"discovered_links": [], "discovered_pdfs": []},
        ),
    }

    def fake_fetch(
        self: IngestService,
        url: str,
        allowed_domains: list[str],
        include_patterns: list[str],
    ) -> ParsedDocument:
        return sources[url]

    def fake_embed_many(self: EmbeddingService, texts) -> list[list[float]]:
        return [[0.01] * 1536 for _ in list(texts)]

    monkeypatch.setattr(IngestService, "_fetch_web_document", fake_fetch)
    monkeypatch.setattr(EmbeddingService, "embed_many", fake_embed_many)

    client = TestClient(app)
    response = client.post(
        "/api/admin/ingest/web",
        headers=admin_headers(),
        json={
            "seed_urls": list(sources.keys()),
            "allowed_domains": ["www.gtu.edu.tr"],
            "max_pages": 2,
        },
    )
    assert response.status_code == 200

    answer_response = client.post(
        "/api/questions/manual",
        json={"content": "Akademik takvim erisim kapisina nasil ulasirim?", "author_name": "Test"},
    )
    assert answer_response.status_code == 200
    body = answer_response.json()
    assert body["answer"] is not None
    assert "traces" not in body["answer"]

    with SessionLocal() as db:
        question = db.scalar(select(Question).where(Question.id == body["id"]))
        assert question is not None
        assert question.answer is not None
        traces = db.scalars(select(AnswerTrace).where(AnswerTrace.answer_id == question.answer.id)).all()
        assert traces
        assert "akademik-takvim-erisim-kapisi" in (traces[0].source_url or "")


def test_parse_html_document_extracts_primary_content() -> None:
    service = IngestService(SessionLocal())
    html = """
    <html>
      <head><title>Gebze Teknik Universitesi</title></head>
      <body>
        <header class="site-header">
          <nav>UNIVERSITE AKADEMIK ARASTIRMA OGRENCI MyGTU S.S.S. EN</nav>
        </header>
        <main id="content">
          <div class="breadcrumb">Ana Sayfa > Aday</div>
          <h1>Okurken Calisma ve Burs Imkanlari</h1>
          <p>GTU'de universite yasami boyunca farkli burs ve calisma imkanlari bulunur.</p>
          <p>Iskur, teknopark ve laboratuvar projelerinde ogrenciler gorev alabilir.</p>
        </main>
        <footer>
          KVKK Aydinlatma Metni
          Iletisim
          © Gebze Teknik Universitesi Rektorlugu Telefon 262 605 10 00 Faks 262 653 84 90 Kep gtu@hs01.kep.tr
        </footer>
      </body>
    </html>
    """

    parsed = service._parse_html_document(
        "https://www.gtu.edu.tr/icerik/demo/burs.aspx",
        html,
        "text/html",
        ["www.gtu.edu.tr"],
        ["/icerik/"],
    )
    service.db.close()

    assert parsed is not None
    assert parsed.title == "Okurken Calisma ve Burs Imkanlari"
    assert "burs ve calisma imkanlari" in parsed.content.lower()
    assert "mygtu" not in parsed.content.lower()
    assert "kvkk" not in parsed.content.lower()
    assert parsed.metadata_json["page_kind"] == "content"


def test_parse_html_document_marks_listing_pages() -> None:
    service = IngestService(SessionLocal())
    html = """
    <html>
      <head><title>Gebze Teknik Universitesi</title></head>
      <body>
        <main class="page-content">
          <h1>Nanoteknoloji Enstitusu Haberler</h1>
          <ul>
            <li>Akademisyenimizin projesine destek</li>
            <li>GTU NANO seminerleri</li>
            <li>Odul toreni</li>
            <li>Yaz okulu</li>
            <li>Sonraki Sayfa</li>
          </ul>
        </main>
        <footer>
          Bizi Takip Edin
          KVKK Aydinlatma Metni
        </footer>
      </body>
    </html>
    """

    parsed = service._parse_html_document(
        "https://www.gtu.edu.tr/kategori/2204/3/all-news",
        html,
        "text/html",
        ["www.gtu.edu.tr"],
        ["/kategori/"],
    )
    service.db.close()

    assert parsed is not None
    assert parsed.metadata_json["page_kind"] == "listing"
    assert "sonraki sayfa" not in parsed.content.lower()
    assert "kvkk" not in parsed.content.lower()


def test_upsert_document_replaces_existing_source_record() -> None:
    url = "https://refresh-test.gtu.edu.tr/icerik/demo.aspx"
    with SessionLocal() as db:
        service = IngestService(db)
        first = ParsedDocument(
            title="Ilk Surum",
            content="Ilk surum metni ve eski gurultulu icerik.",
            source_url=url,
            metadata_json={"discovered_links": []},
        )
        second = ParsedDocument(
            title="Guncel Surum",
            content="Guncel surum metni ve temizlenmis icerik.",
            source_url=url,
            metadata_json={"discovered_links": []},
        )

        created_first, _ = service._upsert_document(first)
        db.commit()
        created_second, _ = service._upsert_document(second)
        db.commit()

        documents = db.scalars(select(Document).where(Document.source_url == url)).all()
        chunk_count = db.scalar(
            select(func.count(Chunk.id)).join(Chunk.document).where(Document.source_url == url)
        )

    assert created_first == 1
    assert created_second == 1
    assert len(documents) == 1
    assert documents[0].title == "Guncel Surum"
    assert chunk_count == 1


def test_stream_connect(monkeypatch) -> None:
    def fake_details(self: YouTubeService, video_id: str) -> dict[str, str]:
        return {"live_chat_id": "chat-123", "title": "GTU Tanitim Yayini"}

    monkeypatch.setattr(YouTubeService, "_get_video_details", fake_details)

    client = TestClient(app)
    response = client.post(
        "/api/streams/youtube/connect",
        headers=admin_headers(),
        json={"video_id": "abc123"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["live_chat_id"] == "chat-123"
    assert payload["status"] == "connected"
