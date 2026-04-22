from __future__ import annotations

import io
import json
import re
import unicodedata
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from xml.etree import ElementTree as ET

import httpx
from bs4 import BeautifulSoup
from bs4.element import Tag
from pypdf import PdfReader
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Chunk, Document, SourceType
from app.schemas import ArchiveCrawlSummary, ArchiveIndexRequest, ArchiveStatsRead, IngestSummary, WebIngestRequest
from app.services.chunker import chunk_text, is_same_domain, normalize_text, safe_join, sha256_digest, token_count
from app.services.embeddings import EmbeddingService


CONTENT_SELECTORS = (
    "main",
    "article",
    "[role='main']",
    "#content",
    "#main",
    "#mainContent",
    ".content",
    ".main-content",
    ".page-content",
    ".entry-content",
    ".article-content",
    ".post-content",
    ".icerik",
    ".icerikDetay",
    ".rich-text-content",
    ".content-area",
)

CONTENT_HINTS = (
    "content",
    "main",
    "article",
    "post",
    "entry",
    "detail",
    "icerik",
    "metin",
    "rich",
    "body",
)

NOISE_CONTAINER_HINTS = (
    "footer",
    "header",
    "nav",
    "navbar",
    "menu",
    "sidebar",
    "breadcrumb",
    "social",
    "share",
    "cookie",
    "popup",
    "modal",
    "banner",
    "slider",
    "search",
    "quick",
    "announcement-list",
    "news-list",
    "pager",
    "pagination",
)

NOISE_BLOCK_PATTERNS = (
    r"^(mygtu|sss|s s s|tr|en|international)$",
    r"^(haberler|duyurular|etkinlikler)( tumu)?$",
    r"^(onceki|sonraki|next|previous)( sayfa)?$",
    r"^ilan portali$",
    r"^kvkk aydinlatma metni$",
    r"^iletisim$",
    r"^bizi takip edin$",
    r"^tum[ua]$",
)

NAVIGATION_HINTS = {
    "akademik",
    "arastirma",
    "ogrenci",
    "international",
    "mygtu",
    "sss",
    "hakkinda",
    "yonetim",
    "egitim",
    "iletisim",
    "haberler",
    "duyurular",
    "etkinlikler",
    "fakulteler",
    "bolumler",
    "enstituler",
}

GENERIC_WEB_TITLES = {
    "gebze teknik universitesi",
    "gebze technical university",
    "gtu",
}

LISTING_URL_HINTS = (
    "all-news",
    "all-announcements",
    "/haber/",
    "/haberler",
    "/duyuru/",
    "/duyurular",
    "/etkinlik/",
    "/etkinlikler",
)


@dataclass
class ParsedDocument:
    title: str
    content: str
    metadata_json: dict[str, Any]
    source_url: str | None = None
    file_name: str | None = None
    source_type: SourceType = SourceType.WEB


@dataclass
class FetchedDocument:
    parsed: ParsedDocument
    from_cache: bool


@dataclass
class CrawlStats:
    sources_archived: int = 0
    sources_loaded_from_cache: int = 0
    sitemap_urls_discovered: int = 0
    indexed_documents: int = 0
    indexed_chunks: int = 0
    skipped: int = 0


class IngestService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()
        self.embedding_service = EmbeddingService()
        self.use_cached_sources = True
        self.refresh_cached_sources = False

    def crawl_to_archive(self, request: WebIngestRequest) -> ArchiveCrawlSummary:
        stats = self._crawl_sources(request, index_documents=False)
        return ArchiveCrawlSummary(
            sources_archived=stats.sources_archived,
            sources_loaded_from_cache=stats.sources_loaded_from_cache,
            sitemap_urls_discovered=stats.sitemap_urls_discovered,
            skipped=stats.skipped,
        )

    def archive_stats(self) -> ArchiveStatsRead:
        total_sources = 0
        web_sources = 0
        pdf_sources = 0
        raw_files_present = 0
        total_bytes = 0
        last_cached_at: datetime | None = None

        for parsed_path in self._iter_archive_parsed_paths():
            parsed = self._load_cached_document_from_path(parsed_path)
            if not parsed:
                continue
            total_sources += 1
            if parsed.source_type == SourceType.PDF:
                pdf_sources += 1
            else:
                web_sources += 1

            cache_dir = parsed_path.parent
            raw_files = [path for path in cache_dir.iterdir() if path.is_file() and path.name != "parsed.json"]
            if raw_files:
                raw_files_present += 1
            total_bytes += sum(path.stat().st_size for path in raw_files)
            total_bytes += parsed_path.stat().st_size

            cached_at = parsed.metadata_json.get("archive", {}).get("cached_at")
            if cached_at:
                try:
                    cached_at_dt = datetime.fromisoformat(cached_at)
                except ValueError:
                    cached_at_dt = None
                if cached_at_dt and (last_cached_at is None or cached_at_dt > last_cached_at):
                    last_cached_at = cached_at_dt

        indexed_documents = int(self.db.scalar(select(func.count(Document.id))) or 0)
        return ArchiveStatsRead(
            total_sources=total_sources,
            web_sources=web_sources,
            pdf_sources=pdf_sources,
            raw_files_present=raw_files_present,
            total_bytes=total_bytes,
            indexed_documents=indexed_documents,
            last_cached_at=last_cached_at,
        )

    def index_archive(self, payload: ArchiveIndexRequest | None = None) -> IngestSummary:
        created = 0
        chunks_created = 0
        skipped = 0
        parsed_paths = self._iter_archive_parsed_paths(payload.cache_keys if payload else None)
        processed_since_commit = 0

        for parsed_path in parsed_paths:
            parsed = self._load_cached_document_from_path(parsed_path)
            if not parsed:
                skipped += 1
                continue
            created_now, chunk_count = self._upsert_document(parsed)
            created += created_now
            chunks_created += chunk_count
            processed_since_commit += 1
            if processed_since_commit >= 10:
                self.db.commit()
                processed_since_commit = 0

        self.db.commit()
        return IngestSummary(documents_created=created, chunks_created=chunks_created, skipped=skipped)

    def ingest_web(self, request: WebIngestRequest) -> IngestSummary:
        self.use_cached_sources = request.use_cached_sources
        self.refresh_cached_sources = request.refresh_cached_sources
        stats = self._crawl_sources(request, index_documents=True)
        self.db.commit()
        return IngestSummary(
            documents_created=stats.indexed_documents,
            chunks_created=stats.indexed_chunks,
            skipped=stats.skipped,
        )

    def _crawl_sources(self, request: WebIngestRequest, *, index_documents: bool) -> CrawlStats:
        self.use_cached_sources = request.use_cached_sources
        self.refresh_cached_sources = request.refresh_cached_sources
        seed_urls = [str(url) for url in request.seed_urls]
        pdf_urls = [str(url) for url in request.pdf_urls]
        allowed_domains = request.allowed_domains or [
            urlparse(str(url)).netloc
            for url in [*request.seed_urls, *request.pdf_urls, *request.sitemap_urls]
            if urlparse(str(url)).netloc
        ]
        include_patterns = [pattern.strip() for pattern in request.include_url_patterns if pattern.strip()]
        prioritize_patterns = [pattern.strip() for pattern in request.prioritize_url_patterns if pattern.strip()]
        sitemap_page_urls, sitemap_pdf_urls, sitemap_urls_discovered = self._discover_sitemap_urls(
            request=request,
            allowed_domains=allowed_domains,
            prioritize_patterns=prioritize_patterns,
        )
        forced_urls = set([*seed_urls, *pdf_urls, *sitemap_page_urls, *sitemap_pdf_urls])
        queue = deque(self._sort_urls([*seed_urls, *pdf_urls, *sitemap_page_urls, *sitemap_pdf_urls], prioritize_patterns))
        visited: set[str] = set()
        stats = CrawlStats(sitemap_urls_discovered=sitemap_urls_discovered)

        while queue and len(visited) < request.max_pages:
            url = queue.popleft()
            if url in visited or not is_same_domain(url, allowed_domains):
                continue
            if not self._should_ingest_url(url, include_patterns, forced_urls):
                continue
            visited.add(url)
            try:
                fetched = self._fetch_document(url, allowed_domains, include_patterns)
            except Exception:
                stats.skipped += 1
                continue
            if not fetched:
                stats.skipped += 1
                continue
            if fetched.from_cache:
                stats.sources_loaded_from_cache += 1
            else:
                stats.sources_archived += 1
            parsed = fetched.parsed
            if index_documents:
                created_now, chunk_count = self._upsert_document(parsed)
                stats.indexed_documents += created_now
                stats.indexed_chunks += chunk_count
            discovered_links = self._sort_urls(parsed.metadata_json.get("discovered_links", []), prioritize_patterns)
            discovered_pdfs = self._sort_urls(parsed.metadata_json.get("discovered_pdfs", []), prioritize_patterns)
            for discovered in discovered_links:
                if discovered not in visited and discovered not in queue:
                    queue.append(discovered)
            for discovered_pdf in discovered_pdfs:
                if discovered_pdf not in visited and discovered_pdf not in queue:
                    queue.append(discovered_pdf)
        return stats

    def ingest_pdf_uploads(self, files: list[tuple[str, bytes]]) -> IngestSummary:
        created = 0
        chunks_created = 0
        skipped = 0
        for file_name, raw_bytes in files:
            parsed = self._parse_pdf(file_name, raw_bytes)
            if not parsed:
                skipped += 1
                continue
            self._store_cached_document(
                f"upload://{file_name}:{sha256_digest(raw_bytes)}",
                parsed,
                raw_bytes=raw_bytes,
                content_type="application/pdf",
            )
            created_now, chunk_count = self._upsert_document(parsed)
            created += created_now
            chunks_created += chunk_count
        self.db.commit()
        return IngestSummary(documents_created=created, chunks_created=chunks_created, skipped=skipped)

    def rebuild_index(self, document_ids: list[str] | None = None) -> IngestSummary:
        statement = select(Chunk).join(Document)
        if document_ids:
            statement = statement.where(Chunk.document_id.in_(document_ids))
        chunks = self.db.scalars(statement).all()
        if not chunks:
            return IngestSummary(documents_created=0, chunks_created=0, skipped=0)
        embeddings = self.embedding_service.embed_many(chunk.content for chunk in chunks)
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            chunk.embedding = embedding
        self.db.commit()
        documents_count = len({chunk.document_id for chunk in chunks})
        return IngestSummary(documents_created=documents_count, chunks_created=len(chunks), skipped=0)

    def list_documents(self) -> list[Document]:
        return self.db.scalars(select(Document).order_by(Document.created_at.desc())).all()

    def _fetch_document(
        self,
        url: str,
        allowed_domains: list[str],
        include_patterns: list[str],
    ) -> FetchedDocument | None:
        cached = self._load_cached_document(url) if self.use_cached_sources else None
        if cached and not self.refresh_cached_sources:
            return FetchedDocument(parsed=cached, from_cache=True)
        try:
            if self._is_pdf_url(url):
                parsed = self._fetch_remote_pdf(url)
            else:
                parsed = self._fetch_web_document(url, allowed_domains, include_patterns)
        except Exception:
            if cached:
                return FetchedDocument(parsed=cached, from_cache=True)
            raise
        if parsed and self.use_cached_sources and not (self._cache_dir(url) / "parsed.json").exists():
            self._store_cached_document(url, parsed)
        if not parsed:
            return None
        return FetchedDocument(parsed=parsed, from_cache=False)

    def _fetch_web_document(
        self,
        url: str,
        allowed_domains: list[str],
        include_patterns: list[str],
    ) -> ParsedDocument | None:
        with httpx.Client(timeout=20.0, follow_redirects=True, headers={"User-Agent": "GTU-AI-Demo/1.0"}) as client:
            response = client.get(url)
            response.raise_for_status()
        content_type = response.headers.get("content-type", "").lower()
        if "application/pdf" in content_type:
            return self._parse_pdf_from_url(url, response.content)
        parsed = self._parse_html_document(
            url,
            response.text,
            response.headers.get("content-type"),
            allowed_domains,
            include_patterns,
        )
        if not parsed:
            return None
        if self.use_cached_sources:
            self._store_cached_document(
                url,
                parsed,
                raw_bytes=response.content,
                content_type=response.headers.get("content-type"),
            )
        return parsed

    def _parse_html_document(
        self,
        url: str,
        html: str,
        content_type: str | None,
        allowed_domains: list[str],
        include_patterns: list[str],
    ) -> ParsedDocument | None:
        soup = BeautifulSoup(html, "html.parser")
        discovered_links, discovered_pdfs = self._discover_page_links(soup, url, allowed_domains, include_patterns)
        self._strip_noise_nodes(soup)
        primary_node = self._select_primary_content_node(soup)
        title = self._extract_web_title(soup, primary_node, url)
        content_blocks = self._extract_content_blocks(primary_node or soup.body or soup)
        if not content_blocks:
            fallback_text = normalize_text((primary_node or soup.body or soup).get_text(" ", strip=True))
            content_blocks = [fallback_text] if fallback_text else []
        cleaned_blocks = self._clean_content_blocks(content_blocks)
        if not cleaned_blocks:
            return None
        body = "\n".join(cleaned_blocks).strip()
        if token_count(body) < 8:
            return None
        page_kind = self._classify_web_page(url, cleaned_blocks)
        return ParsedDocument(
            title=title,
            content=body,
            source_url=url,
            metadata_json={
                "content_type": content_type,
                "discovered_links": discovered_links[:40],
                "discovered_pdfs": discovered_pdfs[:25],
                "page_kind": page_kind,
                "content_blocks": len(cleaned_blocks),
                "content_chars": len(body),
            },
        )

    def _discover_page_links(
        self,
        soup: BeautifulSoup,
        url: str,
        allowed_domains: list[str],
        include_patterns: list[str],
    ) -> tuple[list[str], list[str]]:
        discovered_links: list[str] = []
        discovered_pdfs: list[str] = []
        for anchor in soup.find_all("a", href=True):
            link = safe_join(url, anchor["href"])
            if not is_same_domain(link, allowed_domains):
                continue
            if self._is_pdf_url(link):
                discovered_pdfs.append(link)
            elif self._matches_include_patterns(link, include_patterns):
                discovered_links.append(link)
        return discovered_links, discovered_pdfs

    def _strip_noise_nodes(self, soup: BeautifulSoup) -> None:
        for node in soup(["script", "style", "noscript", "svg", "iframe", "canvas", "form", "button", "input"]):
            node.decompose()
        for node in list(soup.find_all(True)):
            attrs = getattr(node, "attrs", None)
            if attrs is None:
                continue
            role = normalize_text(str(attrs.get("role", ""))).lower()
            if role in {"navigation", "banner", "contentinfo", "complementary", "search", "dialog"}:
                node.decompose()
                continue
            if str(attrs.get("aria-hidden", "")).lower() == "true":
                node.decompose()
                continue
            marker_text = self._marker_text(node)
            if marker_text and any(hint in marker_text for hint in NOISE_CONTAINER_HINTS):
                node.decompose()

    def _select_primary_content_node(self, soup: BeautifulSoup) -> Tag | BeautifulSoup | None:
        body = soup.body or soup
        candidates: list[Tag] = []
        seen: set[int] = set()

        for selector in CONTENT_SELECTORS:
            for node in body.select(selector):
                if id(node) in seen:
                    continue
                seen.add(id(node))
                candidates.append(node)

        for node in body.find_all(["section", "div", "main", "article"], limit=200):
            text = normalize_text(node.get_text(" ", strip=True))
            if len(text) < 120:
                continue
            if not node.find(["h1", "h2", "h3", "h4", "p", "li", "dd", "dt"]):
                continue
            if id(node) in seen:
                continue
            seen.add(id(node))
            candidates.append(node)

        best_node: Tag | BeautifulSoup | None = None
        best_score = -1.0
        for node in candidates or [body]:
            text = normalize_text(node.get_text(" ", strip=True))
            if len(text) < 120:
                continue
            link_count = len(node.find_all("a"))
            paragraph_count = len(node.find_all("p"))
            heading_count = len(node.find_all(["h1", "h2", "h3"]))
            score = float(len(text))
            if isinstance(node, Tag) and node.name in {"main", "article"}:
                score += 700
            marker_text = self._marker_text(node)
            if any(hint in marker_text for hint in CONTENT_HINTS):
                score += 550
            if any(hint in marker_text for hint in NOISE_CONTAINER_HINTS):
                score -= 800
            score += min(paragraph_count * 40, 280)
            score += min(heading_count * 120, 240)
            score -= min(link_count * 12, 360)
            lowered_text = self._fold_text(text[:2000])
            if "telefon" in lowered_text and ("faks" in lowered_text or "kep" in lowered_text):
                score -= 1600
            if "kvkk aydinlatma metni" in lowered_text or "bizi takip edin" in lowered_text:
                score -= 900
            if score > best_score:
                best_score = score
                best_node = node
        return best_node or body

    def _extract_web_title(self, soup: BeautifulSoup, primary_node: Tag | BeautifulSoup | None, url: str) -> str:
        candidates: list[str] = []
        if primary_node and isinstance(primary_node, Tag):
            heading = primary_node.find(["h1", "h2", "h3"])
            if heading:
                candidates.append(heading.get_text(" ", strip=True))
        meta_title = soup.find("meta", attrs={"property": "og:title"})
        if meta_title and meta_title.get("content"):
            candidates.append(str(meta_title["content"]))
        if soup.title:
            candidates.append(soup.title.get_text(" ", strip=True))
        first_heading = soup.find(["h1", "h2", "h3"])
        if first_heading:
            candidates.append(first_heading.get_text(" ", strip=True))

        cleaned_candidates: list[str] = []
        for candidate in candidates:
            cleaned = self._clean_title_candidate(candidate)
            if cleaned and cleaned not in cleaned_candidates:
                cleaned_candidates.append(cleaned)

        for candidate in cleaned_candidates:
            if self._fold_text(candidate) not in GENERIC_WEB_TITLES:
                return candidate
        return cleaned_candidates[0] if cleaned_candidates else url

    def _clean_title_candidate(self, candidate: str) -> str:
        cleaned = normalize_text(candidate)
        cleaned = re.sub(
            r"\s*[\|\-–]\s*(Gebze Teknik Universitesi|Gebze Teknik University|Gebze Technical University|GTU)\s*$",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"^\s*(Gebze Teknik Universitesi|Gebze Teknik University|Gebze Technical University|GTU)\s*[\|\-–:]\s*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        return normalize_text(cleaned)

    def _extract_content_blocks(self, root: Tag | BeautifulSoup) -> list[str]:
        blocks: list[str] = []
        for node in root.find_all(["h1", "h2", "h3", "h4", "p", "li", "dt", "dd", "blockquote", "td", "th"]):
            text = normalize_text(node.get_text(" ", strip=True))
            if text:
                blocks.append(text)
        return blocks

    def _clean_content_blocks(self, blocks: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen_short: set[str] = set()
        for block in blocks:
            text = normalize_text(block)
            if not text or self._is_noise_block(text):
                continue
            folded = self._fold_text(text)
            if cleaned and self._fold_text(cleaned[-1]) == folded:
                continue
            if len(folded) <= 180 and folded in seen_short:
                continue
            cleaned.append(text)
            if len(folded) <= 180:
                seen_short.add(folded)
        return cleaned

    def _is_noise_block(self, text: str) -> bool:
        folded = self._fold_text(text)
        if not folded:
            return True
        if any(re.fullmatch(pattern, folded) for pattern in NOISE_BLOCK_PATTERNS):
            return True
        if "kvkk aydinlatma metni" in folded or "bizi takip edin" in folded:
            return True
        if "telefon" in folded and ("faks" in folded or "kep" in folded):
            return True
        if "gebze teknik universitesi rektorlugu" in folded and "telefon" in folded:
            return True
        tokens = folded.split()
        nav_hits = sum(token in NAVIGATION_HINTS for token in tokens)
        if len(tokens) <= 18 and nav_hits >= 4 and "." not in text and ":" not in text:
            return True
        return False

    def _classify_web_page(self, url: str, blocks: list[str]) -> str:
        path = urlparse(url).path.lower()
        if path in {"", "/"}:
            return "homepage"
        if any(hint in path for hint in LISTING_URL_HINTS):
            return "listing"
        short_blocks = sum(token_count(block) <= 10 for block in blocks)
        joined = self._fold_text(" ".join(blocks[:20]))
        if blocks and (short_blocks / len(blocks)) > 0.65 and any(
            keyword in joined for keyword in ("haberler", "duyurular", "etkinlikler")
        ):
            return "listing"
        return "content"

    def _marker_text(self, node: Tag | BeautifulSoup) -> str:
        classes_value = node.attrs.get("class", []) if isinstance(node, Tag) else []
        if isinstance(classes_value, str):
            classes = classes_value
        else:
            classes = " ".join(classes_value)
        identifier = node.attrs.get("id", "") if isinstance(node, Tag) else ""
        role = node.attrs.get("role", "") if isinstance(node, Tag) else ""
        return self._fold_text(f"{classes} {identifier} {role}")

    def _fold_text(self, value: str) -> str:
        normalized = unicodedata.normalize("NFKD", normalize_text(value).lower())
        folded = "".join(character for character in normalized if not unicodedata.combining(character))
        folded = re.sub(r"[^a-z0-9]+", " ", folded)
        return normalize_text(folded)

    def _fetch_remote_pdf(self, url: str) -> ParsedDocument | None:
        with httpx.Client(timeout=25.0, follow_redirects=True, headers={"User-Agent": "GTU-AI-Demo/1.0"}) as client:
            response = client.get(url)
            response.raise_for_status()
        parsed = self._parse_pdf_from_url(url, response.content)
        if parsed and self.use_cached_sources:
            self._store_cached_document(
                url,
                parsed,
                raw_bytes=response.content,
                content_type=response.headers.get("content-type"),
            )
        return parsed

    def _parse_pdf_from_url(self, url: str, raw_bytes: bytes) -> ParsedDocument | None:
        raw_file_name = urlparse(url).path.split("/")[-1] or "document.pdf"
        file_name = unquote(raw_file_name)
        parsed = self._parse_pdf(file_name, raw_bytes)
        if parsed:
            parsed.source_url = url
        return parsed

    def _parse_pdf(self, file_name: str, raw_bytes: bytes) -> ParsedDocument | None:
        reader = PdfReader(io.BytesIO(raw_bytes))
        text_parts = [page.extract_text() or "" for page in reader.pages]
        content = normalize_text("\n".join(text_parts))
        if not content:
            return None
        metadata_title = normalize_text(str(getattr(reader.metadata, "title", "") or ""))
        title = self._clean_pdf_title(metadata_title or file_name)
        return ParsedDocument(
            title=title,
            content=content,
            file_name=file_name,
            source_type=SourceType.PDF,
            metadata_json={"pages": len(reader.pages)},
        )

    def _clean_pdf_title(self, value: str) -> str:
        cleaned = unquote(value).replace("_", " ")
        cleaned = normalize_text(cleaned)
        cleaned = re.sub(r"\.pdf$", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned)
        if not cleaned:
            return "document"
        return cleaned[:500]

    def _load_cached_document(self, url: str) -> ParsedDocument | None:
        parsed_path = self._cache_dir(url) / "parsed.json"
        return self._load_cached_document_from_path(parsed_path)

    def _load_cached_document_from_path(self, parsed_path: Path) -> ParsedDocument | None:
        if not parsed_path.exists():
            return None
        payload = json.loads(parsed_path.read_text(encoding="utf-8"))
        return ParsedDocument(
            title=payload["title"],
            content=payload["content"],
            metadata_json=payload.get("metadata_json") or {},
            source_url=payload.get("source_url"),
            file_name=payload.get("file_name"),
            source_type=SourceType(payload.get("source_type", SourceType.WEB.value)),
        )

    def _iter_archive_parsed_paths(self, cache_keys: list[str] | None = None) -> list[Path]:
        archive_root = self.settings.source_archive_path
        if not archive_root.exists():
            return []
        if cache_keys:
            return [archive_root / cache_key / "parsed.json" for cache_key in cache_keys]
        return sorted(archive_root.glob("*/parsed.json"))

    def _store_cached_document(
        self,
        cache_id: str,
        parsed: ParsedDocument,
        raw_bytes: bytes | None = None,
        content_type: str | None = None,
    ) -> None:
        cache_dir = self._cache_dir(cache_id)
        cache_dir.mkdir(parents=True, exist_ok=True)
        raw_file_name = self._write_raw_source(cache_dir, parsed, cache_id, raw_bytes, content_type)
        content_path = cache_dir / "content.txt"
        content_path.write_text(parsed.content, encoding="utf-8")

        archive_metadata = dict(parsed.metadata_json)
        archive_metadata["archive"] = {
            "cache_key": self._cache_key(cache_id),
            "cached_at": datetime.now(UTC).isoformat(),
            "content_path": self._relative_archive_path(content_path),
            "raw_path": self._relative_archive_path(cache_dir / raw_file_name) if raw_file_name else None,
        }
        parsed.metadata_json = archive_metadata

        payload = {
            "title": parsed.title,
            "content": parsed.content,
            "metadata_json": parsed.metadata_json,
            "source_url": parsed.source_url,
            "file_name": parsed.file_name,
            "source_type": parsed.source_type.value,
        }
        (cache_dir / "parsed.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _write_raw_source(
        self,
        cache_dir: Path,
        parsed: ParsedDocument,
        cache_id: str,
        raw_bytes: bytes | None,
        content_type: str | None,
    ) -> str | None:
        if raw_bytes is None:
            return None
        raw_file_name = self._raw_file_name(parsed, cache_id, content_type)
        (cache_dir / raw_file_name).write_bytes(raw_bytes)
        return raw_file_name

    def _raw_file_name(self, parsed: ParsedDocument, cache_id: str, content_type: str | None) -> str:
        if parsed.source_type == SourceType.PDF or self._is_pdf_url(cache_id):
            return parsed.file_name or "source.pdf"
        suffix = Path(urlparse(cache_id).path).suffix.lower()
        if suffix in {".html", ".htm", ".aspx"}:
            return f"source{suffix}"
        if content_type and "xml" in content_type.lower():
            return "source.xml"
        return "source.html"

    def _cache_dir(self, cache_id: str) -> Path:
        archive_root = self.settings.source_archive_path
        archive_root.mkdir(parents=True, exist_ok=True)
        return archive_root / self._cache_key(cache_id)

    def _cache_key(self, cache_id: str) -> str:
        return sha256_digest(cache_id)

    def _relative_archive_path(self, path: Path) -> str:
        backend_root = Path(__file__).resolve().parents[2]
        try:
            return str(path.relative_to(backend_root))
        except ValueError:
            return str(path)

    def _discover_sitemap_urls(
        self,
        request: WebIngestRequest,
        allowed_domains: list[str],
        prioritize_patterns: list[str],
    ) -> tuple[list[str], list[str], int]:
        if not request.discover_sitemaps and not request.sitemap_urls:
            return [], [], 0

        base_urls = self._candidate_base_urls(request, allowed_domains)
        candidate_sitemaps = self._sort_urls(
            [
                *(str(url) for url in request.sitemap_urls),
                *self._discover_robots_sitemap_candidates(base_urls),
                *self._common_sitemap_candidates(base_urls),
            ],
            prioritize_patterns,
        )

        discovered_pages: list[str] = []
        discovered_pdfs: list[str] = []
        seen_sitemaps: set[str] = set()
        seen_urls: set[str] = set()
        sitemap_queue = deque(candidate_sitemaps)

        while sitemap_queue and len(seen_sitemaps) < 20 and len(seen_urls) < 600:
            sitemap_url = sitemap_queue.popleft()
            if sitemap_url in seen_sitemaps:
                continue
            seen_sitemaps.add(sitemap_url)
            nested_sitemaps, urls = self._fetch_sitemap_urls(sitemap_url)
            for nested_sitemap in nested_sitemaps:
                if nested_sitemap not in seen_sitemaps:
                    sitemap_queue.append(nested_sitemap)
            for discovered_url in urls:
                if discovered_url in seen_urls or not is_same_domain(discovered_url, allowed_domains):
                    continue
                seen_urls.add(discovered_url)
                if self._is_pdf_url(discovered_url):
                    discovered_pdfs.append(discovered_url)
                else:
                    discovered_pages.append(discovered_url)

        return (
            self._sort_urls(discovered_pages, prioritize_patterns),
            self._sort_urls(discovered_pdfs, prioritize_patterns),
            len(seen_urls),
        )

    def _candidate_base_urls(self, request: WebIngestRequest, allowed_domains: list[str]) -> list[str]:
        bases: set[str] = set()
        for url in [*request.seed_urls, *request.pdf_urls, *request.sitemap_urls]:
            parsed = urlparse(str(url))
            if parsed.scheme and parsed.netloc:
                bases.add(f"{parsed.scheme}://{parsed.netloc}")
        for domain in allowed_domains:
            normalized = domain.strip().rstrip("/")
            if not normalized:
                continue
            if normalized.startswith("http://") or normalized.startswith("https://"):
                bases.add(normalized)
            else:
                bases.add(f"https://{normalized}")
        return sorted(bases)

    def _discover_robots_sitemap_candidates(self, base_urls: list[str]) -> list[str]:
        candidates: list[str] = []
        with httpx.Client(timeout=12.0, follow_redirects=True, headers={"User-Agent": "GTU-AI-Demo/1.0"}) as client:
            for base_url in base_urls:
                robots_url = f"{base_url.rstrip('/')}/robots.txt"
                try:
                    response = client.get(robots_url)
                    response.raise_for_status()
                except Exception:
                    continue
                content_type = response.headers.get("content-type", "").lower()
                if "text/plain" not in content_type and "text/" not in content_type:
                    continue
                for line in response.text.splitlines():
                    if line.lower().startswith("sitemap:"):
                        sitemap_url = line.split(":", 1)[1].strip()
                        if sitemap_url:
                            candidates.append(sitemap_url)
        return candidates

    def _common_sitemap_candidates(self, base_urls: list[str]) -> list[str]:
        suffixes = [
            "/sitemap.xml",
            "/sitemap_index.xml",
            "/sitemap-index.xml",
            "/sitemap/sitemap.xml",
            "/server-sitemap.xml",
        ]
        return [f"{base_url.rstrip('/')}{suffix}" for base_url in base_urls for suffix in suffixes]

    def _fetch_sitemap_urls(self, sitemap_url: str) -> tuple[list[str], list[str]]:
        with httpx.Client(timeout=15.0, follow_redirects=True, headers={"User-Agent": "GTU-AI-Demo/1.0"}) as client:
            try:
                response = client.get(sitemap_url)
                response.raise_for_status()
            except Exception:
                return [], []

        payload = response.content.lstrip()
        content_type = response.headers.get("content-type", "").lower()
        if "xml" not in content_type and not payload.startswith((b"<?xml", b"<urlset", b"<sitemapindex")):
            return [], []

        try:
            root = ET.fromstring(response.content)
        except ET.ParseError:
            return [], []

        root_name = self._xml_local_name(root.tag)
        loc_values = [normalize_text(node.text or "") for node in root.findall(".//{*}loc") if normalize_text(node.text or "")]
        if root_name == "sitemapindex":
            return loc_values, []
        if root_name == "urlset":
            return [], loc_values

        nested_sitemaps = [value for value in loc_values if value.lower().endswith(".xml") or "sitemap" in value.lower()]
        url_values = [value for value in loc_values if value not in nested_sitemaps]
        return nested_sitemaps, url_values

    def _xml_local_name(self, tag: str) -> str:
        if "}" in tag:
            return tag.split("}", 1)[1].lower()
        return tag.lower()

    def _matches_include_patterns(self, url: str, include_patterns: list[str]) -> bool:
        if not include_patterns:
            return True
        lowered = url.lower()
        return any(pattern.lower() in lowered for pattern in include_patterns)

    def _should_ingest_url(
        self,
        url: str,
        include_patterns: list[str],
        forced_urls: set[str],
    ) -> bool:
        return (
            url in forced_urls
            or self._is_pdf_url(url)
            or self._matches_include_patterns(url, include_patterns)
        )

    def _sort_urls(self, urls: list[str], prioritize_patterns: list[str]) -> list[str]:
        def score(url: str) -> tuple[int, int, str]:
            lowered = url.lower()
            for index, pattern in enumerate(prioritize_patterns):
                if pattern.lower() in lowered:
                    return (0, index, lowered)
            return (1, len(prioritize_patterns), lowered)

        return sorted(dict.fromkeys(urls), key=score)

    def _is_pdf_url(self, url: str) -> bool:
        return urlparse(url).path.lower().endswith(".pdf")

    def _upsert_document(self, parsed: ParsedDocument) -> tuple[int, int]:
        checksum = sha256_digest((parsed.source_url or parsed.file_name or parsed.title) + parsed.content[:2000])
        existing_sources = self._existing_documents_for_source(parsed)
        if existing_sources and any(document.checksum == checksum for document in existing_sources):
            return 0, 0
        for existing_document in existing_sources:
            self.db.delete(existing_document)
        if existing_sources:
            self.db.flush()
        existing = self.db.scalar(select(Document).where(Document.checksum == checksum))
        if existing:
            return 0, 0
        document = Document(
            source_type=parsed.source_type,
            title=parsed.title[:500],
            source_url=parsed.source_url,
            file_name=parsed.file_name,
            checksum=checksum,
            metadata_json=parsed.metadata_json,
        )
        self.db.add(document)
        self.db.flush()

        chunks = chunk_text(parsed.content, self.settings.chunk_size, self.settings.chunk_overlap)
        embeddings = self.embedding_service.embed_many(chunks)
        for index, (content, embedding) in enumerate(zip(chunks, embeddings, strict=True)):
            self.db.add(
                Chunk(
                    document_id=document.id,
                    ordinal=index,
                    content=content,
                    token_count=token_count(content),
                    metadata_json={},
                    embedding=embedding,
                )
            )
        return 1, len(chunks)

    def _existing_documents_for_source(self, parsed: ParsedDocument) -> list[Document]:
        if parsed.source_url:
            return self.db.scalars(select(Document).where(Document.source_url == parsed.source_url)).all()
        if parsed.file_name:
            return self.db.scalars(
                select(Document).where(
                    and_(
                        Document.file_name == parsed.file_name,
                        Document.source_type == parsed.source_type,
                    )
                )
            ).all()
        return []
