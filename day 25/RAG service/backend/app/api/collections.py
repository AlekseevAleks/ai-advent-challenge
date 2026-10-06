"""Эндпоинты коллекций и индексов."""

from __future__ import annotations

import json
from typing import List

from fastapi import APIRouter, status

from ..repositories import collections_repo
from ..schemas.indexing import CollectionCreate, CollectionOut, IndexConfigOut, IndexStatsOut
from ..services.faiss_store import get_store
from ..utils.common import median, utc_now_iso
from ..utils.errors import ConflictError, NotFoundError
from ..utils.ids import new_id

router = APIRouter(prefix="/api", tags=["Коллекции и индексы"])


def _config_out(rec: dict) -> IndexConfigOut:
    config = rec["config"] if isinstance(rec["config"], dict) else json.loads(rec["config"])
    store = get_store()
    return IndexConfigOut(
        index_id=config.get("index_id", rec["index_id"]),
        collection_id=rec["collection_id"],
        strategy=rec["strategy"],
        embedding_model=config.get("embedding_model", ""),
        dimension=config.get("dimension", 0),
        schema_version=config.get("schema_version", 1),
        index_version=config.get("index_version", 1),
        num_vectors=config.get("num_vectors", 0),
        num_documents=config.get("num_documents", 0),
        document_ids=config.get("document_ids", []),
        chunking_params=config.get("chunking_params", {}),
        created_at=config.get("created_at", rec.get("created_at") or ""),
        updated_at=config.get("updated_at", rec.get("updated_at") or ""),
        size_bytes=store.index_size_bytes(rec["collection_id"], rec["strategy"]),
        time_chunking_ms=config.get("time_chunking_ms"),
        time_embeddings_ms=config.get("time_embeddings_ms"),
        time_total_ms=config.get("time_total_ms"),
        job_id=config.get("job_id"),
        warnings=config.get("warnings", []),
        errors_count=config.get("errors_count", 0),
    )


def _collection_out(row: dict) -> CollectionOut:
    recs = collections_repo.list_indexes(row["id"])
    indexes = [_config_out(r) for r in recs if get_store().has_index(r["collection_id"], r["strategy"])]
    return CollectionOut(
        id=row["id"], name=row["name"], description=row.get("description") or "",
        created_at=row.get("created_at") or "", updated_at=row.get("updated_at") or "",
        strategies=sorted({i.strategy for i in indexes}),
        indexes=indexes,
    )


@router.get("/collections", summary="Список коллекций", response_model=List[CollectionOut])
def list_collections() -> List[CollectionOut]:
    return [_collection_out(r) for r in collections_repo.list_collections()]


@router.post("/collections", summary="Создать коллекцию", status_code=status.HTTP_201_CREATED)
def create_collection(req: CollectionCreate) -> CollectionOut:
    if collections_repo.get_collection_by_name(req.name) is not None:
        raise ConflictError(f"Коллекция «{req.name}» уже существует", code="collection_exists")
    row = collections_repo.create_collection(new_id("collection"), req.name, req.description)
    return _collection_out(row)


@router.get("/collections/{collection_id}", summary="Коллекция", response_model=CollectionOut)
def get_collection(collection_id: str) -> CollectionOut:
    row = collections_repo.get_collection(collection_id)
    if row is None:
        raise NotFoundError("Коллекция не найдена", code="collection_not_found")
    return _collection_out(row)


@router.delete("/collections/{collection_id}", summary="Удалить коллекцию", status_code=204)
def delete_collection(collection_id: str) -> None:
    row = collections_repo.get_collection(collection_id)
    if row is None:
        raise NotFoundError("Коллекция не найдена", code="collection_not_found")
    get_store().delete_collection_files(collection_id)
    collections_repo.delete_collection(collection_id)


@router.get("/collections/{collection_id}/indexes", summary="Индексы коллекции", response_model=List[IndexConfigOut])
def list_collection_indexes(collection_id: str) -> List[IndexConfigOut]:
    if collections_repo.get_collection(collection_id) is None:
        raise NotFoundError("Коллекция не найдена", code="collection_not_found")
    recs = collections_repo.list_indexes(collection_id)
    return [_config_out(r) for r in recs]


@router.get("/indexes/{index_id}/stats", summary="Статистика индекса", response_model=IndexStatsOut)
def index_stats(index_id: str) -> IndexStatsOut:
    rec = collections_repo.find_index_by_id(index_id)
    if rec is None:
        raise NotFoundError("Индекс не найден", code="index_not_found")
    out = _config_out(rec)
    store = get_store()
    meta_file = store.metadata_file(rec["collection_id"], rec["strategy"])
    sizes: List[int] = []
    empty = 0
    if meta_file.exists():
        metas = json.loads(meta_file.read_text(encoding="utf-8"))
        sizes = [m["char_count"] for m in metas if isinstance(m.get("char_count"), int)]
        empty = sum(1 for m in metas if m.get("char_count", 0) == 0)
    data = out.model_dump()
    data.update({
        "chunks": out.num_vectors,
        "mean_chars": round(sum(sizes) / len(sizes), 1) if sizes else 0.0,
        "median_chars": median([float(x) for x in sizes]) if sizes else 0.0,
        "min_chars": min(sizes) if sizes else 0,
        "max_chars": max(sizes) if sizes else 0,
        "empty_chunks": empty,
    })
    if sizes:
        import statistics
        data["std_chars"] = round(statistics.pstdev(sizes), 1)
    return IndexStatsOut(**data)


@router.get("/indexes/{index_id}/chunks", summary="Чанки индекса")
def index_chunks(index_id: str, limit: int = 200, offset: int = 0) -> dict:
    rec = collections_repo.find_index_by_id(index_id)
    if rec is None:
        raise NotFoundError("Индекс не найден", code="index_not_found")
    store = get_store()
    meta_file = store.metadata_file(rec["collection_id"], rec["strategy"])
    if not meta_file.exists():
        return {"chunks": [], "total": 0}
    metas = json.loads(meta_file.read_text(encoding="utf-8"))
    window = metas[offset:offset + limit]
    return {"chunks": window, "total": len(metas), "index_id": index_id}


@router.get("/indexes/{index_id}/chunks/{chunk_id}", summary="Чанк по идентификатору")
def get_chunk(index_id: str, chunk_id: str) -> dict:
    rec = collections_repo.find_index_by_id(index_id)
    if rec is None:
        raise NotFoundError("Индекс не найден", code="index_not_found")
    store = get_store()
    meta_file = store.metadata_file(rec["collection_id"], rec["strategy"])
    if not meta_file.exists():
        raise NotFoundError("Чанк не найден", code="chunk_not_found")
    metas = json.loads(meta_file.read_text(encoding="utf-8"))
    for m in metas:
        if m.get("chunk_id") == chunk_id:
            return m
    raise NotFoundError("Чанк не найден", code="chunk_not_found")


@router.delete("/indexes/{index_id}", summary="Удалить индекс", status_code=204)
def delete_index(index_id: str) -> None:
    rec = collections_repo.find_index_by_id(index_id)
    if rec is None:
        raise NotFoundError("Индекс не найден", code="index_not_found")
    store = get_store()
    store.delete(rec["collection_id"], rec["strategy"])
    collections_repo.delete_index(rec["collection_id"], rec["strategy"])