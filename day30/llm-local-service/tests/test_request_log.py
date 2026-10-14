"""Проверки JSON-хранилища журнала, retention и восстановления после рестарта."""

from __future__ import annotations

import asyncio

from app.request_log import RequestLogStore, new_record


def _record(content: str):
    record = new_record(
        client="ip:127.0.0.1",
        settings_model="llama3.2:3b",
        ollama_base_url="http://127.0.0.1:11434",
        messages=[{"role": "user", "content": content}],
        estimated_input_tokens=len(content),
        max_output_tokens=128,
        num_ctx=2048,
    )
    record.status = "ok"
    record.http_status = 200
    record.response = f"ответ {content}"
    record.response_chars = len(record.response)
    return record


def test_record_is_persisted_and_restored(tmp_path) -> None:
    directory = tmp_path / "request-logs"
    store = RequestLogStore(directory, enabled=True, max_entries=10)
    saved = asyncio.run(store.flush(_record("секретный текст")))

    assert saved.file is not None
    assert (directory / saved.file).is_file()
    assert store.stats()["files"] == 1

    restored = RequestLogStore(directory, enabled=True, max_entries=10)
    assert restored.stats()["buffered"] == 1
    entry = restored.get_entry(saved.id)
    assert entry is not None
    assert entry.messages[0]["content"] == "секретный текст"
    assert entry.response == "ответ секретный текст"


def test_retention_deletes_oldest_file(tmp_path) -> None:
    directory = tmp_path / "logs"
    store = RequestLogStore(directory, enabled=True, max_entries=2)
    first = asyncio.run(store.flush(_record("1")))
    second = asyncio.run(store.flush(_record("2")))
    third = asyncio.run(store.flush(_record("3")))

    assert store.stats()["files"] == 2
    assert not (directory / first.file).exists()
    assert (directory / second.file).exists()
    assert (directory / third.file).exists()


def test_disabled_store_does_not_write_or_buffer_content(tmp_path) -> None:
    store = RequestLogStore(tmp_path / "off", enabled=False, max_entries=5)
    record = asyncio.run(store.flush(_record("do not keep")))
    assert record.file is None
    assert store.stats()["files"] == 0
    assert store.stats()["buffered"] == 0
