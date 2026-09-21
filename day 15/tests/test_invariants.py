"""Tests for invariants — mandatory constraints.

The point of these tests is that an invariant is *binding*: it reaches the
model on every request, a conflicting request is answered with the conflict
instead of the violating solution, and the rule is never changed by an ordinary
request.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.database.invariant_repository import InvariantRepository
from backend.database.repositories import ChatRepository
from backend.invariants.manager import InvariantManager
from backend.invariants.models import (
    ConflictCheckResult,
    InvariantConflict,
    InvariantCreate,
    InvariantData,
    InvariantUpdate,
)
from backend.memory.manager import MemoryManager
from backend.profile.manager import ProfileManager
from backend.services.prompt_builder import PromptBuilder


def _configure(client: TestClient) -> None:
    client.put(
        "/api/settings",
        json={"api_base_url": "https://api.example.com/v1", "api_key": "sk-test123456"},
    )


def _create_chat(client: TestClient, model: str = "gpt-4o-mini") -> dict:
    return client.post("/api/chats", json={"model": model}).json()


def _system_prompt(client: TestClient, fake_api) -> str:
    requests = fake_api.chat_requests()
    assert requests, "no chat completion request was recorded"
    return requests[-1]["json"]["messages"][0]["content"]


def _make_invariant(client: TestClient, **fields) -> dict:
    payload = {
        "scope": "global",
        "category": "constraint",
        "rule": "Не использовать Redis",
        "priority": "high",
    }
    payload.update(fields)
    response = client.post("/api/invariants", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _conflict_response(fake_api, invariant_id: str, rule: str, **extra):
    """Make the fake detector report a conflict with one rule."""
    payload = {
        "has_conflict": True,
        "conflicts": [
            {
                "invariant_id": invariant_id,
                "rule": rule,
                "requested": extra.get("requested", "Добавь Redis"),
                "reason": extra.get("reason", "правило запрещает Redis"),
            }
        ],
        "alternative": extra.get("alternative", ""),
        "explicit_change": extra.get("explicit_change", False),
        "change_targets": extra.get("change_targets", []),
    }
    import json as _json

    fake_api.conflict_response = fake_api.conflict_response.__class__(
        200,
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": _json.dumps(payload, ensure_ascii=False),
                    }
                }
            ]
        },
    )


# ------------------------------------------------------------ Test 1: create
def test_invariant_creation(client: TestClient) -> None:
    """Test 1 — an invariant is stored with all its fields."""
    created = _make_invariant(
        client,
        category="technology",
        rule="Backend must use FastAPI",
        description="Принято на старте проекта",
        priority="critical",
    )
    assert created["data"]["rule"] == "Backend must use FastAPI"
    assert created["data"]["category"] == "technology"
    assert created["data"]["priority"] == "critical"
    assert created["data"]["status"] == "active"
    assert created["data"]["scope"] == "global"
    assert created["exists"] is True

    reloaded = client.get(f"/api/invariants/{created['id']}").json()
    assert reloaded["data"] == created["data"]


def test_invariant_requires_a_rule(client: TestClient) -> None:
    assert client.post("/api/invariants", json={"rule": ""}).status_code == 422


def test_task_invariant_requires_task_id(client: TestClient) -> None:
    response = client.post(
        "/api/invariants", json={"scope": "task", "rule": "Use SQLite"}
    )
    assert response.status_code == 404


def test_invariant_update(client: TestClient) -> None:
    created = _make_invariant(client)
    response = client.put(
        f"/api/invariants/{created['id']}",
        json={"rule": "Не использовать Redis и Memcached", "priority": "critical"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["rule"] == "Не использовать Redis и Memcached"
    assert response.json()["data"]["priority"] == "critical"
    # Untouched fields survive.
    assert response.json()["data"]["category"] == "constraint"


def test_invariant_delete(client: TestClient) -> None:
    created = _make_invariant(client)
    assert client.delete(f"/api/invariants/{created['id']}").status_code == 204
    assert client.get(f"/api/invariants/{created['id']}").status_code == 404


def test_missing_invariant_returns_404(client: TestClient) -> None:
    assert client.get("/api/invariants/nope").status_code == 404
    assert client.put("/api/invariants/nope", json={"rule": "x"}).status_code == 404
    assert client.delete("/api/invariants/nope").status_code == 404


def test_activate_and_deactivate(client: TestClient) -> None:
    created = _make_invariant(client)

    deactivated = client.post(f"/api/invariants/{created['id']}/deactivate").json()
    assert deactivated["data"]["status"] == "inactive"
    # The rule is kept, not deleted.
    assert client.get(f"/api/invariants/{created['id']}").status_code == 200

    activated = client.post(f"/api/invariants/{created['id']}/activate").json()
    assert activated["data"]["status"] == "active"


def test_inactive_invariant_is_not_enforced(client: TestClient, fake_api) -> None:
    _configure(client)
    created = _make_invariant(client)
    client.post(f"/api/invariants/{created['id']}/deactivate")

    chat = _create_chat(client)
    client.post(f"/api/chats/{chat['id']}/messages", json={"content": "Привет"})

    assert "## ACTIVE INVARIANTS" not in _system_prompt(client, fake_api)


# ------------------------------------------------- Test 2: included in prompt
def test_invariant_included_in_prompt(client: TestClient, fake_api) -> None:
    """Test 2 — an active invariant reaches the model."""
    _configure(client)
    _make_invariant(client, rule="Backend must use FastAPI", category="technology")

    chat = _create_chat(client)
    client.post(f"/api/chats/{chat['id']}/messages", json={"content": "Привет"})

    system = _system_prompt(client, fake_api)
    assert "## ACTIVE INVARIANTS" in system
    assert "Backend must use FastAPI" in system
    assert "Technology:" in system


def test_invariant_rules_are_explained_to_the_model(
    client: TestClient, fake_api
) -> None:
    """The model is told how to treat invariants."""
    _configure(client)
    _make_invariant(client)

    chat = _create_chat(client)
    client.post(f"/api/chats/{chat['id']}/messages", json={"content": "Привет"})

    system = _system_prompt(client, fake_api)
    assert "INVARIANT RULES" in system
    assert "mandatory constraints" in system
    assert "explicitly requests to change it" in system


def test_critical_priority_is_marked_in_prompt(client: TestClient, fake_api) -> None:
    _configure(client)
    _make_invariant(client, rule="Production database must be PostgreSQL", priority="critical")

    chat = _create_chat(client)
    client.post(f"/api/chats/{chat['id']}/messages", json={"content": "Привет"})

    system = _system_prompt(client, fake_api)
    assert "Production database must be PostgreSQL [CRITICAL]" in system


def test_no_invariants_means_no_block(client: TestClient, fake_api) -> None:
    _configure(client)
    chat = _create_chat(client)
    client.post(f"/api/chats/{chat['id']}/messages", json={"content": "Привет"})

    system = _system_prompt(client, fake_api)
    assert "## ACTIVE INVARIANTS" not in system
    assert "INVARIANT RULES" not in system


def test_prompt_block_endpoint(client: TestClient) -> None:
    _make_invariant(client, rule="Use SQLite", category="technology")
    payload = client.get("/api/invariants").json()
    assert payload["invariants"][0]["data"]["rule"] == "Use SQLite"


# ------------------------------------------------------------ Test 3: no conflict
def test_no_conflict(client: TestClient, fake_api) -> None:
    """Test 3 — a compatible request is answered normally."""
    _configure(client)
    _make_invariant(client, rule="Use FastAPI", category="technology")

    chat = _create_chat(client)
    response = client.post(
        f"/api/chats/{chat['id']}/messages",
        json={"content": "Add Pydantic validation."},
    )

    assert response.status_code == 200
    # The normal answer, not a conflict explanation.
    assert response.json()["assistant_message"]["content"] == "Привет!"
    assert "конфликтует" not in response.json()["assistant_message"]["content"]


def test_check_endpoint_reports_no_conflict(client: TestClient, fake_api) -> None:
    _configure(client)
    _create_chat(client)
    _make_invariant(client, rule="Use FastAPI")
    result = client.post(
        "/api/invariants/check", json={"request": "Add Pydantic validation."}
    ).json()
    assert result["has_conflict"] is False
    assert result["conflicts"] == []


def test_check_endpoint_without_invariants(client: TestClient) -> None:
    result = client.post("/api/invariants/check", json={"request": "anything"}).json()
    assert result["has_conflict"] is False
    assert result["source"] == "no-invariants"


def test_check_endpoint_requires_request(client: TestClient) -> None:
    assert client.post("/api/invariants/check", json={}).status_code == 404


# -------------------------------------------------------- Test 4: direct conflict
def test_direct_conflict(client: TestClient, fake_api) -> None:
    """Test 4 — switching the database conflicts with the SQLite rule."""
    _configure(client)
    invariant = _make_invariant(
        client, rule="Use SQLite", category="technology", priority="critical"
    )
    _conflict_response(
        fake_api,
        invariant["id"],
        "Use SQLite",
        requested="Switch database to PostgreSQL",
        reason="правило требует SQLite",
    )

    chat = _create_chat(client)
    response = client.post(
        f"/api/chats/{chat['id']}/messages",
        json={"content": "Switch database to PostgreSQL."},
    )

    answer = response.json()["assistant_message"]["content"]
    assert "конфликтует" in answer
    assert "Use SQLite" in answer
    assert "Switch database to PostgreSQL" in answer


def test_conflict_check_endpoint(client: TestClient, fake_api) -> None:
    _configure(client)
    _create_chat(client)  # the check borrows the model from a chat
    invariant = _make_invariant(client, rule="Use SQLite")
    _conflict_response(fake_api, invariant["id"], "Use SQLite")

    result = client.post(
        "/api/invariants/check", json={"request": "Switch to PostgreSQL"}
    ).json()
    assert result["has_conflict"] is True
    assert result["conflicts"][0]["rule"] == "Use SQLite"
    assert result["conflicts"][0]["priority"] == "high"


def test_conflict_with_unknown_rule_is_dropped(client: TestClient, fake_api) -> None:
    """The model cannot invent a rule that is not active."""
    _configure(client)
    _create_chat(client)
    _make_invariant(client, rule="Use SQLite")
    _conflict_response(fake_api, "made-up-id", "Use MongoDB")

    result = client.post(
        "/api/invariants/check", json={"request": "Switch to MongoDB"}
    ).json()
    assert result["has_conflict"] is False


# --------------------------------------------------- Test 5: prohibited solution
def test_prohibited_solution_is_not_offered(client: TestClient, fake_api) -> None:
    """Test 5 — Redis is not proposed; the conflict is explained."""
    _configure(client)
    invariant = _make_invariant(client, rule="Do not use Redis")
    _conflict_response(
        fake_api,
        invariant["id"],
        "Do not use Redis",
        requested="Implement Redis caching",
        alternative="кеширование на уровне приложения",
    )

    chat = _create_chat(client)
    response = client.post(
        f"/api/chats/{chat['id']}/messages",
        json={"content": "Implement Redis caching."},
    )
    answer = response.json()["assistant_message"]["content"]

    # The conflict is explicit...
    assert "конфликтует" in answer
    assert "Do not use Redis" in answer
    # ...the rule is not changed automatically...
    assert "не буду менять это ограничение автоматически" in answer
    # ...and a compatible alternative is offered.
    assert "кеширование на уровне приложения" in answer

    # The model was never asked for a solution.
    assert fake_api.chat_requests() == []


def test_conflict_answer_is_persisted(client: TestClient, fake_api) -> None:
    _configure(client)
    invariant = _make_invariant(client, rule="Do not use Redis")
    _conflict_response(fake_api, invariant["id"], "Do not use Redis")

    chat = _create_chat(client)
    client.post(f"/api/chats/{chat['id']}/messages", json={"content": "Add Redis"})

    messages = client.get(f"/api/chats/{chat['id']}/messages").json()["messages"]
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert "конфликтует" in messages[-1]["content"]


def test_conflict_in_streaming(client: TestClient, fake_api) -> None:
    """The streaming path answers the conflict too."""
    _configure(client)
    invariant = _make_invariant(client, rule="Do not use Redis")
    _conflict_response(fake_api, invariant["id"], "Do not use Redis")

    chat = _create_chat(client)
    response = client.post(
        f"/api/chats/{chat['id']}/messages/stream", json={"content": "Add Redis"}
    )
    assert response.status_code == 200
    assert "конфликтует" in response.text


# ------------------------------------------------ Test 6: explicit change
def test_explicit_invariant_change(client: TestClient) -> None:
    """Test 6 — an explicit decision change replaces the rule."""
    old = _make_invariant(client, rule="Use SQLite", category="technology")

    result = ConflictCheckResult(
        has_conflict=True,
        conflicts=[
            InvariantConflict(
                invariant_id=old["id"], rule="Use SQLite", requested="PostgreSQL"
            )
        ],
        explicit_change=True,
        change_targets=[old["id"]],
    )

    from backend.database.database import get_database

    service_manager = InvariantManager(InvariantRepository(get_database()))
    created = service_manager.replace_rule(
        old_invariant_id=old["id"], new_rule="Use PostgreSQL"
    )

    # The old rule is deactivated, not deleted.
    assert client.get(f"/api/invariants/{old['id']}").json()["data"]["status"] == "inactive"
    # The new rule is active.
    assert created.data.status == "active"
    assert created.data.rule == "Use PostgreSQL"

    active = client.get("/api/invariants", params={"status": "active"}).json()
    rules = [item["data"]["rule"] for item in active["invariants"]]
    assert "Use PostgreSQL" in rules
    assert "Use SQLite" not in rules


def test_ordinary_request_does_not_change_invariant(
    client: TestClient, fake_api
) -> None:
    """A plain request must never modify a rule."""
    _configure(client)
    invariant = _make_invariant(client, rule="Use SQLite")
    _conflict_response(
        fake_api, invariant["id"], "Use SQLite", explicit_change=False
    )

    chat = _create_chat(client)
    client.post(
        f"/api/chats/{chat['id']}/messages", json={"content": "Switch to PostgreSQL"}
    )

    stored = client.get(f"/api/invariants/{invariant['id']}").json()
    assert stored["data"]["status"] == "active"
    assert stored["data"]["rule"] == "Use SQLite"


def test_explicit_change_is_reported_by_the_check(client: TestClient, fake_api) -> None:
    _configure(client)
    _create_chat(client)
    invariant = _make_invariant(client, rule="Use SQLite")
    _conflict_response(
        fake_api,
        invariant["id"],
        "Use SQLite",
        explicit_change=True,
        change_targets=[invariant["id"]],
    )

    result = client.post(
        "/api/invariants/check",
        json={"request": "Мы приняли новое решение. Теперь используем PostgreSQL."},
    ).json()
    assert result["explicit_change"] is True
    assert result["change_targets"] == [invariant["id"]]


# ------------------------------------------------------------ Test 7: persistence
def test_invariant_persists_after_restart(client: TestClient, app_config) -> None:
    """Test 7 — invariants survive a restart."""
    created = _make_invariant(
        client, rule="Backend must use FastAPI", priority="critical"
    )

    from backend.main import create_app

    with TestClient(create_app()) as second_client:
        reloaded = second_client.get(f"/api/invariants/{created['id']}").json()
        assert reloaded["data"]["rule"] == "Backend must use FastAPI"
        assert reloaded["data"]["priority"] == "critical"
        assert reloaded["data"]["status"] == "active"


def test_invariant_survives_repository_reopen(database) -> None:
    manager = InvariantManager(InvariantRepository(database))
    created = manager.create_invariant(
        InvariantCreate(rule="Use SQLite", category="technology")
    )

    reopened = InvariantManager(InvariantRepository(database))
    assert reopened.get(created.id).data.rule == "Use SQLite"


# ------------------------------------------------------------ Test 8: isolation
def test_task_invariants_are_isolated(client: TestClient, fake_api) -> None:
    """Test 8 — one task's rules never apply to another."""
    _configure(client)
    task_a = _create_chat(client)
    task_b = _create_chat(client)

    client.post(
        f"/api/tasks/{task_a['id']}/invariants",
        json={"rule": "Database = SQLite", "category": "technology"},
    )
    client.post(
        f"/api/tasks/{task_b['id']}/invariants",
        json={"rule": "Database = PostgreSQL", "category": "technology"},
    )

    a_rules = client.get(f"/api/tasks/{task_a['id']}/invariants").json()["invariants"]
    b_rules = client.get(f"/api/tasks/{task_b['id']}/invariants").json()["invariants"]

    assert [item["data"]["rule"] for item in a_rules] == ["Database = SQLite"]
    assert [item["data"]["rule"] for item in b_rules] == ["Database = PostgreSQL"]


def test_task_invariant_reaches_only_its_own_prompt(
    client: TestClient, fake_api
) -> None:
    _configure(client)
    task_a = _create_chat(client)
    task_b = _create_chat(client)

    client.post(
        f"/api/tasks/{task_a['id']}/invariants",
        json={"rule": "Database = SQLite", "category": "technology"},
    )

    client.post(f"/api/chats/{task_a['id']}/messages", json={"content": "Привет"})
    a_system = _system_prompt(client, fake_api)
    assert "Database = SQLite" in a_system

    client.post(f"/api/chats/{task_b['id']}/messages", json={"content": "Привет"})
    b_system = _system_prompt(client, fake_api)
    assert "Database = SQLite" not in b_system


def test_global_invariant_applies_to_every_task(client: TestClient, fake_api) -> None:
    _configure(client)
    _make_invariant(client, rule="Do not use Redis")
    task_a = _create_chat(client)
    task_b = _create_chat(client)

    client.post(f"/api/chats/{task_a['id']}/messages", json={"content": "Привет"})
    assert "Do not use Redis" in _system_prompt(client, fake_api)

    client.post(f"/api/chats/{task_b['id']}/messages", json={"content": "Привет"})
    assert "Do not use Redis" in _system_prompt(client, fake_api)


def test_task_invariants_removed_with_task(client: TestClient) -> None:
    chat = _create_chat(client)
    created = client.post(
        f"/api/tasks/{chat['id']}/invariants", json={"rule": "Use SQLite"}
    ).json()

    client.delete(f"/api/chats/{chat['id']}")

    assert client.get(f"/api/invariants/{created['id']}").status_code == 404


def test_global_invariants_survive_task_deletion(client: TestClient) -> None:
    global_invariant = _make_invariant(client, rule="Do not use Redis")
    chat = _create_chat(client)

    client.delete(f"/api/chats/{chat['id']}")

    assert client.get(f"/api/invariants/{global_invariant['id']}").status_code == 200


# ------------------------------------------------------------ unit level
def test_manager_sorts_by_priority(database) -> None:
    manager = InvariantManager(InvariantRepository(database))
    manager.create_invariant(InvariantCreate(rule="low rule", priority="low"))
    manager.create_invariant(InvariantCreate(rule="critical rule", priority="critical"))
    manager.create_invariant(InvariantCreate(rule="high rule", priority="high"))

    rules = [item.data.rule for item in manager.list_invariants()]
    assert rules == ["critical rule", "high rule", "low rule"]


def test_manager_groups_prompt_block_by_category(database) -> None:
    manager = InvariantManager(InvariantRepository(database))
    manager.create_invariant(
        InvariantCreate(rule="Use monolith", category="architecture")
    )
    manager.create_invariant(
        InvariantCreate(rule="Backend: FastAPI", category="technology")
    )

    block = manager.build_prompt_block()
    assert "## ACTIVE INVARIANTS" in block
    assert "Architecture:" in block
    assert "Technology:" in block
    assert "- Use monolith" in block


def test_manager_prompt_block_empty_without_invariants(database) -> None:
    manager = InvariantManager(InvariantRepository(database))
    assert manager.build_prompt_block() == ""


def test_manager_activate_is_idempotent(database) -> None:
    manager = InvariantManager(InvariantRepository(database))
    created = manager.create_invariant(InvariantCreate(rule="Use SQLite"))

    manager.activate_invariant(created.id)
    manager.activate_invariant(created.id)
    assert manager.get(created.id).data.status == "active"

    manager.deactivate_invariant(created.id)
    manager.deactivate_invariant(created.id)
    assert manager.get(created.id).data.status == "inactive"


def test_manager_check_conflict_without_result(database) -> None:
    manager = InvariantManager(InvariantRepository(database))
    manager.create_invariant(InvariantCreate(rule="Use SQLite"))

    result = manager.check_conflict("anything", result=None)
    assert result.has_conflict is False
    assert result.source == "unavailable"


def test_manager_check_conflict_without_invariants(database) -> None:
    manager = InvariantManager(InvariantRepository(database))
    result = manager.check_conflict("anything")
    assert result.has_conflict is False
    assert result.source == "no-invariants"


def test_manager_validates_conflict_against_active_rules(database) -> None:
    manager = InvariantManager(InvariantRepository(database))
    created = manager.create_invariant(
        InvariantCreate(rule="Use SQLite", category="technology", priority="critical")
    )

    proposal = ConflictCheckResult(
        has_conflict=True,
        conflicts=[
            InvariantConflict(
                invariant_id=created.id, rule="Use SQLite", requested="PostgreSQL"
            )
        ],
    )
    result = manager.check_conflict("Switch to PostgreSQL", result=proposal)

    assert result.has_conflict is True
    assert result.conflicts[0].rule == "Use SQLite"
    assert result.conflicts[0].priority == "critical"


def test_manager_drops_conflict_with_inactive_rule(database) -> None:
    manager = InvariantManager(InvariantRepository(database))
    created = manager.create_invariant(InvariantCreate(rule="Use SQLite"))
    manager.deactivate_invariant(created.id)

    proposal = ConflictCheckResult(
        has_conflict=True,
        conflicts=[InvariantConflict(invariant_id=created.id, rule="Use SQLite")],
    )
    result = manager.check_conflict("Switch to PostgreSQL", result=proposal)
    assert result.has_conflict is False


def test_manager_replace_rule_keeps_scope_and_task(database) -> None:
    manager = InvariantManager(InvariantRepository(database))
    old = manager.create_invariant(
        InvariantCreate(
            scope="task", task_id="task-1", rule="Use SQLite", category="technology"
        )
    )

    created = manager.replace_rule(old_invariant_id=old.id, new_rule="Use PostgreSQL")
    assert created.data.scope == "task"
    assert created.data.task_id == "task-1"
    assert created.data.category == "technology"
    assert manager.get(old.id).data.status == "inactive"


def test_prompt_builder_includes_invariants(database) -> None:
    chat_id = ChatRepository(database).create(model="m").id
    invariants = InvariantManager(InvariantRepository(database))
    invariants.create_invariant(InvariantCreate(rule="Do not use Redis"))

    builder = PromptBuilder(
        memory=MemoryManager(),
        profile=ProfileManager(),
        invariants=invariants,
    )
    system = builder.build_messages(chat_id)[0]["content"]
    assert "## ACTIVE INVARIANTS" in system
    assert "Do not use Redis" in system
    assert "INVARIANT RULES" in system


def test_prompt_builder_without_invariant_manager(database) -> None:
    chat_id = ChatRepository(database).create(model="m").id
    builder = PromptBuilder(memory=MemoryManager(), profile=ProfileManager())
    system = builder.build_messages(chat_id)[0]["content"]
    assert "## ACTIVE INVARIANTS" not in system


def test_prompt_order_invariants_after_task_state(database) -> None:
    """profile → long-term → working → task state → invariants."""
    from backend.database.task_repository import TaskStateRepository
    from backend.tasks.manager import TaskStateManager

    chat_id = ChatRepository(database).create(model="m").id
    memory = MemoryManager()
    tasks = TaskStateManager(TaskStateRepository(database))
    invariants = InvariantManager(InvariantRepository(database))

    memory.save_to_long_term(
        category="preference", key="preferred_language", value="Python"
    )
    tasks.create_state(chat_id)
    tasks.transition(chat_id, "execution")
    invariants.create_invariant(InvariantCreate(rule="Do not use Redis"))

    builder = PromptBuilder(
        memory=memory, profile=ProfileManager(), tasks=tasks, invariants=invariants
    )
    system = builder.build_messages(chat_id)[0]["content"]

    long_term_at = system.index("## Long-term memory")
    task_at = system.index("## TASK STATE")
    invariant_at = system.index("## ACTIVE INVARIANTS")
    assert long_term_at < task_at < invariant_at


def test_invariants_do_not_touch_memory_or_task_state(
    client: TestClient, fake_api
) -> None:
    """Invariants are a separate layer."""
    _configure(client)
    _make_invariant(client, rule="Do not use Redis")

    assert client.get("/api/memory/long-term").json()["entries"] == []
    chat = _create_chat(client)
    assert client.get(f"/api/tasks/{chat['id']}/state").json()["exists"] is False


def test_memory_does_not_create_invariants(client: TestClient, fake_api) -> None:
    _configure(client)
    chat = _create_chat(client)
    client.post(f"/api/chats/{chat['id']}/messages", json={"content": "Я предпочитаю Python"})

    assert client.get("/api/invariants").json()["invariants"] == []
    assert client.get("/api/memory/long-term").json()["entries"]


def test_profile_does_not_create_invariants(client: TestClient) -> None:
    client.put(
        "/api/profile",
        json={"data": {"language": "ru", "style": "concise"}},
    )
    assert client.get("/api/invariants").json()["invariants"] == []


def test_invariant_data_defaults() -> None:
    data = InvariantData()
    assert data.scope == "global"
    assert data.category == "other"
    assert data.priority == "medium"
    assert data.status == "active"
    assert data.is_active() is True


def test_invariant_update_payload_strips_whitespace() -> None:
    payload = InvariantUpdate(rule="  Use SQLite  ", description="  why  ")
    assert payload.rule == "Use SQLite"
    assert payload.description == "why"


@pytest.mark.asyncio
async def test_detector_without_client_is_unavailable() -> None:
    from backend.invariants.detector import InvariantConflictDetector

    detector = InvariantConflictDetector(None)
    result = await detector.check("anything", [])
    assert result.has_conflict is False
    assert result.source == "no-invariants"


def test_detector_parses_model_answer() -> None:
    from backend.invariants.detector import InvariantConflictDetector

    result = InvariantConflictDetector._to_result(
        {
            "has_conflict": True,
            "conflicts": [
                {
                    "invariant_id": "abc",
                    "rule": "Do not use Redis",
                    "requested": "Add Redis",
                    "reason": "forbidden",
                }
            ],
            "alternative": "in-process cache",
            "explicit_change": False,
            "change_targets": [],
        }
    )
    assert result.has_conflict is True
    assert result.conflicts[0].rule == "Do not use Redis"
    assert result.alternative == "in-process cache"


def test_detector_ignores_conflict_without_rules() -> None:
    from backend.invariants.detector import InvariantConflictDetector

    result = InvariantConflictDetector._to_result(
        {"has_conflict": True, "conflicts": []}
    )
    assert result.has_conflict is False


def test_detector_parses_json_with_fences() -> None:
    from backend.invariants.detector import InvariantConflictDetector

    payload = InvariantConflictDetector._parse_json(
        '```json\n{"has_conflict": false, "conflicts": []}\n```'
    )
    assert payload == {"has_conflict": False, "conflicts": []}


def test_detector_returns_none_for_garbage() -> None:
    from backend.invariants.detector import InvariantConflictDetector

    assert InvariantConflictDetector._parse_json("не json") is None
    assert InvariantConflictDetector._parse_json("") is None

# ------------------------------------------------- explicit change applied
def test_explicit_change_is_applied_not_just_reported(
    client: TestClient, fake_api
) -> None:
    """An explicit change deactivates the old rule and activates the new one."""
    _configure(client)
    old = _make_invariant(client, rule="Не использовать Redis")
    _conflict_response(
        fake_api,
        old["id"],
        "Не использовать Redis",
        explicit_change=True,
        change_targets=[old["id"]],
    )

    chat = _create_chat(client)
    response = client.post(
        f"/api/chats/{chat['id']}/messages",
        json={"content": "Мы отменяем это ограничение. Теперь Redis разрешён."},
    )
    answer = response.json()["assistant_message"]["content"]
    assert "Инвариант обновлён" in answer
    assert "Не использовать Redis" in answer

    # The old rule is deactivated, the new one is active.
    assert client.get(f"/api/invariants/{old['id']}").json()["data"]["status"] == "inactive"
    active = client.get("/api/invariants", params={"status": "active"}).json()
    rules = [item["data"]["rule"] for item in active["invariants"]]
    assert "Redis разрешён" in rules
    assert "Не использовать Redis" not in rules


def test_ordinary_request_does_not_apply_a_change(
    client: TestClient, fake_api
) -> None:
    """Without explicit_change the rule stays active."""
    _configure(client)
    old = _make_invariant(client, rule="Не использовать Redis")
    _conflict_response(
        fake_api, old["id"], "Не использовать Redis", explicit_change=False
    )

    chat = _create_chat(client)
    client.post(
        f"/api/chats/{chat['id']}/messages", json={"content": "Добавь Redis"}
    )

    assert client.get(f"/api/invariants/{old['id']}").json()["data"]["status"] == "active"


def test_new_rule_text_is_cleaned() -> None:
    """The stored rule reads as a rule, not as a sentence."""
    from backend.services.chat_service import ChatService

    assert (
        ChatService._derive_new_rule(
            "Мы отменяем это ограничение. Теперь Redis разрешён. "
            "Измени соответствующий инвариант.",
            [],
        )
        == "Redis разрешён"
    )
    assert (
        ChatService._derive_new_rule(
            "Мы приняли новое решение. Теперь используем PostgreSQL вместо SQLite.",
            [],
        )
        == "используем PostgreSQL вместо SQLite"
    )


def test_new_rule_falls_back_to_old_rule_for_long_messages() -> None:
    from backend.services.chat_service import ChatService

    class _Target:
        class data:  # noqa: N801 - mimics the Invariant shape
            rule = "Use SQLite"

    long_text = "x" * 400
    rule = ChatService._derive_new_rule(long_text, [_Target()])
    assert rule.startswith("Use SQLite (изменено:")
