"use client";

import { useEffect, useState, useTransition } from "react";

import { createBasicAuthHeader, getJson, postForm, postJson } from "@/lib/api";
import type {
  ArchiveCrawlSummary,
  ArchiveStats,
  DocumentItem,
  IngestSummary,
  StreamSession,
} from "@/lib/types";

const DEFAULT_SEED_URLS = [
  "https://www.gtu.edu.tr/",
  "https://aday.gtu.edu.tr/",
  "https://aday.gtu.edu.tr/tr/kategori/6667/0/display.aspx",
  "https://aday.gtu.edu.tr/tr/kategori/6682/0/display.aspx",
  "https://aday.gtu.edu.tr/tr/faq-page",
  "https://abl.gtu.edu.tr/ects/",
  "https://takvim.gtu.edu.tr/",
  "https://international.gtu.edu.tr/",
  "https://www.gtu.edu.tr/tr/faq-page",
  "https://www.gtu.edu.tr/icerik/1479/592/lisans-yonetmelik-ve-yonergeler.aspx",
  "https://www.gtu.edu.tr/icerik/1846/1383/regulations-and-instructions.aspx",
  "https://www.gtu.edu.tr/icerik/6702/26289/OkurkenCalismaveBursImkanlari.aspx",
  "https://www.gtu.edu.tr/icerik/6702/26273/YurtveSosyalImkanlar.aspx",
  "https://www.gtu.edu.tr/tr/kategori/5922/0/display.aspx",
  "https://www.gtu.edu.tr/icerik/6524/25611/kizogrenciyurdu.aspx",
  "https://www.gtu.edu.tr/icerik/6460/25484/HeryerdenKolayUlasim.aspx",
  "https://www.gtu.edu.tr/kategori/6223/0/display.aspx",
  "https://www.gtu.edu.tr/kategori/6706/0/display.aspx",
  "https://www.gtu.edu.tr/kategori/38/3/display.aspx",
  "https://www.gtu.edu.tr/kategori/41/3/display.aspx",
  "https://www.gtu.edu.tr/kategori/42/3/display.aspx",
  "https://www.gtu.edu.tr/kategori/43/3/display.aspx",
  "https://www.gtu.edu.tr/kategori/91/3/bilgisayar-muhendisligi.aspx",
  "https://www.gtu.edu.tr/kategori/301/3/elektronik-muhendisligi.aspx",
  "https://www.gtu.edu.tr/kategori/306/3/kimya-muhendisligi.aspx",
  "https://www.gtu.edu.tr/tr/kategori/1007/3/ogrenci-isleri-daire-baskanligi.aspx",
  "https://www.gtu.edu.tr/tr/icerik/1318/436/akademik-takvim.aspx",
  "https://www.gtu.edu.tr/tr/icerik/63/699/ogrenci-konseyi.aspx",
  "https://www.gtu.edu.tr/en/kategori/6369/0/display.aspx",
].join("\n");

const DEFAULT_PDF_URLS = [
  "https://www.gtu.edu.tr/fileman/Files/UserFiles/kalite/Y%C3%B6netmelikler/YN-0001%20%C3%96n%20Lisans%20ve%20Lisans%20E%C4%9Fitim-%C3%96%C4%9Fretim%20Y%C3%B6netmeli%C4%9Fi%20R7.pdf",
  "https://www.gtu.edu.tr/fileman/Files/UserFiles/kalite/Y%C3%B6netmelikler/YN-0002%20Lisans%C3%BCst%C3%BC%20E%C4%9Fitim%20ve%20%C3%96%C4%9Fretim%20Y%C3%B6netmeli%C4%9Fi%20R2.pdf",
  "https://www.gtu.edu.tr/fileman/Files/UserFiles/basin_ve_halkla_iliskiler/dokumanlar/%C3%96%C4%9ERENC%C4%B0%20EL%20K%C4%B0TABI%20(2025-2026)%20REV%C4%B0ZE.pdf",
  "https://www.gtu.edu.tr/fileman/Files/290821-STRATEJIK-PLAN/GT%C3%9C%202022-2026%20STRATEJIK%20PLANI%20(AGUSTOS-2021-son).pdf",
  "https://www.gtu.edu.tr/fileman/Files/UserFiles/kalite/Politikalar/PO-0016%20GTU%20Research%20Policy%20R0.pdf",
  "https://aday.gtu.edu.tr/Files/Student_Guideline_2024_2025.pdf",
  "https://oidb.gtu.edu.tr/Files/Student_Guideline_2024_2025.pdf",
  "https://www.gtu.edu.tr/Files/Yonetmelik_ve_Yonergeler_yeni/Yonergeler/GTU_ULUSLARARASI_OGR_KOOR_YONERGE.pdf",
].join("\n");

const DEFAULT_ALLOWED_DOMAINS =
  "gtu.edu.tr,www.gtu.edu.tr,aday.gtu.edu.tr,abl.gtu.edu.tr,takvim.gtu.edu.tr,kagem.gtu.edu.tr,sem.gtu.edu.tr,oidb.gtu.edu.tr,international.gtu.edu.tr";
const DEFAULT_SITEMAP_URLS = "";
const DEFAULT_INCLUDE_PATTERNS =
  "/kategori/\n/icerik/\n/tr/\n/en/\n/faq-page\nabl.gtu.edu.tr/ects/\naday.gtu.edu.tr/\ninternational.gtu.edu.tr/";
const DEFAULT_PRIORITIZE_PATTERNS =
  "aday.gtu.edu.tr/\n/tr/\n/en/\n/faq-page\nabl.gtu.edu.tr/ects/\ninternational.gtu.edu.tr/\n/icerik/\n/kategori/\n.pdf";

export function AdminConsole() {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("change-me-demo");
  const [seedUrls, setSeedUrls] = useState(DEFAULT_SEED_URLS);
  const [pdfUrls, setPdfUrls] = useState(DEFAULT_PDF_URLS);
  const [allowedDomains, setAllowedDomains] = useState(DEFAULT_ALLOWED_DOMAINS);
  const [sitemapUrls, setSitemapUrls] = useState(DEFAULT_SITEMAP_URLS);
  const [includePatterns, setIncludePatterns] = useState(
    DEFAULT_INCLUDE_PATTERNS,
  );
  const [prioritizePatterns, setPrioritizePatterns] = useState(
    DEFAULT_PRIORITIZE_PATTERNS,
  );
  const [maxPages, setMaxPages] = useState("240");
  const [discoverSitemaps, setDiscoverSitemaps] = useState(true);
  const [useCachedSources, setUseCachedSources] = useState(true);
  const [refreshCachedSources, setRefreshCachedSources] = useState(false);
  const [videoId, setVideoId] = useState("");
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [streams, setStreams] = useState<StreamSession[]>([]);
  const [archiveStats, setArchiveStats] = useState<ArchiveStats | null>(null);
  const [status, setStatus] = useState("Admin işlemleri buradan yönetilir.");
  const [isPending, startTransition] = useTransition();

  const authHeader = {
    Authorization: createBasicAuthHeader(username, password),
  };

  async function refresh() {
    const [documentData, streamData, archiveData] = await Promise.all([
      getJson<DocumentItem[]>("/admin/documents", authHeader),
      getJson<StreamSession[]>("/streams", authHeader),
      getJson<ArchiveStats>("/admin/archive/stats", authHeader),
    ]);
    setDocuments(documentData);
    setStreams(streamData);
    setArchiveStats(archiveData);
  }

  useEffect(() => {
    void refresh().catch((error) => {
      setStatus(
        error instanceof Error ? error.message : "Admin verileri alınamadı.",
      );
    });
  }, [username, password]);

  function buildCrawlPayload() {
    return {
      seed_urls: seedUrls
        .split("\n")
        .map((item) => item.trim())
        .filter(Boolean),
      pdf_urls: pdfUrls
        .split("\n")
        .map((item) => item.trim())
        .filter(Boolean),
      sitemap_urls: sitemapUrls
        .split("\n")
        .map((item) => item.trim())
        .filter(Boolean),
      allowed_domains: allowedDomains
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean),
      include_url_patterns: includePatterns
        .split("\n")
        .map((item) => item.trim())
        .filter(Boolean),
      prioritize_url_patterns: prioritizePatterns
        .split("\n")
        .map((item) => item.trim())
        .filter(Boolean),
      discover_sitemaps: discoverSitemaps,
      use_cached_sources: useCachedSources,
      refresh_cached_sources: refreshCachedSources,
      max_pages: Number(maxPages) || 40,
    };
  }

  function applyDefaultProfile() {
    setSeedUrls(DEFAULT_SEED_URLS);
    setPdfUrls(DEFAULT_PDF_URLS);
    setSitemapUrls(DEFAULT_SITEMAP_URLS);
    setAllowedDomains(DEFAULT_ALLOWED_DOMAINS);
    setIncludePatterns(DEFAULT_INCLUDE_PATTERNS);
    setPrioritizePatterns(DEFAULT_PRIORITIZE_PATTERNS);
    setMaxPages("240");
    setDiscoverSitemaps(true);
    setStatus("Resmi GTU alanlarından derlenen geniş profil yüklendi.");
  }

  function handleArchiveCrawl() {
    startTransition(async () => {
      try {
        const summary = await postJson<ArchiveCrawlSummary>(
          "/admin/archive/crawl",
          buildCrawlPayload(),
          authHeader,
        );
        setStatus(
          `Arşiv taraması tamamlandı. ${summary.sources_archived} kaynak ağdan indirildi, ${summary.sources_loaded_from_cache} kaynak yerel arşivden kullanıldı, ${summary.sitemap_urls_discovered} URL sitemap/robots keşfiyle eklendi.`,
        );
        await refresh();
      } catch (error) {
        setStatus(
          error instanceof Error ? error.message : "Arşiv taraması başarısız.",
        );
      }
    });
  }

  function handleArchiveIndex() {
    startTransition(async () => {
      try {
        const summary = await postJson<IngestSummary>(
          "/admin/archive/index",
          {},
          authHeader,
        );
        setStatus(
          `Arşivden indexleme tamamlandı. ${summary.documents_created} belge ve ${summary.chunks_created} chunk veritabanına yazıldı.`,
        );
        await refresh();
      } catch (error) {
        setStatus(
          error instanceof Error
            ? error.message
            : "Arşivden indexleme başarısız.",
        );
      }
    });
  }

  const archiveSizeMb = archiveStats
    ? (archiveStats.total_bytes / (1024 * 1024)).toFixed(2)
    : "0.00";
  const lastCachedAtLabel = archiveStats?.last_cached_at
    ? new Date(archiveStats.last_cached_at).toLocaleString("tr-TR")
    : "Henüz yok";

  function handleConnectStream() {
    startTransition(async () => {
      try {
        await postJson<StreamSession>(
          "/streams/youtube/connect",
          { video_id: videoId },
          authHeader,
        );
        setStatus("YouTube canlı sohbet oturumu eklendi.");
        await refresh();
      } catch (error) {
        setStatus(
          error instanceof Error ? error.message : "YouTube bağlantısı başarısız.",
        );
      }
    });
  }

  function handleRebuild() {
    startTransition(async () => {
      try {
        const summary = await postJson<IngestSummary>(
          "/admin/index/rebuild",
          {},
          authHeader,
        );
        setStatus(
          `Index yenilendi. ${summary.chunks_created} chunk yeniden güncellendi.`,
        );
        await refresh();
      } catch (error) {
        setStatus(
          error instanceof Error ? error.message : "Index rebuild başarısız.",
        );
      }
    });
  }

  function handlePdfUpload(event: React.ChangeEvent<HTMLInputElement>) {
    const files = event.target.files;
    if (!files?.length) {
      return;
    }
    startTransition(async () => {
      try {
        const formData = new FormData();
        Array.from(files).forEach((file) => formData.append("files", file));
        const summary = await postForm<IngestSummary>(
          "/admin/ingest/pdf",
          formData,
          authHeader,
        );
        setStatus(
          `PDF ingest tamamlandı. ${summary.documents_created} belge eklendi.`,
        );
        await refresh();
      } catch (error) {
        setStatus(
          error instanceof Error ? error.message : "PDF ingest başarısız.",
        );
      }
    });
  }

  return (
    <main className="shell admin-shell">
      {/* ─── Hero ─── */}
      <section className="hero animate-in" style={{ marginBottom: "var(--space-lg)" }}>
        <div className="hero-content">
          <div className="eyebrow">
            <span>⚙</span> Operator Console
          </div>
          <div className="hero-row">
            <div>
              <h1>
                Canlı yayın bağlantısı, döküman ingest ve indeks yönetimi.
              </h1>
              <p className="hero-copy">
                Bu sayfa ilk demo sırasında operatörün veri toplama, stream açma
                ve index yenileme ihtiyacını karşılar.
              </p>
            </div>
            <a className="admin-link" href="/">
              ◀ Canlı görünüm
            </a>
          </div>
        </div>
      </section>

      {/* ─── Status Bar ─── */}
      <div
        className="panel panel-accent animate-in animate-in-delay-1"
        style={{ marginBottom: "var(--space-lg)" }}
      >
        <div className="panel-head">
          <h2>Sistem Durumu</h2>
          <span className="live-chip">
            {isPending ? "Çalışıyor" : "Hazır"}
          </span>
        </div>
        <div className="form-grid">
          <label>
            Kullanıcı adı
            <input
              value={username}
              onChange={(event) => setUsername(event.target.value)}
            />
          </label>
          <label>
            Şifre
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
        </div>
        <p className="status-note" style={{ marginTop: "var(--space-md)" }}>
          {status}
        </p>
      </div>

      {/* ─── Top 3-Col Grid: YouTube, PDF, Archive Stats ─── */}
      <div className="admin-grid-3">
        {/* YouTube */}
        <div className="panel animate-in animate-in-delay-2">
          <div className="panel-head">
            <h2>▶ YouTube Stream</h2>
            <span className="subtle-note">Gerçek live chat bağlantısı</span>
          </div>
          <label>
            Video ID
            <input
              value={videoId}
              onChange={(event) => setVideoId(event.target.value)}
              placeholder="YouTube video ID"
            />
          </label>
          <button
            className="btn btn-primary"
            type="button"
            onClick={handleConnectStream}
            style={{ marginTop: "var(--space-md)", width: "100%" }}
          >
            Streami bağla
          </button>
        </div>

        {/* PDF Upload */}
        <div className="panel animate-in animate-in-delay-3">
          <div className="panel-head">
            <h2>📄 PDF Ingest</h2>
            <span className="subtle-note">Yönerge, kılavuz, takvim</span>
          </div>
          <input
            type="file"
            accept="application/pdf"
            multiple
            onChange={handlePdfUpload}
          />
          <button
            className="btn btn-secondary"
            type="button"
            onClick={handleRebuild}
            style={{ marginTop: "var(--space-md)", width: "100%" }}
          >
            Indexi yeniden oluştur
          </button>
        </div>

        {/* Archive Stats */}
        <div className="panel animate-in animate-in-delay-4">
          <div className="panel-head">
            <h2>📊 Arşiv İstatistikleri</h2>
          </div>
          <div className="archive-stats-grid">
            <div className="archive-stat-item">
              <span className="stat-value">
                {archiveStats?.total_sources ?? 0}
              </span>
              <span className="stat-label">Toplam kaynak</span>
            </div>
            <div className="archive-stat-item">
              <span className="stat-value">
                {archiveStats?.web_sources ?? 0}
              </span>
              <span className="stat-label">Web</span>
            </div>
            <div className="archive-stat-item">
              <span className="stat-value">
                {archiveStats?.pdf_sources ?? 0}
              </span>
              <span className="stat-label">PDF</span>
            </div>
            <div className="archive-stat-item">
              <span className="stat-value">{archiveSizeMb} MB</span>
              <span className="stat-label">Boyut</span>
            </div>
            <div className="archive-stat-item">
              <span className="stat-value">
                {archiveStats?.indexed_documents ?? 0}
              </span>
              <span className="stat-label">İndexli</span>
            </div>
            <div className="archive-stat-item">
              <span className="stat-value">
                {archiveStats?.raw_files_present ?? 0}
              </span>
              <span className="stat-label">Ham dosya</span>
            </div>
          </div>
          <p className="status-note">Son güncelleme: {lastCachedAtLabel}</p>
        </div>
      </div>

      {/* ─── Crawl & Archive Panel ─── */}
      <div
        className="section-title animate-in animate-in-delay-3"
        style={{ animationDelay: "200ms" }}
      >
        <h2>Crawl ve Arşiv</h2>
      </div>

      <div className="panel animate-in" style={{ animationDelay: "240ms" }}>
        <div className="panel-head">
          <h2>🌐 Kaynak yapılandırması</h2>
          <button
            className="btn btn-accent btn-sm"
            type="button"
            onClick={applyDefaultProfile}
          >
            GTU profilini yükle
          </button>
        </div>

        <div className="dashboard-grid" style={{ marginTop: 0 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-md)" }}>
            <label>
              Seed URL listesi
              <textarea
                value={seedUrls}
                onChange={(event) => setSeedUrls(event.target.value)}
                rows={5}
              />
            </label>
            <label>
              PDF URL listesi
              <textarea
                value={pdfUrls}
                onChange={(event) => setPdfUrls(event.target.value)}
                rows={4}
              />
            </label>
            <label>
              Ek sitemap URL listesi
              <textarea
                value={sitemapUrls}
                onChange={(event) => setSitemapUrls(event.target.value)}
                rows={3}
              />
            </label>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-md)" }}>
            <label>
              İzinli domainler
              <input
                value={allowedDomains}
                onChange={(event) => setAllowedDomains(event.target.value)}
              />
            </label>
            <label>
              Dahil et patternleri
              <textarea
                value={includePatterns}
                onChange={(event) => setIncludePatterns(event.target.value)}
                rows={4}
              />
            </label>
            <label>
              Öncelik patternleri
              <textarea
                value={prioritizePatterns}
                onChange={(event) =>
                  setPrioritizePatterns(event.target.value)
                }
                rows={4}
              />
            </label>
            <label>
              Maksimum sayfa
              <input
                value={maxPages}
                onChange={(event) => setMaxPages(event.target.value)}
                inputMode="numeric"
              />
            </label>
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: "var(--space-sm)",
              }}
            >
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={discoverSitemaps}
                  onChange={(event) =>
                    setDiscoverSitemaps(event.target.checked)
                  }
                />
                Robots ve sitemap keşfini kullan
              </label>
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={useCachedSources}
                  onChange={(event) =>
                    setUseCachedSources(event.target.checked)
                  }
                />
                Yerel kaynak arşivini kullan
              </label>
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={refreshCachedSources}
                  onChange={(event) =>
                    setRefreshCachedSources(event.target.checked)
                  }
                />
                Kaynakları ağdan yeniden indir
              </label>
            </div>
          </div>
        </div>

        <p className="status-note" style={{ marginTop: "var(--space-md)" }}>
          İndirilen HTML ve PDF kaynakları backend/data/source_archive altında
          saklanır.
        </p>

        <div className="form-grid" style={{ marginTop: "var(--space-lg)" }}>
          <button
            className="btn btn-primary"
            type="button"
            onClick={handleArchiveCrawl}
          >
            1. Arşive indir
          </button>
          <button
            className="btn btn-secondary"
            type="button"
            onClick={handleArchiveIndex}
          >
            2. Arşivden indexle
          </button>
        </div>
      </div>

      {/* ─── Documents & Streams ─── */}
      <section className="dashboard-grid" style={{ marginTop: "var(--space-lg)" }}>
        <div className="panel animate-in" style={{ animationDelay: "300ms" }}>
          <div className="panel-head">
            <h2>İndexlenmiş belgeler</h2>
            <span className="subtle-note">{documents.length} kayıt</span>
          </div>
          <div className="feed">
            {documents.length === 0 ? (
              <div className="empty-state">Henüz belge indexlenmedi.</div>
            ) : (
              documents.map((document) => (
                <article key={document.id} className="compact-card">
                  <div className="question-meta">
                    <span className={`badge badge-${document.source_type}`}>
                      {document.source_type}
                    </span>
                    <span>
                      {new Date(document.created_at).toLocaleString("tr-TR")}
                    </span>
                  </div>
                  <h3>{document.title}</h3>
                  <p>
                    {document.source_url || document.file_name || "Yerel dosya"}
                  </p>
                </article>
              ))
            )}
          </div>
          <button
            className="btn btn-secondary"
            type="button"
            onClick={() => void refresh()}
            style={{ marginTop: "var(--space-md)", width: "100%" }}
          >
            Döküman listesini yenile
          </button>
        </div>

        <div className="panel animate-in" style={{ animationDelay: "360ms" }}>
          <div className="panel-head">
            <h2>Aktif streamler</h2>
            <span className="subtle-note">{streams.length} oturum</span>
          </div>
          <div className="feed">
            {streams.length === 0 ? (
              <div className="empty-state">Henüz stream bağlanmadı.</div>
            ) : (
              streams.map((stream) => (
                <article key={stream.id} className="compact-card">
                  <div className="question-meta">
                    <span className={`badge badge-${stream.status}`}>
                      {stream.status}
                    </span>
                    <span>{stream.youtube_video_id}</span>
                  </div>
                  <h3>{stream.title || "Adsız yayın"}</h3>
                  <p>Live chat: {stream.live_chat_id}</p>
                  <p>
                    {stream.error_message ||
                      "Polling worker tarafından sürdürülüyor."}
                  </p>
                </article>
              ))
            )}
          </div>
        </div>
      </section>
    </main>
  );
}
