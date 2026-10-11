"""Хранилище FAISS-индексов и JSON-метаданных.

Структура на диске (пример):
  storage/collections/<collection_id>/fixed_size/index.faiss
  storage/collections/<collection_id>/fixed_size/metadata.json
  storage/collections/<collection_id>/fixed_size/config.json

Позиция вектора в FAISS однозначно соответствует записи в metadata.json —
при сохранении это проверяется. Запись выполняется атомарно: сначала во
временную директорию, затем публикация. Параллельная запись в один индекс
блокируется (threading.Lock на пару коллекция+стратегия).
"""

from __future__ import annotations

import json
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import faiss
import numpy as np

from ..schemas.indexing import STRATEGIES
from ..utils.common import utc_now_iso
from ..utils.errors import ConflictError, NotFoundError
from ..utils.logging import get_logger
from . import runtime

logger = get_logger(__name__)

METADATA_SCHEMA_VERSION = 1

# Блокировки записи на пару (collection_id, strategy)
_index_locks: Dict[Tuple[str, str], threading.RLock] = {}
_locks_guard = threading.Lock()


def index_lock(collection_id: str, strategy: str) -> threading.RLock:
    key = (collection_id, strategy)
    with _locks_guard:
        if key not in _index_locks:
            _index_locks[key] = threading.RLock()
        return _index_locks[key]


# ---------------------------------------------------------------------------
# Низкоуровневые помощники
# ---------------------------------------------------------------------------

class IndexStore:
    """Работа с индексами на диске."""

    def __init__(self, paths: runtime.StoragePaths):
        self.paths = paths

    # -- пути ----------------------------------------------------------
    def strategy_dir(self, collection_id: str, strategy: str) -> Path:
        return self.paths.collection_dir(collection_id) / strategy

    def index_file(self, collection_id: str, strategy: str) -> Path:
        return self.strategy_dir(collection_id, strategy) / "index.faiss"

    def metadata_file(self, collection_id: str, strategy: str) -> Path:
        return self.strategy_dir(collection_id, strategy) / "metadata.json"

    def config_file(self, collection_id: str, strategy: str) -> Path:
        return self.strategy_dir(collection_id, strategy) / "config.json"

    # -- чтение ---------------------------------------------------------
    def load(
        self, collection_id: str, strategy: str
    ) -> Tuple[faiss.Index, List[Dict[str, Any]], Dict[str, Any]]:
        """Загрузить индекс, метаданные и конфиг. NotFoundError, если нет."""
        if strategy not in STRATEGIES:
            raise NotFoundError(f"Неизвестная стратегия: {strategy}", code="unknown_strategy")
        idx_file = self.index_file(collection_id, strategy)
        meta_file = self.metadata_file(collection_id, strategy)
        cfg_file = self.config_file(collection_id, strategy)
        if not (idx_file.exists() and meta_file.exists() and cfg_file.exists()):
            raise NotFoundError(
                f"Индекс «{strategy}» коллекции «{collection_id}» не найден",
                code="index_not_found",
            )
        index = faiss.read_index(str(idx_file))
        metadata = json.loads(meta_file.read_text(encoding="utf-8"))
        config = json.loads(cfg_file.read_text(encoding="utf-8"))
        if len(metadata) != index.ntotal:
            raise RuntimeError(
                f"Целостность нарушена: {len(metadata)} метаданных, {index.ntotal} векторов"
            )
        return index, metadata, config

    def has_index(self, collection_id: str, strategy: str) -> bool:
        return self.index_file(collection_id, strategy).exists()

    def index_size_bytes(self, collection_id: str, strategy: str) -> int:
        f = self.index_file(collection_id, strategy)
        return f.stat().st_size if f.exists() else 0

    # -- атомарная публикация --------------------------------------------
    def _publish(self, tmp_dir: Path, target_dir: Path) -> None:
        """Атомарно заменить target_dir содержимым tmp_dir (с откатом)."""
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        backup = target_dir.parent / f".{target_dir.name}.bak-{uuid.uuid4().hex[:8]}"
        published = False
        try:
            if target_dir.exists():
                shutil.rmtree(target_dir)
            tmp_dir.rename(target_dir)
            published = True
        except Exception:
            # откат
            if not published and target_dir.parent.exists() and backup.exists() and not target_dir.exists():
                backup.rename(target_dir)
            raise
        finally:
            if backup.exists():
                shutil.rmtree(backup, ignore_errors=True)

    def _write_json_atomic(self, path: Path, obj: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + f".tmp{uuid.uuid4().hex[:6]}")
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    # -- конфигурация -----------------------------------------------------
    def build_config(
        self,
        collection_id: str,
        strategy: str,
        index_id: str,
        model: str,
        dimension: int,
        chunking_params: Dict[str, Any],
        num_vectors: int,
        document_ids: List[str],
        job_id: Optional[str] = None,
        times: Optional[Dict[str, float]] = None,
        warnings: Optional[List[str]] = None,
        errors_count: int = 0,
    ) -> Dict[str, Any]:
        return {
            "schema_version": METADATA_SCHEMA_VERSION,
            "index_version": 1,
            "index_id": index_id,
            "collection_id": collection_id,
            "strategy": strategy,
            "embedding_model": model,
            "dimension": dimension,
            "chunking_params": chunking_params,
            "num_vectors": num_vectors,
            "num_documents": len(document_ids),
            "document_ids": sorted(set(document_ids)),
            "job_id": job_id,
            "created_at": utc_now_iso(),
            "updated_at": utc_now_iso(),
            "time_chunking_ms": (times or {}).get("chunking_ms"),
            "time_embeddings_ms": (times or {}).get("embeddings_ms"),
            "time_total_ms": (times or {}).get("total_ms"),
            "warnings": warnings or [],
            "errors_count": errors_count,
        }

    # -- запись новых/перестроенных индексов --------------------------------
    def save_new(
        self,
        collection_id: str,
        strategy: str,
        vectors: np.ndarray,
        metadata: List[Dict[str, Any]],
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Создать индекс (или атомарно перестроить существующий)."""
        with index_lock(collection_id, strategy):
            dim = int(vectors.shape[1])
            normalized = _normalize(vectors)
            index = faiss.IndexFlatIP(dim)
            index.add(np.ascontiguousarray(normalized, dtype="float32"))
            self._save_after_build(collection_id, strategy, index, metadata, config)
            config = self._config_with_sizes(collection_id, strategy, config, len(metadata))
            return config

    def append(
        self,
        collection_id: str,
        strategy: str,
        vectors: np.ndarray,
        new_metadata: List[Dict[str, Any]],
        existing_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Добавить документы в существующий индекс (конфигурация совместима)."""
        with index_lock(collection_id, strategy):
            old_index, old_metadata, _ = self.load(collection_id, strategy)
            dim = old_index.d
            if vectors.shape[1] != dim:
                raise ConflictError(
                    f"Размерность новых векторов ({vectors.shape[1]}) не совпадает "
                    f"с размерностью индекса ({dim})",
                    code="dimension_mismatch",
                )
            old_vecs = old_index.reconstruct_n(0, old_index.ntotal)
            all_vecs = np.vstack([old_vecs, _normalize(vectors)])
            new_meta = old_metadata + new_metadata
            index = faiss.IndexFlatIP(dim)
            index.add(np.ascontiguousarray(all_vecs, dtype="float32"))
            # обновить конфиг
            doc_ids = sorted(set(existing_config.get("document_ids", [])) |
                             {m["document_id"] for m in new_metadata})
            existing_config["document_ids"] = doc_ids
            existing_config["num_documents"] = len(doc_ids)
            existing_config["num_vectors"] = len(new_meta)
            existing_config["updated_at"] = utc_now_iso()
            self._save_after_build(collection_id, strategy, index, new_meta, existing_config)
            existing_config = self._config_with_sizes(collection_id, strategy, existing_config, len(new_meta))
            return existing_config

    def _save_after_build(
        self,
        collection_id: str,
        strategy: str,
        index: faiss.Index,
        metadata: List[Dict[str, Any]],
        config: Dict[str, Any],
    ) -> None:
        if len(metadata) != index.ntotal:
            raise RuntimeError(
                f"Несовпадение числа записей: {len(metadata)} метаданных, {index.ntotal} векторов"
            )
        target = self.strategy_dir(collection_id, strategy)
        tmp_dir = self.paths.root / "tmp" / f".pub-{uuid.uuid4().hex[:8]}"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        try:
            faiss.write_index(index, str(tmp_dir / "index.faiss"))
            self._write_json_atomic(tmp_dir / "metadata.json", metadata)
            self._write_json_atomic(tmp_dir / "config.json", config)
            # контрольная проверка перед публикацией
            check = faiss.read_index(str(tmp_dir / "index.faiss"))
            if check.ntotal != len(metadata):
                raise RuntimeError("Ошибка целостности перед публикацией")
            self._publish(tmp_dir, target)
        finally:
            if tmp_dir.exists():
                shutil.rmtree(tmp_dir, ignore_errors=True)

    def _config_with_sizes(
        self, collection_id: str, strategy: str, config: Dict[str, Any], num_vectors: int
    ) -> Dict[str, Any]:
        config = {**config, "num_vectors": num_vectors, "updated_at": utc_now_iso()}
        config["size_bytes"] = self.index_size_bytes(collection_id, strategy)
        return config

    def delete(self, collection_id: str, strategy: str) -> bool:
        with index_lock(collection_id, strategy):
            d = self.strategy_dir(collection_id, strategy)
            if not d.exists():
                return False
            shutil.rmtree(d, ignore_errors=True)
            return True

    def delete_collection_files(self, collection_id: str) -> None:
        d = self.paths.collection_dir(collection_id)
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)


def _normalize(vectors: np.ndarray) -> np.ndarray:
    """Нормализовать векторы для cosine similarity через Inner Product."""
    v = np.asarray(vectors, dtype="float32")
    norms = np.linalg.norm(v, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (v / norms).astype("float32")


def get_store() -> IndexStore:
    return IndexStore(runtime.get_paths())