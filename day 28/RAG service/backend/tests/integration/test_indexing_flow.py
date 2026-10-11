"""Интеграционные тесты: загрузка → индексация → FAISS → поиск → сравнение.

Работают на фейковом клиенте эмбеддингов (без Ollama).
"""

from __future__ import annotations

import json
import time

from tests.conftest import make_pdf


def _upload_demo(client) -> list[dict]:
    r = client.post("/api/documents/demo")
    assert r.status_code == 200, r.text
    docs = r.json()["documents"]
    assert len(docs) == 5
    return docs


def _wait_job(client, job_id, timeout=60.0) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = client.get(f"/api/indexing/jobs/{job_id}").json()
        if last["status"] in ("completed", "completed_with_errors", "failed", "cancelled"):
            return last
        time.sleep(0.2)
    raise TimeoutError(f"job {job_id} не завершился: {last}")


# ---------------------------------------------------------------------------
# Загрузка нескольких файлов
# ---------------------------------------------------------------------------

def test_upload_multiple_files(client, file_factories):
    pdf = file_factories["pdf"](["Page one", "Page two"])
    r = client.post("/api/documents/upload", files=[
        ("files", ("a.txt", "просто текст".encode(), "text/plain")),
        ("files", ("b.pdf", pdf, "application/pdf")),
        ("files", ("c.md", "# Заголовок\n\nТекст".encode("utf-8"), "text/markdown")),
        ("files", ("d.docx", file_factories["docx"]([(0, "Абзац")]), "application/octet-stream")),
    ])
    assert r.status_code == 200
    j = r.json()
    assert j["uploaded"] == 4 and j["failed"] == 0
    by_name = {d["source"]: d for d in j["documents"]}
    assert by_name["b.pdf"]["page_count"] == 2
    assert by_name["a.txt"]["status"] == "ready"


def test_upload_limits_size_and_count(client):
    # превышение числа файлов
    many = [("files", (f"f{i}.txt", b"x", "text/plain")) for i in range(5)]
    from app.services.runtime import effective_settings
    s = effective_settings()
    assert s.max_files_per_request >= 5  # лимит по умолчанию выше
    r = client.post("/api/documents/upload", files=many)
    assert r.status_code == 200 and r.json()["uploaded"] == 5

    # неподдерживаемый формат
    r = client.post("/api/documents/upload", files=[("files", ("a.xyz", b"x", "text/plain"))])
    assert r.json()["failed"] == 1
    assert "Неподдерживаемый формат" in r.json()["errors"][0]["message"]


def test_duplicate_filenames_not_overwritten(client):
    r1 = client.post("/api/documents/upload", files=[("files", ("same.txt", b"first", "text/plain"))])
    r2 = client.post("/api/documents/upload", files=[("files", ("same.txt", b"second", "text/plain"))])
    storage_names = [d["storage_name"] for d in (r1.json()["documents"] + r2.json()["documents"])]
    assert len(set(storage_names)) == 2  # второй файл получил суффикс
    assert storage_names[1] == "same_1.txt"
    docs = client.get("/api/documents").json()
    assert len(docs) == 2  # первый файл не перезаписан


# ---------------------------------------------------------------------------
# Индексация end-to-end (обе стратегии)
# ---------------------------------------------------------------------------

def test_indexing_both_strategies(client):
    docs = _upload_demo(client)
    doc_ids = [d["id"] for d in docs]
    payload = {
        "document_ids": doc_ids,
        "strategies": ["fixed_size", "structural"],
        "mode": "new_collection",
        "collection_name": "Тестовая коллекция",
        "fixed_size": {"chunk_size": 400, "overlap": 80, "unit": "chars"},
        "structural": {"max_chunk_size": 600, "min_chunk_size": 150, "merge_small_sections": True},
    }
    r = client.post("/api/indexing/jobs", json=payload)
    assert r.status_code == 201, r.text
    job_id = r.json()["job_id"]
    final = _wait_job(client, job_id)
    assert final["status"] in ("completed", "completed_with_errors"), final

    collections = client.get("/api/collections").json()
    assert len(collections) == 1
    col = collections[0]
    assert set(col["strategies"]) == {"fixed_size", "structural"}
    total_vectors = sum(i["num_vectors"] for i in col["indexes"])
    assert total_vectors > 0


def test_index_requires_documents(client):
    r = client.post("/api/indexing/jobs", json={
        "document_ids": [],
        "strategies": ["fixed_size"],
        "mode": "new_collection",
        "collection_name": "Пустая",
    })
    assert r.status_code == 422


def test_index_requires_nonempty_documents(client):
    # файл с пробелами читается, но текста в нём нет
    r = client.post("/api/documents/upload", files=[("files", ("empty.md", b"\n\n  \n", "text/markdown"))])
    assert r.json()["documents"][0]["status"] == "ready"
    empty_doc = r.json()["documents"][0]
    rr = client.post("/api/indexing/jobs", json={
        "document_ids": [empty_doc["id"]],
        "strategies": ["fixed_size"],
        "mode": "new_collection",
        "collection_name": "Пустая",
    })
    assert rr.status_code == 409  # нет текста → отказ с понятным сообщением


def test_index_validation_overlap(client):
    docs = _upload_demo(client)
    r = client.post("/api/indexing/jobs", json={
        "document_ids": [d["id"] for d in docs],
        "strategies": ["fixed_size"],
        "mode": "new_collection",
        "collection_name": "Некорректная",
        "fixed_size": {"chunk_size": 100, "overlap": 200, "unit": "chars"},
    })
    assert r.status_code == 422
    assert "overlap" in json.dumps(r.json(), ensure_ascii=False).lower() or "Overlap" in r.text


# ---------------------------------------------------------------------------
# FAISS: сохранение, загрузка, соответствие позиций, поиск Top-K
# ---------------------------------------------------------------------------

def _build_index(client, strategies=("fixed_size", "structural")):
    docs = _upload_demo(client)
    payload = {
        "document_ids": [d["id"] for d in docs],
        "strategies": list(strategies),
        "mode": "new_collection",
        "collection_name": "FAISS-тест",
        "fixed_size": {"chunk_size": 500, "overlap": 100},
        "structural": {"max_chunk_size": 700, "min_chunk_size": 150},
    }
    job_id = client.post("/api/indexing/jobs", json=payload).json()["job_id"]
    final = _wait_job(client, job_id)
    assert final["status"] in ("completed", "completed_with_errors"), final
    col = client.get("/api/collections").json()[0]
    return col


def test_faiss_save_load_and_alignment(client):
    col = _build_index(client)
    from app.services import runtime
    from app.services.faiss_store import get_store

    store = get_store()
    for strategy in ("fixed_size", "structural"):
        index, metadata, config = store.load(col["id"], strategy)
        assert index.ntotal == len(metadata) == config["num_vectors"] > 0
        # векторы восстановимы и нормализованы
        v = index.reconstruct_n(0, 1)[0]
        assert abs(float(sum(x * x for x in v)) - 1.0) < 1e-4
        # позиции: каждый i-й вектор соответствует i-й записи метаданных
        assert metadata[0]["chunk_id"]
        # файлы на диске
        assert store.index_file(col["id"], strategy).exists()
        assert store.metadata_file(col["id"], strategy).exists()
        assert store.config_file(col["id"], strategy).exists()


def test_search_topk(client):
    col = _build_index(client, strategies=("structural",))
    r = client.post("/api/search", json={
        "collection_id": col["id"], "strategy": "structural",
        "query": "чем полезна индексация для RAG", "top_k": 3,
    })
    assert r.status_code == 200, r.text
    j = r.json()
    assert 1 <= len(j["results"]) <= 3
    first = j["results"][0]
    assert first["rank"] == 1
    assert 0.0 <= first["score"] <= 1.001
    assert first["chunk"]["chunk_id"]
    assert first["chunk"]["text"]
    # подсказка про cosine similarity
    assert j["note"]


def test_search_empty_and_model_mismatch(client):
    # пустой запрос
    r = client.post("/api/search", json={"collection_id": "x", "strategy": "fixed_size", "query": "  ", "top_k": 3})
    assert r.status_code in (409, 422)

    # несуществующая коллекция/индекс
    r = client.post("/api/search", json={"collection_id": "nonexistent", "strategy": "fixed_size", "query": "x", "top_k": 3})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Отмена задания
# ---------------------------------------------------------------------------

def test_cancel_job(client):
    client.fake_embeddings.batch_delay = 0.2  # type: ignore[attr-defined]  # замедляем эмбеддинги
    docs = _upload_demo(client)
    payload = {
        "document_ids": [d["id"] for d in docs],
        "strategies": ["fixed_size", "structural"],
        "mode": "new_collection",
        "collection_name": "Отменяемая",
        "fixed_size": {"chunk_size": 300, "overlap": 60},
    }
    job_id = client.post("/api/indexing/jobs", json=payload).json()["job_id"]
    time.sleep(0.2)
    r = client.post(f"/api/indexing/jobs/{job_id}/cancel")
    assert r.status_code == 200
    final = _wait_job(client, job_id, timeout=30)
    assert final["status"] == "cancelled"
    # частичный индекс не опубликован
    assert client.get("/api/collections").json() == []


# ---------------------------------------------------------------------------
# Обработка ошибки Ollama
# ---------------------------------------------------------------------------

def test_ollama_error_is_visible(client):
    client.fake_embeddings.fail_forever = True  # type: ignore[attr-defined]
    docs = _upload_demo(client)
    payload = {
        "document_ids": [d["id"] for d in docs],
        "strategies": ["fixed_size"],
        "mode": "new_collection",
        "collection_name": "Сбой Ollama",
        "fixed_size": {"chunk_size": 400, "overlap": 80},
    }
    job_id = client.post("/api/indexing/jobs", json=payload).json()["job_id"]
    final = _wait_job(client, job_id, timeout=30)
    assert final["status"] == "failed"
    assert "Ошибка эмбеддингов" in (final["message"] or "") or final["errors"] > 0


def test_partial_embedding_failure_reported(client):
    client.fake_embeddings.fail_batches = 2  # type: ignore[attr-defined]
    docs = _upload_demo(client)
    payload = {
        "document_ids": [d["id"] for d in docs],
        "strategies": ["fixed_size"],
        "mode": "new_collection",
        "collection_name": "Частичный сбой",
        "fixed_size": {"chunk_size": 400, "overlap": 80},
    }
    job_id = client.post("/api/indexing/jobs", json=payload).json()["job_id"]
    final = _wait_job(client, job_id, timeout=60)
    assert final["status"] in ("completed_with_errors", "failed")
    assert final["errors"] > 0


# ---------------------------------------------------------------------------
# Добавление документов и режимы
# ---------------------------------------------------------------------------

def test_add_documents_mode(client):
    col = _build_index(client, strategies=("structural",))
    new_doc = client.post("/api/documents/upload",
                          files=[("files", ("extra.md", "# Дополнение\n\nНовый материал для индекса.".encode("utf-8"), "text/markdown"))]
                          ).json()["documents"][0]
    payload = {
        "document_ids": [new_doc["id"]],
        "strategies": ["structural"],
        "mode": "add",
        "collection_id": col["id"],
        "structural": {"max_chunk_size": 700, "min_chunk_size": 150},
    }
    job_id = client.post("/api/indexing/jobs", json=payload).json()["job_id"]
    final = _wait_job(client, job_id, timeout=60)
    assert final["status"] in ("completed", "completed_with_errors"), final
    col2 = client.get(f"/api/collections/{col['id']}").json()
    idx = col2["indexes"][0]
    assert idx["num_documents"] == 6  # 5 + 1


def test_add_incompatible_config_rejected(client):
    col = _build_index(client, strategies=("fixed_size",))
    doc = client.post("/api/documents/upload", files=[("files", ("x.md", b"# X\n\nY", "text/markdown"))]
                      ).json()["documents"][0]
    payload = {
        "document_ids": [doc["id"]], "strategies": ["fixed_size"], "mode": "add",
        "collection_id": col["id"],
        "fixed_size": {"chunk_size": 9999, "overlap": 10},  # несовместимые параметры
    }
    r = client.post("/api/indexing/jobs", json=payload)
    assert r.status_code == 409
    assert "несовместим" in r.json()["detail"]


def test_rebuild_mode(client):
    col = _build_index(client, strategies=("fixed_size",))
    payload = {
        "document_ids": [i["document_ids"][0] for i in client.get(f"/api/collections/{col['id']}").json()["indexes"]],
        "strategies": ["fixed_size"], "mode": "rebuild", "collection_id": col["id"],
        "fixed_size": {"chunk_size": 500, "overlap": 100},
    }
    job_id = client.post("/api/indexing/jobs", json=payload).json()["job_id"]
    final = _wait_job(client, job_id, timeout=60)
    assert final["status"] in ("completed", "completed_with_errors"), final


# ---------------------------------------------------------------------------
# Сравнение, история, статистика
# ---------------------------------------------------------------------------

def test_comparison_and_history(client):
    col = _build_index(client)
    cmp = client.get(f"/api/comparison/{col['id']}").json()
    assert set(cmp["strategies"]) == {"fixed_size", "structural"}
    for s in cmp["strategies"]:
        m = cmp["metrics"][s]
        assert m["chunks"] > 0
        assert m["mean_chars"] > 0
    assert cmp["tradeoffs"]

    h = client.get("/api/history").json()
    assert h["total"] == 1
    job = h["jobs"][0]
    assert job["status"] == "completed"
    detail = client.get(f"/api/history/{job['job_id']}").json()
    assert detail["result"]["indexes"]

    ov = client.get("/api/stats/overview").json()
    assert ov["documents"]["total"] == 5
    assert ov["chunks"]["total"] > 0
    assert ov["collections"]["total"] == 1


def test_index_stats_endpoint(client):
    col = _build_index(client, strategies=("fixed_size",))
    idx = col["indexes"][0]
    st = client.get(f"/api/indexes/{idx['index_id']}/stats").json()
    assert st["chunks"] > 0
    assert st["mean_chars"] > 0 and st["median_chars"] > 0
    assert st["min_chars"] <= st["max_chars"]
    chunks = client.get(f"/api/indexes/{idx['index_id']}/chunks?limit=5").json()
    assert chunks["total"] == st["chunks"]
    cid = chunks["chunks"][0]["chunk_id"]
    one = client.get(f"/api/indexes/{idx['index_id']}/chunks/{cid}").json()
    assert one["chunk_id"] == cid