from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable

from app.core.config import get_settings
from app.services.chunker import tokenize
from app.services.provider_client import create_openai_compatible_client


class EmbeddingService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = create_openai_compatible_client(self.settings)

    def embed(self, text: str) -> list[float]:
        return self.embed_many([text])[0]

    def embed_many(self, texts: Iterable[str]) -> list[list[float]]:
        payload = [text.strip() for text in texts]
        if not payload:
            return []
        if self.client:
            vectors: list[list[float]] = []
            for start in range(0, len(payload), self.settings.embedding_batch_size):
                batch = payload[start : start + self.settings.embedding_batch_size]
                try:
                    response = self.client.embeddings.create(
                        **self._embedding_request_kwargs(batch, include_dimensions=True)
                    )
                except Exception:
                    try:
                        response = self.client.embeddings.create(
                            **self._embedding_request_kwargs(batch, include_dimensions=False)
                        )
                    except Exception:
                        vectors.extend(self._hashed_embedding(text) for text in batch)
                        continue
                vectors.extend(item.embedding for item in response.data)
            return vectors
        return [self._hashed_embedding(text) for text in payload]

    def _embedding_request_kwargs(self, payload: list[str], *, include_dimensions: bool) -> dict[str, object]:
        kwargs: dict[str, object] = {
            "model": self.settings.active_embedding_model,
            "input": payload,
        }
        if include_dimensions and self.settings.embedding_dimensions > 0:
            kwargs["dimensions"] = self.settings.embedding_dimensions
        return kwargs

    def _hashed_embedding(self, text: str) -> list[float]:
        dimensions = self.settings.embedding_dimensions
        vector = [0.0] * dimensions
        for token in tokenize(text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            weight = 1.0 + (digest[5] / 255.0)
            vector[index] += sign * weight
        norm = math.sqrt(sum(component * component for component in vector))
        if norm == 0:
            return vector
        return [component / norm for component in vector]
