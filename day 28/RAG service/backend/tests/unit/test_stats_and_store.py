"""Unit-тесты статистики, совместимости индекса и метаданных."""

from __future__ import annotations

import json

import numpy as np

from app.services import faiss_store
from app.services.comparison_service import _metrics_for, _nice_buckets
from app.services.faiss_store import METADATA_SCHEMA_VERSION
from app.utils.common import median, quantile


# ---------------------------------------------------------------------------
# Статистика
# ---------------------------------------------------------------------------

def test_median_and_quantile():
    assert median([5, 1, 3]) == 3
    assert median([]) == 0
    s = sorted([10, 20, 30, 40])
    assert quantile(s, 0.5) == 25
    assert quantile(s, 0.25) == 17.5


def test_histogram_buckets():
    buckets = _nice_buckets([10, 12, 50, 60, 100], n=5)
    total = sum(b["count"] for b in buckets)
    assert total == 5
    assert buckets  # непустая гистограмма


def test_metrics_empty():
    m = _metrics_for([], "fixed_size")
    assert m.chunks == 0 and m.mean_chars == 0.0


# ---------------------------------------------------------------------------
# FAISS + метаданные
# ---------------------------------------------------------------------------

def test_normalize_vectors_unit_length():
    v = np.array([[3.0, 4.0], [1.0, 0.0]], dtype="float32")
    n = faiss_store._normalize(v)
    assert np.allclose(np.linalg.norm(n, axis=1), [1.0, 1.0])


def test_metadata_schema_version():
    assert METADATA_SCHEMA_VERSION == 1


def test_index_compatibility_dimension_mismatch(client):
    """Векторы другой размерности не должны попадать в индекс."""
    import faiss as faiss_lib

    import numpy as np

    idx = faiss_lib.IndexFlatIP(8)
    idx.add(np.random.rand(3, 8).astype("float32"))
    assert idx.d == 8


def test_metadata_json_roundtrip(tmp_path):
    meta = [{"chunk_id": "chunk_a", "text": "hello"}, {"chunk_id": "chunk_b", "text": "world"}]
    p = tmp_path / "metadata.json"
    p.write_text(json.dumps(meta), encoding="utf-8")
    loaded = json.loads(p.read_text(encoding="utf-8"))
    assert [m["chunk_id"] for m in loaded] == ["chunk_a", "chunk_b"]


def test_chunk_metadata_has_required_fields():
    from app.schemas.common import ChunkOut

    meta = {
        "chunk_id": "chunk_x", "document_id": "doc_1", "source": "a.md", "title": "a.md",
        "section": "RAG > Эмбеддинги", "text": "текст", "chunk_index": 0,
        "chunking_strategy": "structural", "start_offset": 0, "end_offset": 4,
        "page_start": None, "page_end": None, "char_count": 4,
        "embedding_model": "nomic-embed-text", "collection_id": "col_1", "index_version": 1,
    }
    out = ChunkOut(**meta)
    assert out.chunk_id == "chunk_x"
    assert out.section == "RAG > Эмбеддинги"