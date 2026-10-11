"""Клиент эмбеддингов через локальный Ollama.

Используются только локальные модели (по умолчанию nomic-embed-text).
Никаких облачных API. Предусмотрены таймауты, повторные попытки с backoff
и проверка корректности векторов (размерность, конечность значений).
"""

from __future__ import annotations

import math
import threading
import time
from typing import Any, Dict, List, Optional

import requests

from ..schemas.ollama import OllamaStatusOut, OllamaTestOut
from ..utils.logging import get_logger

logger = get_logger(__name__)


class EmbeddingError(Exception):
    """Ошибка получения эмбеддингов."""


class OllamaEmbeddingProvider:
    """Провайдер эмбеддингов через HTTP API Ollama."""

    def __init__(
        self,
        url: str,
        model: str,
        batch_size: int = 32,
        retries: int = 3,
        timeout: float = 120.0,
        connection_timeout: float = 10.0,
    ):
        self.url = url.rstrip("/")
        self.model = model
        self.batch_size = max(1, batch_size)
        self.retries = retries
        self.timeout = timeout
        self.connection_timeout = connection_timeout
        self._dim: Optional[int] = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Низкоуровневые запросы
    # ------------------------------------------------------------------
    def _request(self, method: str, path: str, payload: Optional[dict] = None) -> Any:
        attempt = 0
        while True:
            try:
                resp = requests.request(
                    method,
                    self.url + path,
                    json=payload,
                    timeout=(self.connection_timeout, self.timeout),
                )
                if resp.status_code == 404 and path == "/api/embed":
                    raise _NoEmbedEndpoint()
                if resp.status_code >= 500:
                    raise EmbeddingError(f"Ollama вернул ошибку {resp.status_code}: {resp.text[:300]}")
                if resp.status_code >= 400:
                    raise EmbeddingError(f"Ollama вернул ошибку {resp.status_code}: {resp.text[:300]}")
                return resp.json()
            except requests.Timeout:
                err: Exception = EmbeddingError(
                    f"Ollama не ответил за {self.timeout} c (timeout)"
                )
            except requests.ConnectionError:
                err = EmbeddingError("Ollama недоступен (соединение отклонено)")
            except _NoEmbedEndpoint:
                raise
            except EmbeddingError:
                raise
            except requests.RequestException as e:
                err = EmbeddingError(f"Ошибка запроса к Ollama: {e}")
            attempt += 1
            if attempt > self.retries:
                raise err  # type: ignore[arg-type]
            delay = min(2 ** attempt, 8)
            logger.warning("Ollama: попытка %d/%d не удалась (%s), пауза %ds",
                           attempt, self.retries, err, delay)
            time.sleep(delay)

    def _supports_embed_endpoint(self) -> bool:
        try:
            data = self._request("POST", "/api/embed", {
                "model": self.model, "input": ["probe"],
            })
            return isinstance(data.get("embeddings"), list)
        except _NoEmbedEndpoint:
            return False
        except EmbeddingError:
            return False

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------
    def embed(self, texts: List[str]) -> List[List[float]]:
        """Получить эмбеддинги для списка текстов (пакетно)."""
        if not texts:
            return []
        if self._supports_embed_endpoint():
            data = self._request("POST", "/api/embed", {"model": self.model, "input": texts})
            vectors = data.get("embeddings")
        else:
            vectors = []
            for t in texts:
                data = self._request("POST", "/api/embeddings", {"model": self.model, "prompt": t})
                vectors.append(data["embeddings"][0])
        out = [list(v) for v in vectors]
        self._validate(out)
        return out

    def embed_one(self, text: str) -> List[float]:
        return self.embed([text])[0]

    def _validate(self, vectors: List[List[float]]) -> None:
        if not vectors:
            raise EmbeddingError("Ollama вернул пустой список эмбеддингов")
        dim = self._dim
        for v in vectors:
            for x in v:
                if not math.isfinite(x):
                    raise EmbeddingError("Эмбеддинг содержит нечисловые значения (nan/inf)")
            if dim is None:
                dim = len(v)
                with self._lock:
                    self._dim = dim
            elif len(v) != dim:
                raise EmbeddingError(
                    f"Несогласованная размерность эмбеддинга: {len(v)} != {dim}"
                )

    def probe_dimension(self) -> int:
        """Узнать размерность модели, сделав один тестовый эмбеддинг."""
        if self._dim is not None:
            return self._dim
        vec = self.embed_one("probe")
        with self._lock:
            self._dim = len(vec)
        return self._dim

    def list_models(self) -> List[dict]:
        try:
            data = self._request("GET", "/api/tags", None)
        except EmbeddingError as e:
            return [{"error": str(e)}]
        return data.get("models", [])

    def status(self) -> Dict[str, Any]:
        """Реальное состояние: доступность Ollama, наличие модели, размерность."""
        try:
            data = self._request("GET", "/api/tags", None)
            models = [
                m.get("name")
                for m in data.get("models", [])
                if m.get("capabilities") is None or "embedding" in m.get("capabilities", [])
            ]
            version = None
            try:
                v = self._request("GET", "/api/version", None)
                version = v.get("version")
            except EmbeddingError:
                pass
            model_available = self.model in models or any(
                m.split(":")[0] == self.model for m in models
            )
            return {
                "ok": True,
                "available": True,
                "version": version,
                "model": self.model,
                "model_available": model_available,
                "models": models,
                "message": "Ollama доступен" if model_available else
                           f"Ollama доступен, но модель «{self.model}» не установлена",
                "error": None,
            }
        except (_NoEmbedEndpoint, EmbeddingError) as e:
            return {
                "ok": False,
                "available": False,
                "version": None,
                "model": self.model,
                "model_available": None,
                "models": [],
                "message": "Ollama недоступен",
                "error": str(e),
            }

    def test(self) -> OllamaTestOut:
        """Полная проверка подключения (для кнопки «Проверить подключение»)."""
        url = self.url
        # 1. доступность
        try:
            data = self._request("GET", "/api/tags", None)
        except _NoEmbedEndpoint:
            data = {}
        except EmbeddingError as e:
            return OllamaTestOut(ok=False, step="failed",
                                 message="Ollama недоступен", ollama_url=url, error=str(e),
                                 pull_command=f"ollama pull {self.model}")
        if isinstance(data, dict) and data.get("error"):
            return OllamaTestOut(ok=False, step="failed", message="Ollama недоступен",
                                 ollama_url=url, error=str(data.get("error")),
                                 pull_command=f"ollama pull {self.model}")
        models_raw = data.get("models", []) if isinstance(data, dict) else []
        embed_models = [
            m.get("name")
            for m in models_raw
            if m.get("capabilities") is None or "embedding" in m.get("capabilities", [])
        ]
        found = self.model in embed_models or any(
            m.split(":")[0] == self.model for m in embed_models
        )
        # 2. наличие модели
        if not found:
            return OllamaTestOut(
                ok=False, step="model_found", message=f"Модель «{self.model}» не установлена",
                ollama_url=url, model=self.model, model_available=False,
                pull_command=f"ollama pull {self.model}",
            )
        # 3. тестовый эмбеддинг
        try:
            vec = self.embed_one("Тестовый запрос RAG Document Indexing Lab")
        except EmbeddingError as e:
            return OllamaTestOut(
                ok=False, step="embedding_ok", message="Ошибка при создании тестового эмбеддинга",
                ollama_url=url, model=self.model, model_available=True, error=str(e),
                pull_command=f"ollama pull {self.model}",
            )
        finite = all(math.isfinite(x) for x in vec)
        return OllamaTestOut(
            ok=True, step="embedding_ok",
            message=f"Подключение работает, размерность эмбеддинга: {len(vec)}",
            ollama_url=url, model=self.model, model_available=True,
            dimension=len(vec), vector_sample=vec[:8], vector_finite=finite,
        )


class _NoEmbedEndpoint(Exception):
    """Эндпоинт /api/embed не поддерживается старой версией Ollama."""


# ---------------------------------------------------------------------------
# Провайдер (singleton с возможностью подмены в тестах)
# ---------------------------------------------------------------------------

class ProviderHolder:
    """Держатель провайдера эмбеддингов.

    В production используются только реальные Ollama-модели. Подмена на
    фейковый клиент возможна исключительно в тестах и делается явно.
    """

    def __init__(self) -> None:
        self._fake: Optional[Any] = None
        self._real: Optional[OllamaEmbeddingProvider] = None
        self._lock = threading.Lock()

    def set_fake(self, client: Any) -> None:
        """Только для тестов."""
        self._fake = client

    def reset_fake(self) -> None:
        self._fake = None

    def reset(self) -> None:
        with self._lock:
            self._real = None

    def get_provider(self) -> Any:
        if self._fake is not None:
            return self._fake
        from . import runtime

        s = runtime.effective_settings()
        with self._lock:
            if self._real is None or self._real.url != s.ollama_url or self._real.model != s.embedding_model:
                self._real = OllamaEmbeddingProvider(
                    url=s.ollama_url,
                    model=s.embedding_model,
                    batch_size=s.embedding_batch_size,
                    retries=s.embedding_retries,
                    timeout=s.ollama_timeout,
                    connection_timeout=s.ollama_connection_timeout,
                )
            return self._real


ollama_provider = ProviderHolder()