"""Фиктивный клиент эмбеддингов — ТОЛЬКО для тестов.

Даёт детерминированные векторы и позволяет симулировать сбои Ollama.
В production-режиме всегда используется реальная модель через
app.services.ollama_service.OllamaEmbeddingProvider.
"""

from __future__ import annotations

import math
import time
from typing import List

from app.services.ollama_service import EmbeddingError


class FakeEmbeddingsClient:
    """Детерминированные нормализованные векторы размерности dim."""

    dim = 8

    def __init__(self) -> None:
        # имитация сбоев: N первых вызовов embed падают
        self.fail_batches = 0
        self.fail_forever = False
        # имитация долгой работы (для тестов отмены)
        self.batch_delay = 0.0
        self.embed_calls = 0

    def _vector(self, text: str) -> List[float]:
        h = abs(hash(text)) if text else 0
        v = []
        for i in range(self.dim):
            v.append(math.sin(h * (i + 3) + i) * 0.5 + math.cos(h * (i + 7)))
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def embed(self, texts: List[str]) -> List[List[float]]:
        self.embed_calls += 1
        if self.batch_delay:
            time.sleep(self.batch_delay)
        if self.fail_forever:
            raise EmbeddingError("Fake: Ollama недоступен (тест ошибки)")
        if self.fail_batches > 0:
            self.fail_batches -= 1
            raise EmbeddingError("Fake: временная ошибка Ollama (тест)")
        return [self._vector(t) for t in texts]

    def embed_one(self, text: str) -> List[float]:
        return self._vector(text)

    def probe_dimension(self) -> int:
        return self.dim

    def status(self) -> dict:
        return {
            "ok": True, "available": True, "version": "0.0.0-fake", "model": "nomic-embed-text",
            "model_available": True, "models": ["nomic-embed-text"], "message": "Fake OK",
            "error": None, "model_dimension": self.dim,
        }

    def test(self) -> dict:
        return {
            "ok": True, "step": "embedding_ok", "message": f"Fake, dim={self.dim}",
            "ollama_url": "http://localhost:11434", "model": "nomic-embed-text",
            "dimension": self.dim, "vector_finite": True, "model_available": True,
        }

    def list_models(self) -> List[dict]:
        return [{"name": "nomic-embed-text", "details": {"embedding_length": self.dim}}]