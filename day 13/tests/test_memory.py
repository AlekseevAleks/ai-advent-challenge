"""Tests for the three-layer agent memory model.

These tests demonstrate the *separation* of the layers, which is the point of
the assignment: the same message can touch several layers, but each layer has
its own storage, lifetime and role in the prompt.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.memory.extractor import MemoryExtractor
from backend.memory.long_term import LongTermMemory
from backend.memory.manager import MemoryManager
from backend.memory.models import (
    LongTermCandidate,
    WorkingMemoryData,
    WorkingMemoryPatch,
)
from backend.memory.short_term import ShortTermMemory
from backend.memory.working import WorkingMemory


def _configure(client: TestClient) -> None:
    client.put(
        "/api/settings",
        json={"api_base_url": "https://api.example.com/v1", "api_key": "sk-test123456"},
    )


def _create_chat(client: TestClient, model: str = "gpt-4o-mini") -> dict:
    return client.post("/api/chats", json={"model": model}).json()


# ---------------------------------------------------------------- Test 1
def test_short_term_stores_current_dialogue(client: TestClient, fake_api) -> None:
    """Test 1 — a user message lands in the current chat's short-term memory."""
    _configure(client)
    chat = _create_chat(client)

    client.post(f"/api/chats/{chat['id']}/messages", json={"content": "Привет!"})

    response = client.get(f"/api/chats/{chat['id']}/memory/short-term")
    assert response.status_code == 200
    payload = response.json()
    assert payload["chat_id"] == chat["id"]
    assert payload["total_messages"] == 2
    assert [entry["role"] for entry in payload["entries"]] == ["user", "assistant"]
    assert payload["entries"][0]["content"] == "Привет!"


def test_short_term_is_scoped_to_one_chat(client: TestClient, fake_api) -> None:
    """Short-term memory of one chat never leaks into another."""
    _configure(client)
    first = _create_chat(client)
    second = _create_chat(client)

    client.post(f"/api/chats/{first['id']}/messages", json={"content": "Только тут"})

    other = client.get(f"/api/chats/{second['id']}/memory/short-term").json()
    assert other["entries"] == []
    assert other["total_messages"] == 0


def test_short_term_is_trimmed_to_context_window(database) -> None:
    """Short-term memory is limited to the last N messages."""
    from backend.database.repositories import MessageRepository

    from backend.database.repositories import ChatRepository

    chat_id = ChatRepository(database).create(model="m").id
    messages = MessageRepository(database)
    memory = ShortTermMemory(messages, max_messages=3)
    for index in range(6):
        memory.append(chat_id, "user", f"сообщение {index}")

    trimmed = memory.get(chat_id)
    assert trimmed.total_messages == 6
    assert trimmed.truncated is True
    assert len(trimmed.entries) == 3
    assert trimmed.entries[-1].content == "сообщение 5"


# ---------------------------------------------------------------- Test 2
def test_working_memory_holds_task_state(client: TestClient, fake_api) -> None:
    """Test 2 — a task statement is classified into working memory."""
    _configure(client)
    chat = _create_chat(client)

    client.post(
        f"/api/chats/{chat['id']}/messages",
        json={"content": "Сейчас мы разрабатываем API интернет-магазина"},
    )

    working = client.get(f"/api/chats/{chat['id']}/memory/working").json()
    assert working["exists"] is True
    assert "интернет-магазина" in working["data"]["task"]


def test_working_memory_merges_patches(database) -> None:
    """Working memory accumulates state instead of overwriting it."""
    from backend.database.repositories import ChatRepository

    chat_id = ChatRepository(database).create(model="m").id
    working = WorkingMemory()
    working.apply_patch(
        chat_id,
        WorkingMemoryPatch(task="API магазина", stack=["Python", "FastAPI"]),
    )
    data, changes = working.apply_patch(
        chat_id,
        WorkingMemoryPatch(current_step="Авторизация", completed=["Регистрация"]),
    )

    assert data.task == "API магазина"
    assert data.stack == ["Python", "FastAPI"]
    assert data.current_step == "Авторизация"
    assert data.completed == ["Регистрация"]
    assert any("current_step" in change for change in changes)


def test_working_memory_does_not_duplicate_list_items(database) -> None:
    from backend.database.repositories import ChatRepository

    chat_id = ChatRepository(database).create(model="m").id
    working = WorkingMemory()
    working.apply_patch(chat_id, WorkingMemoryPatch(stack=["Python"]))
    data, changes = working.apply_patch(chat_id, WorkingMemoryPatch(stack=["Python"]))

    assert data.stack == ["Python"]
    assert changes == []


def test_working_memory_can_be_edited_and_cleared(client: TestClient, fake_api) -> None:
    _configure(client)
    chat = _create_chat(client)

    response = client.put(
        f"/api/chats/{chat['id']}/memory/working",
        json={
            "data": {
                "task": "Своя задача",
                "goal": "Своя цель",
                "stack": ["Go"],
                "current_step": "Шаг 1",
                "completed": [],
                "constraints": [],
                "decisions": [],
            }
        },
    )
    assert response.status_code == 200
    assert response.json()["data"]["task"] == "Своя задача"

    assert client.delete(f"/api/chats/{chat['id']}/memory/working").status_code == 204
    assert client.get(f"/api/chats/{chat['id']}/memory/working").json()["exists"] is False


# ---------------------------------------------------------------- Test 3
def test_long_term_memory_holds_user_preferences(client: TestClient, fake_api) -> None:
    """Test 3 — a durable preference is promoted to long-term memory."""
    _configure(client)
    chat = _create_chat(client)

    client.post(
        f"/api/chats/{chat['id']}/messages",
        json={"content": "Я предпочитаю Python и FastAPI"},
    )

    entries = client.get("/api/memory/long-term").json()["entries"]
    values = {entry["value"] for entry in entries}
    assert "Python" in values
    assert "FastAPI" in values
    assert all(entry["category"] == "preference" for entry in entries)


def test_long_term_memory_is_not_chat_scoped(client: TestClient, fake_api) -> None:
    """Long-term memory is global: it is not tied to the chat that produced it."""
    _configure(client)
    chat = _create_chat(client)
    client.post(
        f"/api/chats/{chat['id']}/messages",
        json={"content": "Я предпочитаю Python"},
    )

    # Deleting the chat must not remove the user-level fact.
    client.delete(f"/api/chats/{chat['id']}")
    entries = client.get("/api/memory/long-term").json()["entries"]
    assert any(entry["value"] == "Python" for entry in entries)


def test_long_term_memory_crud(client: TestClient) -> None:
    created = client.post(
        "/api/memory/long-term",
        json={"category": "preference", "key": "response_style", "value": "concise"},
    )
    assert created.status_code == 201
    memory_id = created.json()["id"]

    updated = client.put(
        f"/api/memory/long-term/{memory_id}", json={"value": "detailed"}
    )
    assert updated.status_code == 200
    assert updated.json()["value"] == "detailed"

    assert client.delete(f"/api/memory/long-term/{memory_id}").status_code == 204
    assert client.get("/api/memory/long-term").json()["entries"] == []


def test_long_term_upsert_updates_same_key(client: TestClient) -> None:
    client.post(
        "/api/memory/long-term",
        json={"category": "preference", "key": "preferred_language", "value": "Python"},
    )
    client.post(
        "/api/memory/long-term",
        json={"category": "preference", "key": "preferred_language", "value": "Go"},
    )

    entries = client.get("/api/memory/long-term").json()["entries"]
    assert len(entries) == 1
    assert entries[0]["value"] == "Go"


def test_missing_long_term_entry_returns_404(client: TestClient) -> None:
    assert client.delete("/api/memory/long-term/nope").status_code == 404
    assert (
        client.put("/api/memory/long-term/nope", json={"value": "x"}).status_code == 404
    )


# ---------------------------------------------------------------- Test 4
def test_deleting_chat_keeps_long_term_memory(client: TestClient, fake_api) -> None:
    """Test 4 — isolation: chat deletion drops chat layers, keeps user facts."""
    _configure(client)
    chat = _create_chat(client)
    client.post(
        f"/api/chats/{chat['id']}/messages",
        json={"content": "Я предпочитаю Python"},
    )
    client.post(
        f"/api/chats/{chat['id']}/messages",
        json={"content": "Сейчас мы разрабатываем API интернет-магазина"},
    )

    # Both chat-scoped layers are populated before deletion.
    assert client.get(f"/api/chats/{chat['id']}/memory/short-term").json()[
        "total_messages"
    ] > 0
    assert client.get(f"/api/chats/{chat['id']}/memory/working").json()["exists"] is True

    client.delete(f"/api/chats/{chat['id']}")

    # The chat is gone entirely...
    assert client.get(f"/api/chats/{chat['id']}").status_code == 404
    # ...but the user-level fact survives.
    entries = client.get("/api/memory/long-term").json()["entries"]
    assert any(entry["value"] == "Python" for entry in entries)


def test_working_memory_row_is_removed_with_chat(database) -> None:
    from backend.database.memory_repositories import WorkingMemoryRepository
    from backend.database.repositories import ChatRepository

    chats = ChatRepository(database)
    working_repo = WorkingMemoryRepository(database)
    chat = chats.create(model="m")

    working_repo.save(chat.id, WorkingMemoryData(task="Задача"))
    assert working_repo.get(chat.id) is not None

    chats.delete(chat.id)
    assert working_repo.get(chat.id) is None


# ---------------------------------------------------------------- Test 5
def test_new_chat_sees_long_term_but_not_working_memory(
    client: TestClient, fake_api
) -> None:
    """Test 5 — a fresh chat inherits user facts, not the old task state."""
    _configure(client)
    first = _create_chat(client)
    client.post(
        f"/api/chats/{first['id']}/messages",
        json={"content": "Я предпочитаю Python"},
    )
    client.post(
        f"/api/chats/{first['id']}/messages",
        json={"content": "Сейчас мы разрабатываем API интернет-магазина"},
    )

    second = _create_chat(client)
    overview = client.get("/api/memory", params={"chat_id": second["id"]}).json()

    # Long-term memory is visible in the new chat...
    assert any(entry["value"] == "Python" for entry in overview["long_term"]["entries"])
    # ...while the new chat has no working memory and no dialogue of its own.
    assert overview["working"]["exists"] is False
    assert overview["short_term"]["entries"] == []


def test_prompt_for_new_chat_contains_long_term_only(
    client: TestClient, fake_api
) -> None:
    _configure(client)
    first = _create_chat(client)
    client.post(
        f"/api/chats/{first['id']}/messages",
        json={"content": "Я предпочитаю Python"},
    )
    client.post(
        f"/api/chats/{first['id']}/messages",
        json={"content": "Сейчас мы разрабатываем API интернет-магазина"},
    )

    second = _create_chat(client)
    preview = client.get("/api/memory", params={"chat_id": second["id"]}).json()[
        "prompt_preview"
    ]

    assert "Long-term memory" in preview
    assert "Python" in preview
    # The old task must not leak into the new chat's context.
    assert "Working memory" not in preview
    assert "интернет-магазина" not in preview


# ---------------------------------------------------------------- Test 6
def test_prompt_contains_all_three_layers(client: TestClient, fake_api) -> None:
    """Test 6 — the LLM context is assembled from long-term + working + short-term."""
    _configure(client)
    chat = _create_chat(client)
    client.post(
        f"/api/chats/{chat['id']}/messages",
        json={"content": "Я предпочитаю Python"},
    )
    client.post(
        f"/api/chats/{chat['id']}/messages",
        json={"content": "Сейчас мы разрабатываем API интернет-магазина"},
    )

    preview = client.get("/api/memory", params={"chat_id": chat["id"]}).json()[
        "prompt_preview"
    ]
    assert "## Long-term memory" in preview
    assert "## Working memory" in preview
    assert "Python" in preview
    assert "интернет-магазина" in preview


def test_first_message_has_no_memory_yet(client: TestClient, fake_api) -> None:
    """Memory is extracted after the reply, so the very first prompt is plain."""
    _configure(client)
    chat = _create_chat(client)
    client.post(
        f"/api/chats/{chat['id']}/messages",
        json={"content": "Я предпочитаю Python"},
    )

    completion_requests = fake_api.chat_requests()
    first_prompt = completion_requests[0]["json"]["messages"][0]["content"]
    assert "Long-term memory" not in first_prompt

    # ...but the fact was extracted and is available for the next request.
    assert client.get("/api/memory/long-term").json()["entries"]


def test_llm_request_includes_memory_context(client: TestClient, fake_api) -> None:
    """The memory context really reaches the model, not just the UI."""
    _configure(client)
    chat = _create_chat(client)
    client.post(
        f"/api/chats/{chat['id']}/messages",
        json={"content": "Я предпочитаю Python"},
    )
    client.post(
        f"/api/chats/{chat['id']}/messages",
        json={"content": "Сейчас мы разрабатываем API интернет-магазина"},
    )
    # A third message is needed: working memory extracted from message #2 only
    # becomes part of the prompt for message #3.
    client.post(
        f"/api/chats/{chat['id']}/messages",
        json={"content": "Что дальше?"},
    )

    completion_requests = fake_api.chat_requests()
    assert completion_requests
    sent = completion_requests[-1]["json"]["messages"]
    system_messages = [m for m in sent if m["role"] == "system"]
    assert system_messages
    system_text = system_messages[0]["content"]
    assert "Long-term memory" in system_text
    assert "Working memory" in system_text
    # Short-term memory is the dialogue itself.
    assert any(m["role"] == "user" for m in sent)


def test_memory_context_is_compact_text_not_json(client: TestClient, fake_api) -> None:
    """Raw JSON is never injected into the prompt."""
    _configure(client)
    chat = _create_chat(client)
    client.post(
        f"/api/chats/{chat['id']}/messages",
        json={"content": "Я предпочитаю Python"},
    )

    preview = client.get("/api/memory", params={"chat_id": chat["id"]}).json()[
        "prompt_preview"
    ]
    assert "{" not in preview
    assert "User preferences:" in preview


# ------------------------------------------------------- extractor behaviour
def test_extractor_rules_classify_preference(database) -> None:
    extractor = MemoryExtractor()
    result = extractor.extract_with_rules("Я предпочитаю Python и FastAPI")

    keys = {candidate.key for candidate in result.long_term_candidates}
    assert "preferred_language" in keys
    assert "preferred_framework" in keys
    assert result.working_memory is None


def test_extractor_rules_classify_task(database) -> None:
    extractor = MemoryExtractor()
    result = extractor.extract_with_rules("Сейчас мы разрабатываем API интернет-магазина")

    assert result.working_memory is not None
    assert "интернет-магазина" in result.working_memory.task
    assert result.long_term_candidates == []


def test_extractor_rules_classify_step_and_decision(database) -> None:
    extractor = MemoryExtractor()
    result = extractor.extract_with_rules("Давай теперь сделаем авторизацию")

    assert result.working_memory is not None
    assert "авторизацию" in result.working_memory.current_step


def test_extractor_rules_detect_response_style(database) -> None:
    extractor = MemoryExtractor()
    result = extractor.extract_with_rules("Отвечай кратко")

    assert any(
        candidate.key == "response_style" and candidate.value == "concise"
        for candidate in result.long_term_candidates
    )


def test_extractor_plain_message_touches_nothing(database) -> None:
    extractor = MemoryExtractor()
    result = extractor.extract_with_rules("Привет, как дела?")

    assert result.working_memory is None
    assert result.long_term_candidates == []
    assert result.short_term is True


def test_extractor_parses_llm_json_with_fences() -> None:
    payload = MemoryExtractor._parse_json(
        '```json\n{"short_term": true, "long_term_memory": []}\n```'
    )
    assert payload == {"short_term": True, "long_term_memory": []}


def test_extractor_parses_llm_json_with_prose() -> None:
    payload = MemoryExtractor._parse_json(
        'Вот результат: {"short_term": true, "summary": "ok"} — готово'
    )
    assert payload is not None
    assert payload["summary"] == "ok"


def test_extractor_returns_none_for_garbage() -> None:
    assert MemoryExtractor._parse_json("не json вовсе") is None
    assert MemoryExtractor._parse_json("") is None


def test_extractor_maps_llm_payload() -> None:
    result = MemoryExtractor._to_result(
        {
            "short_term": True,
            "working_memory": {"task": "API", "stack": ["FastAPI"]},
            "long_term_memory": [
                {
                    "category": "preference",
                    "key": "preferred_framework",
                    "value": "FastAPI",
                    "confidence": 0.9,
                }
            ],
            "summary": "задача и предпочтение",
        }
    )
    assert result.working_memory is not None
    assert result.working_memory.task == "API"
    assert result.long_term_candidates[0].key == "preferred_framework"
    assert result.long_term_candidates[0].confidence == 0.9


def test_extractor_ignores_unknown_category() -> None:
    result = MemoryExtractor._to_result(
        {
            "long_term_memory": [
                {"category": "nonsense", "key": "k", "value": "v", "confidence": 0.9}
            ]
        }
    )
    assert result.long_term_candidates[0].category == "fact"


# ------------------------------------------------------- validation rules
def test_low_confidence_candidate_is_rejected(database) -> None:
    memory = LongTermMemory()
    accepted, rejected = memory.accept_candidates(
        [
            LongTermCandidate(
                category="preference", key="preferred_language", value="Python",
                confidence=0.2,
            )
        ]
    )
    assert accepted == []
    assert len(rejected) == 1
    assert "уверенность" in rejected[0].reason


def test_task_scoped_key_is_rejected(database) -> None:
    memory = LongTermMemory()
    accepted, rejected = memory.accept_candidates(
        [
            LongTermCandidate(
                category="fact", key="current_step", value="Авторизация",
                confidence=0.95,
            )
        ]
    )
    assert accepted == []
    assert "текущей задаче" in rejected[0].reason


def test_empty_value_is_rejected(database) -> None:
    memory = LongTermMemory()
    accepted, rejected = memory.accept_candidates(
        [LongTermCandidate(category="fact", key="something", value="нет", confidence=0.9)]
    )
    assert accepted == []
    assert rejected


def test_valid_candidate_is_accepted(database) -> None:
    memory = LongTermMemory()
    accepted, rejected = memory.accept_candidates(
        [
            LongTermCandidate(
                category="preference", key="preferred_language", value="Python",
                confidence=0.9,
            )
        ]
    )
    assert len(accepted) == 1
    assert accepted[0].value == "Python"
    assert rejected == []


# ------------------------------------------------------- manager behaviour
@pytest.mark.asyncio
async def test_manager_analyze_persists_accepted_candidates(database) -> None:
    from backend.database.repositories import ChatRepository

    chat_id = ChatRepository(database).create(model="m").id
    manager = MemoryManager()
    report = await manager.analyze(chat_id, "Я предпочитаю Python и FastAPI")

    assert report.short_term_saved is True
    assert report.working_memory_updated is False
    assert {entry.value for entry in report.long_term_accepted} == {"Python", "FastAPI"}
    assert manager.get_long_term_memory().entries


@pytest.mark.asyncio
async def test_manager_analyze_updates_working_memory(database) -> None:
    from backend.database.repositories import ChatRepository

    chat_id = ChatRepository(database).create(model="m").id
    manager = MemoryManager()
    report = await manager.analyze(
        chat_id, "Сейчас мы разрабатываем API интернет-магазина"
    )

    assert report.working_memory_updated is True
    assert report.working_memory_changes
    assert "интернет-магазина" in manager.get_working_memory(chat_id).data.task


@pytest.mark.asyncio
async def test_manager_analyze_without_persist_changes_nothing(database) -> None:
    from backend.database.repositories import ChatRepository

    chat_id = ChatRepository(database).create(model="m").id
    manager = MemoryManager()
    report = await manager.analyze(
        chat_id, "Я предпочитаю Python", persist=False
    )

    assert report.long_term_accepted == []
    assert manager.get_long_term_memory().entries == []


@pytest.mark.asyncio
async def test_manager_analyze_plain_message_stores_nothing(database) -> None:
    from backend.database.repositories import ChatRepository

    chat_id = ChatRepository(database).create(model="m").id
    manager = MemoryManager()
    report = await manager.analyze(chat_id, "Привет, как дела?")

    assert report.long_term_accepted == []
    assert report.working_memory_updated is False
    assert manager.get_long_term_memory().entries == []


def test_manager_build_messages_layout(database) -> None:
    """Prompt layout: system (memory) → short-term dialogue."""
    from backend.database.repositories import ChatRepository

    chat_id = ChatRepository(database).create(model="m").id
    manager = MemoryManager()
    manager.save_to_short_term(chat_id, "user", "Привет")
    manager.save_to_short_term(chat_id, "assistant", "Здравствуйте")
    manager.save_to_long_term(
        category="preference", key="preferred_language", value="Python"
    )

    messages = manager.build_messages(chat_id, "")
    assert messages[0]["role"] == "system"
    assert "Long-term memory" in messages[0]["content"]
    assert [m["role"] for m in messages[1:]] == ["user", "assistant"]


def test_manager_on_chat_deleted_keeps_long_term(database) -> None:
    from backend.database.repositories import ChatRepository

    chat_id = ChatRepository(database).create(model="m").id
    manager = MemoryManager()
    manager.save_to_working_memory(chat_id, WorkingMemoryPatch(task="Задача"))
    manager.save_to_long_term(
        category="preference", key="preferred_language", value="Python"
    )

    manager.on_chat_deleted(chat_id)

    assert manager.get_working_memory(chat_id).exists is False
    assert len(manager.get_long_term_memory().entries) == 1


# ------------------------------------------------------------- API surface
def test_memory_overview_requires_existing_chat(client: TestClient) -> None:
    assert client.get("/api/memory", params={"chat_id": "nope"}).status_code == 404


def test_memory_overview_without_chat_returns_long_term_only(
    client: TestClient,
) -> None:
    payload = client.get("/api/memory").json()
    assert payload["chat_id"] is None
    assert payload["short_term"] is None
    assert payload["working"] is None
    assert payload["long_term"]["entries"] == []


def test_short_term_memory_of_missing_chat_returns_404(client: TestClient) -> None:
    assert client.get("/api/chats/nope/memory/short-term").status_code == 404


def test_analyze_endpoint_requires_messages(client: TestClient, fake_api) -> None:
    _configure(client)
    chat = _create_chat(client)
    assert client.post(f"/api/chats/{chat['id']}/memory/analyze").status_code == 404


def test_analyze_endpoint_reports_decision(client: TestClient, fake_api) -> None:
    _configure(client)
    chat = _create_chat(client)
    client.post(
        f"/api/chats/{chat['id']}/messages",
        json={"content": "Я предпочитаю Python"},
    )

    report = client.post(f"/api/chats/{chat['id']}/memory/analyze").json()
    assert report["short_term_saved"] is True
    assert report["long_term_accepted"]
    assert report["source"] in {"llm", "rules"}


def test_working_memory_validation_rejects_bad_payload(client: TestClient) -> None:
    chat = _create_chat(client)
    response = client.put(
        f"/api/chats/{chat['id']}/memory/working",
        json={"data": {"stack": "not-a-list"}},
    )
    assert response.status_code == 422

# ------------------------------------------------- LLM extraction path
@pytest.mark.asyncio
async def test_extractor_uses_llm_when_client_available(monkeypatch) -> None:
    """The LLM path is used (not the rule fallback) when a client is provided."""
    from backend.services.ai_client import AIClient

    calls = []

    async def fake_complete(self, model, messages, **kwargs):
        calls.append({"model": model, "messages": messages})
        return (
            '{"short_term": true,'
            ' "working_memory": {"task": "API магазина"},'
            ' "long_term_memory": [{"category": "preference",'
            ' "key": "preferred_language", "value": "Python", "confidence": 0.9}],'
            ' "summary": "llm"}'
        )

    monkeypatch.setattr(AIClient, "complete", fake_complete)

    client = AIClient("https://api.example.com/v1", "sk-test")
    extractor = MemoryExtractor(client, model="gpt-4o-mini")
    result = await extractor.extract("Я предпочитаю Python")

    assert result.source == "llm"
    assert result.working_memory is not None
    assert result.working_memory.task == "API магазина"
    assert result.long_term_candidates[0].value == "Python"
    # The chat's model is used for extraction.
    assert calls[0]["model"] == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_extractor_falls_back_when_llm_returns_garbage(monkeypatch) -> None:
    from backend.services.ai_client import AIClient

    async def fake_complete(self, model, messages, **kwargs):
        return "извините, не могу"

    monkeypatch.setattr(AIClient, "complete", fake_complete)

    client = AIClient("https://api.example.com/v1", "sk-test")
    extractor = MemoryExtractor(client, model="gpt-4o-mini")
    result = await extractor.extract("Я предпочитаю Python")

    assert result.source == "rules"
    assert any(c.key == "preferred_language" for c in result.long_term_candidates)


@pytest.mark.asyncio
async def test_extractor_without_model_uses_rules(monkeypatch) -> None:
    """A client without a model name must not crash the pipeline."""
    from backend.services.ai_client import AIClient

    client = AIClient("https://api.example.com/v1", "sk-test")
    extractor = MemoryExtractor(client)  # no model
    result = await extractor.extract("Я предпочитаю Python")

    assert result.source == "rules"


def test_analyze_uses_chat_model_for_extraction(
    client: TestClient, fake_api, monkeypatch
) -> None:
    """The extraction request is sent with the chat's model."""
    from backend.services.ai_client import AIClient

    seen_models = []
    original = AIClient.complete

    async def spy(self, model, messages, **kwargs):
        seen_models.append(model)
        return await original(self, model, messages, **kwargs)

    monkeypatch.setattr(AIClient, "complete", spy)

    _configure(client)
    chat = _create_chat(client, model="gpt-4o")
    client.post(f"/api/chats/{chat['id']}/messages", json={"content": "Привет"})

    assert "gpt-4o" in seen_models
