"""Сервис индексации: оркестрация задания.

Последовательность: подготовка → извлечение → chunking → эмбеддинги (Ollama)
→ построение FAISS → сохранение метаданных → проверка целостности → финал.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from ..models.document import Document
from ..repositories import collections_repo, documents_repo
from ..schemas.indexing import (
    FixedSizeParams,
    JobRequest,
    JobResult,
    JobResultIndex,
    STRATEGIES,
    StructuralParams,
)
from ..utils.common import utc_now_iso
from ..utils.errors import ConflictError, NotFoundError, ValidationError2
from ..utils.ids import new_id
from ..utils.logging import get_logger
from . import runtime
from .chunking import chunk_fixed_size, chunk_structural
from .document_loader import loader
from .faiss_store import get_store
from .job_service import JobCancelled, JobManager
from .ollama_service import EmbeddingError, ollama_provider

logger = get_logger(__name__)

STAGE_WEIGHTS = {
    "prepare": 0.05,
    "extract": 0.10,
    "chunking": 0.15,
    "embeddings": 0.55,
    "faiss": 0.05,
    "metadata": 0.05,
    "integrity": 0.03,
    "done": 0.02,
}


class IndexingService:
    def __init__(self, manager: JobManager):
        self.manager = manager

    # ------------------------------------------------------------------
    # Валидация при создании (быстрый отказ, понятные ошибки)
    # ------------------------------------------------------------------
    def validate(self, req: JobRequest) -> Dict[str, Any]:
        """Синхронная проверка перед созданием задания. Возвращает метаинфо."""
        settings = runtime.effective_settings()
        model = req.embedding_model or settings.embedding_model

        docs = {d.id: d for d in loader.get_many(req.document_ids)}
        missing = [i for i in req.document_ids if i not in docs]
        if missing:
            raise NotFoundError(
                f"Документы не найдены: {', '.join(missing[:5])}", code="document_not_found"
            )
        # проверяем реальное наличие извлекаемого текста (не только статус)
        empty_docs: List[str] = []
        for did in req.document_ids:
            doc = docs[did]
            try:
                res = loader.load_text(doc)
            except Exception:  # noqa: BLE001
                empty_docs.append(doc.source)
                continue
            if res is None or not res.text.strip():
                empty_docs.append(doc.source)
        if empty_docs:
            raise ConflictError(
                "Документы не содержат извлекаемого текста (например, PDF со сканами — "
                "нужен OCR): " + ", ".join(empty_docs[:5]),
                code="empty_text",
            )

        store = get_store()
        for strategy in req.strategies:
            if req.mode == "new_collection":
                continue
            existing = collections_repo.get_index(req.collection_id or "", strategy)
            exists = existing is not None and store.has_index(req.collection_id or "", strategy)
            if req.mode == "new_index" and exists:
                raise ConflictError(
                    f"Индекс «{strategy}» уже существует в коллекции. "
                    "Выберите «Перестроить» или «Добавить документы».",
                    code="index_exists",
                )
            if req.mode == "rebuild" and not exists:
                raise NotFoundError(
                    f"Индекс «{strategy}» не существует — перестраивать нечего.",
                    code="index_not_found",
                )
            if req.mode == "add":
                if not exists:
                    raise NotFoundError(
                        f"Индекс «{strategy}» не существует — режим «добавить» невозможен. "
                        "Создайте индекс сначала.",
                        code="index_not_found",
                    )
                import json as _json

                cfg = _json.loads(existing["config"]) if isinstance(existing["config"], str) else existing["config"]
                self._check_append_compatible(cfg, strategy, req, model)

        if req.mode == "new_collection":
            if collections_repo.get_collection_by_name(req.collection_name or "") is not None:
                raise ConflictError(
                    f"Коллекция «{req.collection_name}» уже существует", code="collection_exists"
                )
        else:
            if collections_repo.get_collection(req.collection_id or "") is None:
                raise NotFoundError(
                    f"Коллекция «{req.collection_id}» не найдена", code="collection_not_found"
                )
        return {"model": model, "settings": settings}

    def _check_append_compatible(self, existing_cfg: Dict[str, Any], strategy: str,
                                 req: JobRequest, model: str) -> None:
        """Запрет небезопасного добавления векторов в несовместимый индекс."""
        problems: List[str] = []
        if existing_cfg.get("embedding_model") != model:
            problems.append(
                f"модель эмбеддингов: {existing_cfg.get('embedding_model')} → {model}"
            )
        req_params = self._params_for(req, strategy)
        old_params = existing_cfg.get("chunking_params") or {}
        if old_params != req_params.model_dump():
            problems.append("параметры chunking изменены")
        if problems:
            raise ConflictError(
                "Добавление невозможно: индекс несовместим с текущей конфигурацией "
                f"(«{strategy}»: {'; '.join(problems)}). Создайте новый индекс или перестройте.",
                code="incompatible_index",
            )

    def _params_for(self, req: JobRequest, strategy: str):
        s = runtime.effective_settings()
        if strategy == "fixed_size":
            p = req.fixed_size
            return FixedSizeParams(
                chunk_size=p.chunk_size if p else s.default_chunk_size,
                overlap=p.overlap if p else s.default_chunk_overlap,
                unit=(p.unit if p else "chars"),
            )
        p = req.structural
        return StructuralParams(
            max_chunk_size=p.max_chunk_size if p else s.default_structural_max_chunk_size,
            min_chunk_size=p.min_chunk_size if p else s.default_structural_min_chunk_size,
            merge_small_sections=p.merge_small_sections if p else True,
        )

    # ------------------------------------------------------------------
    # Запуск
    # ------------------------------------------------------------------
    def submit(self, req: JobRequest) -> str:
        meta = self.validate(req)
        job_id = self.manager.create(req)
        self.manager.start(job_id, lambda jid: self._run(jid, req.model_copy(deep=True)))
        return job_id

    # ------------------------------------------------------------------
    # Выполнение
    # ------------------------------------------------------------------
    def _run(self, job_id: str, req: JobRequest) -> None:
        holder: Dict[str, Optional[str]] = {"collection_id": None}
        try:
            self._pipeline(job_id, req, holder)
        except JobCancelled:
            # откат пустой коллекции, если индексы не были опубликованы
            cid = holder.get("collection_id")
            if cid and req.mode == "new_collection":
                _cleanup_empty_collection(cid)
            raise

    def _pipeline(self, job_id: str, req: JobRequest, holder: Dict[str, Optional[str]]) -> None:
        m = self.manager
        settings = runtime.effective_settings()
        model = req.embedding_model or settings.embedding_model
        batch_size = req.embedding_batch_size or settings.embedding_batch_size
        store = get_store()

        start_epoch = time.time()
        m.set_stage(job_id, "prepare", 0.0, "Подготовка документов…")
        m.check_cancel(job_id)

        # --- коллекция ---
        collection_id, collection_name = self._resolve_collection(req)
        if req.mode == "new_collection":
            holder["collection_id"] = collection_id
        m.update(job_id, collection_id=collection_id, collection_name=collection_name)

        # --- документы и текст ---
        m.set_stage(job_id, "extract", STAGE_WEIGHTS["prepare"], "Извлечение/загрузка текста…")
        docs = {d.id: d for d in loader.get_many(req.document_ids)}
        prepared: List[Document] = []
        for did in req.document_ids:
            m.check_cancel(job_id)
            doc = docs[did]
            res = loader.load_text(doc)
            if res is None or res.errors and not res.text:
                m.add_error(job_id, f"{doc.source}: не удалось извлечь текст")
                continue
            setattr(doc, "_pages", res.pages or [])
            setattr(doc, "_text", res.text)
            setattr(doc, "_segments", res.segments or [])
            prepared.append(doc)
        if not prepared:
            raise ValidationError2("Нет документов с извлечённым текстом для индексации")

        # --- chunking по каждой стратегии ---
        m.set_stage(job_id, "chunking", STAGE_WEIGHTS["prepare"] + STAGE_WEIGHTS["extract"],
                    "Разбиение документов на чанки…")
        strategy_chunks: Dict[str, List[Any]] = {}
        time_chunking: Dict[str, float] = {}
        for strategy in req.strategies:
            params = self._params_for(req, strategy)
            t0 = time.time()
            chunks: List[Any] = []
            for i, doc in enumerate(prepared):
                m.check_cancel(job_id)
                m.update(job_id, document_index=i + 1, document_total=len(prepared),
                         current_document=doc.source, chunks=sum(len(c) for c in strategy_chunks.values()))
                try:
                    if strategy == "fixed_size":
                        chunks += chunk_fixed_size(doc, getattr(doc, "_text"), params)
                    else:
                        chunks += chunk_structural(doc, getattr(doc, "_text"), params,
                                                   getattr(doc, "_segments", []))
                except ValueError as e:
                    raise ValidationError2(str(e))
            strategy_chunks[strategy] = chunks
            time_chunking[strategy] = (time.time() - t0) * 1000
            m.update(job_id, chunks=sum(len(c) for c in strategy_chunks.values()))

        # --- эмбеддинги ---
        client = ollama_provider.get_provider()
        dim = client.probe_dimension()
        m.set_stage(job_id, "embeddings",
                    STAGE_WEIGHTS["prepare"] + STAGE_WEIGHTS["extract"] + STAGE_WEIGHTS["chunking"],
                    f"Генерация эмбеддингов (модель {model}, dim={dim})…")
        base_percent = sum(STAGE_WEIGHTS[k] for k in ("prepare", "extract", "chunking"))
        emb_share = STAGE_WEIGHTS["embeddings"]
        strategy_vectors: Dict[str, np.ndarray] = {}
        strategy_ok_meta: Dict[str, List[Dict[str, Any]]] = {}
        embeddings_done = 0
        for si, strategy in enumerate(req.strategies):
            chunks = strategy_chunks[strategy]
            t0 = time.time()
            vecs: List[List[float]] = []
            ok_chunks: List[Any] = []
            n_batches = max(1, (len(chunks) + batch_size - 1) // batch_size)
            for bi, i in enumerate(range(0, len(chunks), batch_size)):
                m.check_cancel(job_id)
                batch = chunks[i:i + batch_size]
                try:
                    emb = client.embed([c.text for c in batch])
                except EmbeddingError as e:
                    m.add_error(job_id, f"[{strategy}] Ошибка эмбеддингов: {e}")
                    logger.warning("Batch %d стратегии %s не удался: %s", bi, strategy, e)
                    continue
                for c, v in zip(batch, emb):
                    if len(v) != dim:
                        m.add_error(job_id, f"[{strategy}] Неверная размерность вектора")
                        continue
                    vecs.append(v)
                    ok_chunks.append(c)
                embeddings_done += len(emb)
                frac = (si + (bi + 1) / n_batches) / len(req.strategies)
                m.update(
                    job_id,
                    embeddings_done=embeddings_done,
                    percent=base_percent + emb_share * frac,
                    message=f"Эмбеддинги: {embeddings_done} из ~{len(chunks) * len(req.strategies)}",
                )
            if chunks and not vecs:
                m.add_error(job_id, f"[{strategy}] Все эмбеддинги упали — индекс не создан")
                continue
            strategy_vectors[strategy] = np.asarray(vecs, dtype="float32")
            strategy_ok_meta[strategy] = [
                c.to_metadata(collection_id, model, index_version=1) for c in ok_chunks
            ]
            time_emb = (time.time() - t0) * 1000

            # --- FAISS + метаданные ---
            m.set_stage(job_id, "faiss", base_percent + emb_share,
                        f"Построение FAISS-индекса «{strategy}»…")
            m.check_cancel(job_id)
            config = store.build_config(
                collection_id=collection_id,
                strategy=strategy,
                index_id=new_id("index"),
                model=model,
                dimension=dim,
                chunking_params=self._params_for(req, strategy).model_dump(),
                num_vectors=len(strategy_ok_meta[strategy]),
                document_ids=[d.id for d in prepared],
                job_id=job_id,
                times={"chunking_ms": time_chunking[strategy], "embeddings_ms": time_emb,
                       "total_ms": (time.time() - start_epoch) * 1000},
                errors_count=0,
            )
            if req.mode == "add":
                existing = collections_repo.get_index(collection_id, strategy)
                existing_cfg = existing["config"] if isinstance(existing["config"], dict) \
                    else json.loads(existing["config"])
                config = store.append(collection_id, strategy, strategy_vectors[strategy],
                                      strategy_ok_meta[strategy], existing_cfg)
                action = "add"
            else:
                config = store.save_new(collection_id, strategy, strategy_vectors[strategy],
                                        strategy_ok_meta[strategy], config)
                action = "rebuild" if req.mode == "rebuild" else "create"

            # --- проверка целостности ---
            m.set_stage(job_id, "integrity", base_percent + emb_share + STAGE_WEIGHTS["faiss"],
                        "Проверка целостности…")
            _, meta_loaded, cfg_loaded = store.load(collection_id, strategy)
            if len(meta_loaded) != cfg_loaded["num_vectors"]:
                raise RuntimeError("Ошибка целостности: несовпадение числа записей")

            collections_repo.upsert_index(
                collection_id, strategy, config["index_id"],
                str(store.config_file(collection_id, strategy)), config,
            )
            m.update(job_id, message=f"Индекс «{strategy}» готов ({len(meta_loaded)} чанков)")

        result = self._finalize(job_id, req, collection_id, collection_name, prepared,
                                strategy_ok_meta, strategy_vectors, start_epoch, model)
        # статус «проиндексирован» для включённых документов
        ok_doc_ids = {meta["document_id"] for metas in strategy_ok_meta.values() for meta in metas}
        for did in ok_doc_ids:
            documents_repo.update_document(did, indexed_at=utc_now_iso())

    # ------------------------------------------------------------------
    def _resolve_collection(self, req: JobRequest) -> Tuple[str, str]:
        if req.mode == "new_collection":
            cid = new_id("collection")
            now = __import__("time").strftime("%Y-%m-%dT%H:%M:%S")
            row = collections_repo.create_collection(cid, req.collection_name or "Без названия",
                                                     description="Автоматически создана при индексации")
            return cid, row["name"]
        row = collections_repo.get_collection(req.collection_id or "")
        if row is None:
            raise NotFoundError("Коллекция не найдена", code="collection_not_found")
        return row["id"], row["name"]

    def _finalize(self, job_id, req, collection_id, collection_name, prepared,
                  strategy_ok_meta, strategy_vectors, start_epoch, model) -> Dict[str, Any]:
        m = self.manager
        indexes: List[JobResultIndex] = []
        total_chunks = 0
        for strategy in req.strategies:
            metas = strategy_ok_meta.get(strategy) or []
            total_chunks += len(metas)
            rec = collections_repo.get_index(collection_id, strategy)
            config = rec["config"] if isinstance(rec["config"], dict) else json.loads(rec["config"])
            indexes.append(JobResultIndex(
                collection_id=collection_id, strategy=strategy,
                index_id=config.get("index_id", ""), num_vectors=len(metas),
                num_documents=config.get("num_documents", 0),
                action="ok", size_bytes=config.get("size_bytes", 0),
                dimension=config.get("dimension", 0),
            ))
        p = m.get_progress(job_id)
        errors = (p.errors if p else 0) or 0
        result = JobResult(
            collection_id=collection_id,
            collection_name=collection_name,
            indexes=indexes,
            documents=len(prepared),
            chunks=total_chunks,
            embeddings_ok=sum(len(v) for v in strategy_vectors.values()),
            embeddings_failed=0,
            errors=[],
            warnings=[],
            time_total_ms=(time.time() - start_epoch) * 1000,
        ).model_dump()
        status = "completed_with_errors" if errors else "completed"
        self.manager.finish(job_id, status, result=result,
                            message=f"Готово: {len(indexes)} индекс(ов), {total_chunks} чанков")
        return result


def _cleanup_empty_collection(collection_id: str) -> None:
    """Удалить созданную, но не наполненную коллекцию (отмена задания)."""
    try:
        store = get_store()
        has_fixed = store.strategy_dir(collection_id, "fixed_size").exists()
        has_struct = store.strategy_dir(collection_id, "structural").exists()
        if not has_fixed and not has_struct:
            store.delete_collection_files(collection_id)
            collections_repo.delete_collection(collection_id)
    except Exception:  # noqa: BLE001
        logger.exception("Не удалось удалить пустую коллекцию %s", collection_id)


def get_indexing_service() -> IndexingService:
    from .job_service import manager as m
    return IndexingService(m)


indexing_service = get_indexing_service()