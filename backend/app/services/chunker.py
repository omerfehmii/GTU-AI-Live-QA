from __future__ import annotations

import hashlib
import re
from urllib.parse import urljoin, urlparse


TURKISH_STOPWORDS = {
    "acaba",
    "ama",
    "ancak",
    "aslinda",
    "az",
    "bir",
    "biri",
    "biz",
    "bu",
    "cok",
    "da",
    "de",
    "daha",
    "en",
    "gibi",
    "hangi",
    "hem",
    "icin",
    "kac",
    "kaç",
    "kactir",
    "kaçtır",
    "kadar",
    "ile",
    "ise",
    "mi",
    "mu",
    "mü",
    "ne",
    "nasil",
    "nasıl",
    "neden",
    "nerede",
    "ve",
    "veya",
    "ya",
}


def normalize_text(value: str) -> str:
    text = value.replace("\x00", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def tokenize(value: str) -> list[str]:
    normalized = normalize_text(value).lower()
    tokens = re.findall(r"[a-zA-Z0-9çğıöşüÇĞİÖŞÜ]+", normalized)
    return [token for token in tokens if token not in TURKISH_STOPWORDS and len(token) > 2]


def token_count(value: str) -> int:
    return len(tokenize(value))


def chunk_text(value: str, chunk_size: int, overlap: int) -> list[str]:
    text = normalize_text(value)
    if not text:
        return []
    words = text.split(" ")
    chunks: list[str] = []
    start = 0
    while start < len(words):
        window = words[start : start + chunk_size]
        if not window:
            break
        chunks.append(" ".join(window))
        if start + chunk_size >= len(words):
            break
        start += max(chunk_size - overlap, 1)
    return chunks


def sha256_digest(value: bytes | str) -> str:
    payload = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(payload).hexdigest()


def safe_join(base_url: str, candidate: str) -> str:
    return urljoin(base_url, candidate)


def is_same_domain(url: str, allowed_domains: list[str]) -> bool:
    if not allowed_domains:
        return True
    host = urlparse(url).netloc.lower()
    return any(host == domain.lower() or host.endswith(f".{domain.lower()}") for domain in allowed_domains)
