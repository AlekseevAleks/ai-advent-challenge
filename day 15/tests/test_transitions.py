"""Tests for the configurable task lifecycle.

The point of this layer is that the AI may *decide* that a transition is
needed, but only ``TransitionManager`` may *perform* it, using the rules the
user configured. These tests cover:

* states — create, rename, activate, delete, initial/final;
* rules — create, update, delete, activate, duplicate and invalid edges;
* conditions — the structured evaluator and its refusal messages;
* transitions — allowed, refused, and the history of both;
* the AI path — the model proposes, the manager disposes;
* persistence and dynamic updates without a restart;
* pause/resume keeping the stage.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.database.repositories import ChatRepository
from backend.database.task_repository import TaskStateRepository
from backend.database.transition_repository import (
    TaskStateDefinitionRepository,
    TransitionHistoryRepository,
    TransitionRuleRepository,
)
from backend.tasks.manager import TaskStateManager
from backend.transitions.conditions import (
    conditions_hold,
    evaluate_condition,
    first_failure,
)
from backend.transitions.manager import (
    DuplicateRuleError,
    InvalidRuleError,
    StateInUseError,
    TransitionManager,
)
from backend.transitions.models import (
    Condition,
    TaskStateDefinitionCreate,
    TaskStateDefinitionUpdate,
    TransitionRuleCreate,
    TransitionRuleUpdate,
    TransitionSuggestion,
)


def _configure(client: TestClient) -> None:
    client.put(
        "/api/settings",
        json={"api_base_url": "https://api.example.com/v1", "api_key": "sk-test123456"},
    )


def _create_chat(client: TestClient, model: str = "gpt-4o-mini") -> dict:
    return client.post("/api/chats", json={"model": model}).json()


def _manager(database) -> TransitionManager:
    tasks = TaskStateManager(TaskStateRepository(database))
    return TransitionManager(
        states=TaskStateDefinitionRepository(database),
        rules=TransitionRuleRepository(database),
        history=TransitionHistoryRepository(database),
        tasks=tasks,
    )


def _rule_for(client: TestClient, from_state: str, to_state: str) -> dict:
    rules = client.get("/api/transition-rules").json()["rules"]
    for rule in rules:
        if rule["from_state"] == from_state and rule["to_state"] == to_state:
            return rule
    raise AssertionError(f"rule {from_state} → {to_state} not found")


def _set_condition(client: TestClient, rule_id: str, field: str, value: str) -> dict:
    response = client.put(
        f"/api/transition-rules/{rule_id}",
        json={
            "condition": f"{field} == {value}",
            "conditions": [
                {"type": "field_equals", "field": field, "value": value}
            ],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _set_fact(client: TestClient, task_id: str, **facts) -> None:
    response = client.put(
        f"/api/tasks/{task_id}/state", json={"metadata": facts}
    )
    assert response.status_code == 200, response.text


def _report_conflict(fake_api, invariant_id: str, rule: str) -> None:
    """Make the fake invariant detector report a conflict with one rule."""
    fake_api.conflict_response = fake_api.conflict_response.__class__(
        200,
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(
                            {
                                "has_conflict": True,
                                "conflicts": [
                                    {
                                        "invariant_id": invariant_id,
                                        "rule": rule,
                                        "requested": "Add Redis",
                                        "reason": "правило запрещает Redis",
                                    }
                                ],
                                "alternative": "",
                                "explicit_change": False,
                                "change_targets": [],
                            },
                            ensure_ascii=False,
                        ),
                    }
                }
            ]
        },
    )


def _pin_step_extractor(fake_api) -> None:
    """Make the step extractor propose no stage change.

    It runs in the same background batch as the gate, and a stage it moved on
    its own would make the assertions about the gate ambiguous.
    """
    fake_api.step_response = fake_api.step_response.__class__(
        200,
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": (
                            '{"current_step": "implement authentication",'
                            ' "expected_action": "create login endpoint",'
                            ' "confidence": 0.9}'
                        ),
                    }
                }
            ]
        },
    )


def _propose_transition(fake_api, to_state: str, confidence: float = 0.9) -> None:
    """Make the fake detector propose a transition.

    The step extractor is pinned to the current stage at the same time: it runs
    in the same background batch, and a stage it moved on its own would make
    the transition proposal ambiguous.
    """
    fake_api.transition_response = fake_api.transition_response.__class__(
        200,
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(
                            {
                                "to_state": to_state,
                                "reason": "пользователь подтвердил этап",
                                "confidence": confidence,
                            },
                            ensure_ascii=False,
                        ),
                    }
                }
            ]
        },
    )
    fake_api.step_response = fake_api.step_response.__class__(
        200,
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": (
                            '{"current_step": "implement authentication",'
                            ' "expected_action": "create login endpoint",'
                            ' "confidence": 0.9}'
                        ),
                    }
                }
            ]
        },
    )


# ------------------------------------------------------------------- states
def test_default_lifecycle_is_seeded(client: TestClient) -> None:
    """A fresh install already has the four built-in states and three rules."""
    payload = client.get("/api/task-states").json()
    names = [item["id"] for item in payload["states"]]
    assert names == ["planning", "execution", "validation", "done"]
    assert payload["initial_state"] == "planning"
    assert payload["final_states"] == ["done"]

    rules = client.get("/api/transition-rules").json()["rules"]
    edges = [(rule["from_state"], rule["to_state"]) for rule in rules]
    assert edges == [
        ("planning", "execution"),
        ("execution", "validation"),
        ("validation", "done"),
    ]


def test_create_state(client: TestClient) -> None:
    response = client.post(
        "/api/task-states",
        json={"name": "Review", "description": "Проверка результата"},
    )
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["name"] == "Review"
    assert created["description"] == "Проверка результата"
    assert created["active"] is True
    assert created["is_initial"] is False
    assert created["is_final"] is False

    reloaded = client.get(f"/api/task-states/{created['id']}").json()
    assert reloaded["name"] == "Review"


def test_update_state(client: TestClient) -> None:
    created = client.post("/api/task-states", json={"name": "Review"}).json()
    response = client.put(
        f"/api/task-states/{created['id']}",
        json={"name": "Code review", "description": "Ревью кода", "is_final": True},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Code review"
    assert data["description"] == "Ревью кода"
    assert data["is_final"] is True
    # The id is stable, so existing rules keep pointing at the same state.
    assert data["id"] == created["id"]


def test_deactivate_and_activate_state(client: TestClient) -> None:
    created = client.post("/api/task-states", json={"name": "Review"}).json()

    off = client.put(
        f"/api/task-states/{created['id']}", json={"active": False}
    ).json()
    assert off["active"] is False

    on = client.put(
        f"/api/task-states/{created['id']}", json={"active": True}
    ).json()
    assert on["active"] is True


def test_delete_unused_state(client: TestClient) -> None:
    created = client.post("/api/task-states", json={"name": "Review"}).json()
    assert client.delete(f"/api/task-states/{created['id']}").status_code == 204
    assert client.get(f"/api/task-states/{created['id']}").status_code == 404


def test_cannot_delete_state_used_by_a_rule(client: TestClient) -> None:
    """A state referenced by a rule is protected until the rule is removed."""
    response = client.delete("/api/task-states/execution")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "state_in_use"
    # The state is still there.
    assert client.get("/api/task-states/execution").status_code == 200


def test_state_can_be_deleted_after_its_rules(client: TestClient) -> None:
    """Once no rule mentions the state, it can be removed."""
    for from_state, to_state in (("planning", "execution"), ("execution", "validation")):
        rule = _rule_for(client, from_state, to_state)
        client.delete(f"/api/transition-rules/{rule['id']}")

    assert client.delete("/api/task-states/execution").status_code == 204


def test_only_one_initial_state(client: TestClient) -> None:
    created = client.post("/api/task-states", json={"name": "Review"}).json()
    client.put(f"/api/task-states/{created['id']}", json={"is_initial": True})

    payload = client.get("/api/task-states").json()
    initial = [item["id"] for item in payload["states"] if item["is_initial"]]
    assert initial == [created["id"]]
    assert payload["initial_state"] == created["id"]


def test_missing_state_returns_404(client: TestClient) -> None:
    assert client.get("/api/task-states/nope").status_code == 404
    assert client.put("/api/task-states/nope", json={"name": "x"}).status_code == 404
    assert client.delete("/api/task-states/nope").status_code == 404


# -------------------------------------------------------------------- rules
def test_create_rule(client: TestClient) -> None:
    client.post("/api/task-states", json={"name": "Review"})
    response = client.post(
        "/api/transition-rules",
        json={
            "from_state": "validation",
            "to_state": "review",
            "name": "Start review",
            "description": "Проверка результата",
            "condition": "review_requested == true",
            "conditions": [
                {"type": "boolean_true", "field": "review_requested"}
            ],
        },
    )
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["from_state"] == "validation"
    assert created["to_state"] == "review"
    assert created["name"] == "Start review"
    assert created["active"] is True
    assert created["conditions"][0]["type"] == "boolean_true"


def test_rule_requires_existing_states(client: TestClient) -> None:
    response = client.post(
        "/api/transition-rules",
        json={"from_state": "planning", "to_state": "nope"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_rule"


def test_rule_cannot_point_at_itself(client: TestClient) -> None:
    response = client.post(
        "/api/transition-rules",
        json={"from_state": "planning", "to_state": "planning"},
    )
    assert response.status_code == 422


def test_duplicate_rule_is_refused(client: TestClient) -> None:
    response = client.post(
        "/api/transition-rules",
        json={"from_state": "planning", "to_state": "execution"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "duplicate_rule"


def test_update_rule(client: TestClient) -> None:
    rule = _rule_for(client, "planning", "execution")
    response = client.put(
        f"/api/transition-rules/{rule['id']}",
        json={"name": "Begin work", "condition": "Plan approved"},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Begin work"
    assert response.json()["condition"] == "Plan approved"


def test_delete_rule(client: TestClient) -> None:
    rule = _rule_for(client, "validation", "done")
    assert client.delete(f"/api/transition-rules/{rule['id']}").status_code == 204
    assert client.get(f"/api/transition-rules/{rule['id']}").status_code == 404


def test_deactivate_rule_blocks_the_move(client: TestClient) -> None:
    """A deactivated rule stops allowing the transition."""
    rule = _rule_for(client, "planning", "execution")
    client.post(f"/api/transition-rules/{rule['id']}/deactivate")

    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    outcome = client.post(
        f"/api/tasks/{task_id}/transitions/apply", json={"to_state": "execution"}
    ).json()
    assert outcome["allowed"] is False
    assert "Нет активного правила" in outcome["reason"]
    assert client.get(f"/api/tasks/{task_id}/state").json()["data"]["stage"] == "planning"


def test_activate_rule_allows_the_move_again(client: TestClient) -> None:
    rule = _rule_for(client, "planning", "execution")
    client.post(f"/api/transition-rules/{rule['id']}/deactivate")
    client.post(f"/api/transition-rules/{rule['id']}/activate")

    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    outcome = client.post(
        f"/api/tasks/{task_id}/transitions/apply", json={"to_state": "execution"}
    ).json()
    assert outcome["allowed"] is True


def test_rule_check_endpoint(client: TestClient) -> None:
    rule = _rule_for(client, "planning", "execution")
    _set_condition(client, rule["id"], "plan_status", "approved")

    pending = client.post(
        f"/api/transition-rules/{rule['id']}/check",
        json={"facts": {"plan_status": "pending"}},
    ).json()
    assert pending["satisfied"] is False
    assert pending["actual"] == "pending"

    approved = client.post(
        f"/api/transition-rules/{rule['id']}/check",
        json={"facts": {"plan_status": "approved"}},
    ).json()
    assert approved["satisfied"] is True


def test_rule_without_conditions_is_always_satisfied(client: TestClient) -> None:
    rule = _rule_for(client, "execution", "validation")
    result = client.post(
        f"/api/transition-rules/{rule['id']}/check", json={}
    ).json()
    assert result["satisfied"] is True


def test_condition_requires_a_field(client: TestClient) -> None:
    response = client.post(
        "/api/transition-rules",
        json={
            "from_state": "planning",
            "to_state": "validation",
            "conditions": [{"type": "field_equals", "field": "", "value": "x"}],
        },
    )
    assert response.status_code == 422


def test_unknown_condition_type_is_refused(client: TestClient) -> None:
    response = client.post(
        "/api/transition-rules",
        json={
            "from_state": "planning",
            "to_state": "validation",
            "conditions": [{"type": "run_shell", "field": "x", "value": "y"}],
        },
    )
    assert response.status_code == 422


# --------------------------------------------------------------- conditions
def test_condition_field_equals() -> None:
    condition = Condition(type="field_equals", field="plan_status", value="approved")
    assert evaluate_condition(condition, {"plan_status": "approved"}).satisfied is True
    assert evaluate_condition(condition, {"plan_status": "pending"}).satisfied is False
    # Comparison is case-insensitive, so "Approved" also passes.
    assert evaluate_condition(condition, {"plan_status": "Approved"}).satisfied is True


def test_condition_field_not_equals() -> None:
    condition = Condition(
        type="field_not_equals", field="plan_status", value="rejected"
    )
    assert evaluate_condition(condition, {"plan_status": "approved"}).satisfied is True
    assert evaluate_condition(condition, {"plan_status": "rejected"}).satisfied is False


def test_condition_field_not_empty_and_empty() -> None:
    not_empty = Condition(type="field_not_empty", field="plan_status")
    assert evaluate_condition(not_empty, {"plan_status": "approved"}).satisfied is True
    assert evaluate_condition(not_empty, {}).satisfied is False

    empty = Condition(type="field_empty", field="plan_status")
    assert evaluate_condition(empty, {}).satisfied is True
    assert evaluate_condition(empty, {"plan_status": "x"}).satisfied is False


def test_condition_boolean_flags() -> None:
    is_true = Condition(type="boolean_true", field="review_requested")
    assert evaluate_condition(is_true, {"review_requested": "true"}).satisfied is True
    assert evaluate_condition(is_true, {"review_requested": "yes"}).satisfied is True
    assert evaluate_condition(is_true, {"review_requested": "false"}).satisfied is False
    assert evaluate_condition(is_true, {}).satisfied is False

    is_false = Condition(type="boolean_false", field="review_requested")
    assert evaluate_condition(is_false, {"review_requested": "false"}).satisfied is True
    assert evaluate_condition(is_false, {"review_requested": "true"}).satisfied is False


def test_condition_all_and_any() -> None:
    all_conditions = Condition(
        type="all_conditions",
        conditions=[
            Condition(type="field_equals", field="a", value="1"),
            Condition(type="field_equals", field="b", value="2"),
        ],
    )
    assert evaluate_condition(all_conditions, {"a": "1", "b": "2"}).satisfied is True
    assert evaluate_condition(all_conditions, {"a": "1", "b": "3"}).satisfied is False

    any_condition = Condition(
        type="any_condition",
        conditions=[
            Condition(type="field_equals", field="a", value="1"),
            Condition(type="field_equals", field="b", value="2"),
        ],
    )
    assert evaluate_condition(any_condition, {"a": "1", "b": "3"}).satisfied is True
    assert evaluate_condition(any_condition, {"a": "9", "b": "3"}).satisfied is False


def test_empty_condition_list_holds() -> None:
    assert conditions_hold([], {}) is True


def test_first_failure_reports_the_blocking_condition() -> None:
    conditions = [
        Condition(type="field_equals", field="a", value="1"),
        Condition(type="field_equals", field="b", value="2"),
    ]
    checks = [
        evaluate_condition(condition, {"a": "1", "b": "3"})
        for condition in conditions
    ]
    failure = first_failure(checks)
    assert failure is not None
    assert failure.condition.field == "b"
    assert failure.actual == "3"


def test_condition_describe() -> None:
    assert (
        Condition(type="field_equals", field="plan_status", value="approved").describe()
        == "plan_status == approved"
    )
    assert (
        Condition(type="field_not_empty", field="plan_status").describe()
        == "plan_status заполнено"
    )


# -------------------------------------------------------------- transitions
def test_allowed_transition(client: TestClient) -> None:
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    outcome = client.post(
        f"/api/tasks/{task_id}/transitions/apply", json={"to_state": "execution"}
    ).json()
    assert outcome["allowed"] is True
    assert outcome["from_state"] == "planning"
    assert outcome["to_state"] == "execution"
    assert client.get(f"/api/tasks/{task_id}/state").json()["data"]["stage"] == "execution"


def test_forbidden_transition_does_not_change_stage(client: TestClient) -> None:
    """planning → done has no rule, so the stage must not move."""
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    outcome = client.post(
        f"/api/tasks/{task_id}/transitions/apply", json={"to_state": "done"}
    ).json()
    assert outcome["allowed"] is False
    assert "Нет активного правила" in outcome["reason"]
    assert client.get(f"/api/tasks/{task_id}/state").json()["data"]["stage"] == "planning"


def test_condition_blocks_the_transition(client: TestClient) -> None:
    """plan_status = pending must refuse planning → execution."""
    rule = _rule_for(client, "planning", "execution")
    _set_condition(client, rule["id"], "plan_status", "approved")

    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})
    _set_fact(client, task_id, plan_status="pending")

    outcome = client.post(
        f"/api/tasks/{task_id}/transitions/apply", json={"to_state": "execution"}
    ).json()
    assert outcome["allowed"] is False
    assert outcome["required_condition"] == "plan_status == approved"
    assert outcome["actual"] == "pending"
    assert client.get(f"/api/tasks/{task_id}/state").json()["data"]["stage"] == "planning"


def test_condition_allows_the_transition_when_met(client: TestClient) -> None:
    rule = _rule_for(client, "planning", "execution")
    _set_condition(client, rule["id"], "plan_status", "approved")

    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})
    _set_fact(client, task_id, plan_status="approved")

    outcome = client.post(
        f"/api/tasks/{task_id}/transitions/apply", json={"to_state": "execution"}
    ).json()
    assert outcome["allowed"] is True
    assert client.get(f"/api/tasks/{task_id}/state").json()["data"]["stage"] == "execution"


def test_available_transitions_report_the_verdict(client: TestClient) -> None:
    rule = _rule_for(client, "planning", "execution")
    _set_condition(client, rule["id"], "plan_status", "approved")

    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    payload = client.get(f"/api/tasks/{task_id}/available-transitions").json()
    assert payload["stage"] == "planning"
    assert len(payload["transitions"]) == 1
    item = payload["transitions"][0]
    assert item["to_state"] == "execution"
    assert item["allowed"] is False
    assert item["condition"] == "plan_status == approved"
    assert "plan_status == approved" in item["reason"]


def test_legacy_transition_endpoint_obeys_the_rules(client: TestClient) -> None:
    """The original endpoint goes through the manager too."""
    rule = _rule_for(client, "planning", "execution")
    _set_condition(client, rule["id"], "plan_status", "approved")

    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    refused = client.post(
        f"/api/tasks/{task_id}/transition", json={"stage": "execution"}
    )
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "invalid_transition"

    _set_fact(client, task_id, plan_status="approved")
    allowed = client.post(
        f"/api/tasks/{task_id}/transition", json={"stage": "execution"}
    )
    assert allowed.status_code == 200
    assert allowed.json()["data"]["stage"] == "execution"


def test_transition_to_unknown_state_is_refused(client: TestClient) -> None:
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    outcome = client.post(
        f"/api/tasks/{task_id}/transitions/apply", json={"to_state": "nonsense"}
    ).json()
    assert outcome["allowed"] is False
    assert "не существует" in outcome["reason"]


def test_transition_to_current_state_is_idempotent(client: TestClient) -> None:
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    outcome = client.post(
        f"/api/tasks/{task_id}/transitions/apply", json={"to_state": "planning"}
    ).json()
    assert outcome["allowed"] is True
    assert "уже на этом этапе" in outcome["reason"]


# ------------------------------------------------------------------ history
def test_history_records_success(client: TestClient) -> None:
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})
    client.post(
        f"/api/tasks/{task_id}/transitions/apply",
        json={"to_state": "execution", "reason": "план утверждён"},
    )

    entries = client.get(f"/api/tasks/{task_id}/transition-history").json()["entries"]
    assert len(entries) == 1
    assert entries[0]["from_stage"] == "planning"
    assert entries[0]["to_stage"] == "execution"
    assert entries[0]["result"] == "success"
    assert entries[0]["trigger"] == "user"
    assert entries[0]["reason"] == "план утверждён"


def test_history_records_rejection(client: TestClient) -> None:
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})
    client.post(
        f"/api/tasks/{task_id}/transitions/apply", json={"to_state": "done"}
    )

    entries = client.get(f"/api/tasks/{task_id}/transition-history").json()["entries"]
    assert len(entries) == 1
    assert entries[0]["result"] == "rejected"
    assert entries[0]["to_stage"] == "done"
    assert "Нет активного правила" in entries[0]["reason"]


def test_history_is_isolated_per_task(client: TestClient) -> None:
    first = _create_chat(client)
    second = _create_chat(client)
    client.post(f"/api/tasks/{first['id']}/state", json={})
    client.post(
        f"/api/tasks/{first['id']}/transitions/apply", json={"to_state": "execution"}
    )

    assert len(
        client.get(f"/api/tasks/{first['id']}/transition-history").json()["entries"]
    ) == 1
    assert (
        client.get(f"/api/tasks/{second['id']}/transition-history").json()["entries"]
        == []
    )


def test_history_removed_with_task(client: TestClient) -> None:
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})
    client.post(
        f"/api/tasks/{task_id}/transitions/apply", json={"to_state": "execution"}
    )

    client.delete(f"/api/chats/{task_id}")

    assert (
        client.get(f"/api/tasks/{task_id}/transition-history").json()["entries"] == []
    )


# --------------------------------------------------------------- AI path
def test_ai_initiates_transition(client: TestClient, fake_api) -> None:
    """The model proposes a move and the manager applies it."""
    _configure(client)
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    _propose_transition(fake_api, "execution")
    client.post(f"/api/chats/{task_id}/messages", json={"content": "Начинаем работу"})
    fake_api.wait_for_analysis(expected=3)

    assert client.get(f"/api/tasks/{task_id}/state").json()["data"]["stage"] == "execution"
    entries = client.get(f"/api/tasks/{task_id}/transition-history").json()["entries"]
    assert entries[0]["trigger"] == "ai_detected"
    assert entries[0]["result"] == "success"


def test_ai_cannot_bypass_a_condition(client: TestClient, fake_api) -> None:
    """The AI proposes, but a failing condition keeps the stage unchanged."""
    _configure(client)
    rule = _rule_for(client, "planning", "execution")
    _set_condition(client, rule["id"], "plan_status", "approved")

    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})
    _set_fact(client, task_id, plan_status="pending")

    _propose_transition(fake_api, "execution")
    client.post(f"/api/chats/{task_id}/messages", json={"content": "Начинай реализацию"})
    fake_api.wait_for_analysis(expected=3)

    # The stage did not move...
    assert client.get(f"/api/tasks/{task_id}/state").json()["data"]["stage"] == "planning"
    # ...and the refusal is recorded.
    entries = client.get(f"/api/tasks/{task_id}/transition-history").json()["entries"]
    assert entries[0]["result"] == "rejected"
    assert entries[0]["trigger"] == "ai_detected"


def test_ai_transition_is_allowed_once_the_condition_holds(
    client: TestClient, fake_api
) -> None:
    _configure(client)
    rule = _rule_for(client, "planning", "execution")
    _set_condition(client, rule["id"], "plan_status", "approved")

    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})
    _set_fact(client, task_id, plan_status="approved")

    _propose_transition(fake_api, "execution")
    client.post(
        f"/api/chats/{task_id}/messages",
        json={"content": "План утверждён, начинаем реализацию."},
    )
    fake_api.wait_for_analysis(expected=3)

    assert client.get(f"/api/tasks/{task_id}/state").json()["data"]["stage"] == "execution"


def test_ai_cannot_jump_over_a_stage(client: TestClient, fake_api) -> None:
    """A proposal to jump planning → done is refused, not walked."""
    _configure(client)
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    _propose_transition(fake_api, "done")
    client.post(f"/api/chats/{task_id}/messages", json={"content": "Всё готово"})
    fake_api.wait_for_analysis(expected=3)

    assert client.get(f"/api/tasks/{task_id}/state").json()["data"]["stage"] == "planning"


def test_ai_proposal_outside_the_allowed_set_is_dropped(
    client: TestClient, fake_api
) -> None:
    """A state the model invented is not even attempted."""
    _configure(client)
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    _propose_transition(fake_api, "invented_state")
    client.post(f"/api/chats/{task_id}/messages", json={"content": "Привет"})
    fake_api.wait_for_analysis(expected=3)

    assert client.get(f"/api/tasks/{task_id}/state").json()["data"]["stage"] == "planning"
    assert (
        client.get(f"/api/tasks/{task_id}/transition-history").json()["entries"] == []
    )


def test_low_confidence_proposal_is_ignored(client: TestClient, fake_api) -> None:
    _configure(client)
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    _propose_transition(fake_api, "execution", confidence=0.1)
    client.post(f"/api/chats/{task_id}/messages", json={"content": "Привет"})
    fake_api.wait_for_analysis(expected=3)

    assert client.get(f"/api/tasks/{task_id}/state").json()["data"]["stage"] == "planning"


def test_transition_detection_uses_its_own_api_call(
    client: TestClient, fake_api
) -> None:
    _configure(client)
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    client.post(f"/api/chats/{task_id}/messages", json={"content": "Привет"})
    fake_api.wait_for_analysis(expected=3)

    calls = [
        request
        for request in fake_api.analysis_requests()
        if "Transition Detector" in request["json"]["messages"][0]["content"]
    ]
    assert calls, "transition detection must issue its own API call"
    user_content = calls[-1]["json"]["messages"][1]["content"]
    assert "Текущее состояние" in user_content
    assert "Разрешённые переходы" in user_content


def test_transition_detection_does_not_block_the_reply(
    client: TestClient, fake_api
) -> None:
    _configure(client)
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    fake_api.transition_response = fake_api.transition_response.__class__(
        200, {"choices": [{"message": {"role": "assistant", "content": "не могу"}}]}
    )

    response = client.post(
        f"/api/chats/{task_id}/messages", json={"content": "Привет"}
    )
    assert response.status_code == 200
    assert response.json()["assistant_message"]["content"] == "Привет!"


def test_step_extractor_does_not_move_the_stage(
    client: TestClient, fake_api
) -> None:
    """The background step pass never advances the stage on its own.

    The stage is decided by the pre-flight gate, which runs on the request
    itself. A second, unchecked path would let the task advance without the
    rules being consulted.
    """
    _configure(client)
    rule = _rule_for(client, "planning", "execution")
    _set_condition(client, rule["id"], "plan_status", "approved")

    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    # The step extractor proposes execution, but the condition does not hold.
    client.post(f"/api/chats/{task_id}/messages", json={"content": "Начинаем работу"})
    fake_api.wait_for_analysis()

    state = client.get(f"/api/tasks/{task_id}/state").json()
    assert state["data"]["stage"] == "planning"
    # The step itself is still stored.
    assert state["data"]["current_step"] == "implement authentication"


def test_step_extractor_stage_is_not_applied_even_when_allowed(
    client: TestClient, fake_api
) -> None:
    """Even a permitted move is not taken by the background step pass."""
    _configure(client)
    rule = _rule_for(client, "planning", "execution")
    _set_condition(client, rule["id"], "plan_status", "approved")

    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})
    _set_fact(client, task_id, plan_status="approved")

    # The gate is pinned to "no transition", so nothing may move the stage.
    client.post(f"/api/chats/{task_id}/messages", json={"content": "Начинаем работу"})
    fake_api.wait_for_analysis()

    assert client.get(f"/api/tasks/{task_id}/state").json()["data"]["stage"] == "planning"


# ------------------------------------------------- pre-flight gate (request)
# When a task is active, the transition a request would cause is decided
# *before* the request is executed. A forbidden transition means the request is
# not executed at all and the user is told why.

def test_blocked_request_is_not_executed(client: TestClient, fake_api) -> None:
    """A request that would break the lifecycle is never sent to the model."""
    _configure(client)
    rule = _rule_for(client, "planning", "execution")
    _set_condition(client, rule["id"], "plan_status", "approved")

    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})
    _set_fact(client, task_id, plan_status="pending")

    _propose_transition(fake_api, "execution")
    response = client.post(
        f"/api/chats/{task_id}/messages", json={"content": "Начинай реализацию"}
    )

    answer = response.json()["assistant_message"]["content"]
    assert "не могу выполнить этот запрос" in answer
    assert "planning → execution" in answer
    assert "plan_status == approved" in answer
    assert "запрос не выполнен" in answer

    # The model was never asked for a solution.
    assert fake_api.chat_requests() == []
    # The stage did not move.
    assert client.get(f"/api/tasks/{task_id}/state").json()["data"]["stage"] == "planning"


def test_blocked_request_is_recorded_in_history(
    client: TestClient, fake_api
) -> None:
    _configure(client)
    rule = _rule_for(client, "planning", "execution")
    _set_condition(client, rule["id"], "plan_status", "approved")

    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})
    _set_fact(client, task_id, plan_status="pending")

    _propose_transition(fake_api, "execution")
    client.post(f"/api/chats/{task_id}/messages", json={"content": "Начинай"})
    fake_api.wait_for_analysis()

    entries = client.get(f"/api/tasks/{task_id}/transition-history").json()["entries"]
    assert entries[0]["result"] == "rejected"
    assert entries[0]["trigger"] == "ai_detected"


def test_allowed_request_runs_and_advances_the_stage(
    client: TestClient, fake_api
) -> None:
    """When the move is allowed the request runs and the stage advances."""
    _configure(client)
    rule = _rule_for(client, "planning", "execution")
    _set_condition(client, rule["id"], "plan_status", "approved")

    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})
    _set_fact(client, task_id, plan_status="approved")

    _propose_transition(fake_api, "execution")
    response = client.post(
        f"/api/chats/{task_id}/messages",
        json={"content": "План утверждён, начинаем реализацию."},
    )

    # The request was executed...
    assert response.json()["assistant_message"]["content"] == "Привет!"
    assert fake_api.chat_requests()
    # ...and the stage advanced.
    assert client.get(f"/api/tasks/{task_id}/state").json()["data"]["stage"] == "execution"


def test_request_that_does_not_move_the_task_runs(
    client: TestClient, fake_api
) -> None:
    """A plain question does not move the task, so it is executed normally."""
    _configure(client)
    _pin_step_extractor(fake_api)
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    # The detector answers "no transition" by default.
    response = client.post(
        f"/api/chats/{task_id}/messages", json={"content": "Расскажи про Python"}
    )

    assert response.json()["assistant_message"]["content"] == "Привет!"
    assert client.get(f"/api/tasks/{task_id}/state").json()["data"]["stage"] == "planning"


def test_gate_is_skipped_without_a_task(client: TestClient, fake_api) -> None:
    """A chat without a task has no lifecycle to enforce."""
    _configure(client)
    _pin_step_extractor(fake_api)
    chat = _create_chat(client)

    _propose_transition(fake_api, "execution")
    response = client.post(
        f"/api/chats/{chat['id']}/messages", json={"content": "Начинай реализацию"}
    )

    # The request ran: there was no task to gate it against.
    assert response.json()["assistant_message"]["content"] == "Привет!"
    assert "не могу выполнить этот запрос" not in response.json()["assistant_message"]["content"]


def test_gate_is_skipped_without_active_rules(
    client: TestClient, fake_api
) -> None:
    """With no active rule there is no move to check, so the request runs."""
    _configure(client)
    _pin_step_extractor(fake_api)
    for rule in client.get("/api/transition-rules").json()["rules"]:
        client.post(f"/api/transition-rules/{rule['id']}/deactivate")

    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    _propose_transition(fake_api, "execution")
    response = client.post(
        f"/api/chats/{task_id}/messages", json={"content": "Начинай реализацию"}
    )

    assert response.json()["assistant_message"]["content"] == "Привет!"
    assert client.get(f"/api/tasks/{task_id}/state").json()["data"]["stage"] == "planning"


def test_blocked_request_in_streaming(client: TestClient, fake_api) -> None:
    """The streaming path refuses the request too."""
    _configure(client)
    rule = _rule_for(client, "planning", "execution")
    _set_condition(client, rule["id"], "plan_status", "approved")

    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})
    _set_fact(client, task_id, plan_status="pending")

    _propose_transition(fake_api, "execution")
    response = client.post(
        f"/api/chats/{task_id}/messages/stream", json={"content": "Начинай реализацию"}
    )

    assert response.status_code == 200
    assert "не могу выполнить этот запрос" in response.text
    assert client.get(f"/api/tasks/{task_id}/state").json()["data"]["stage"] == "planning"


def test_blocked_request_is_persisted(client: TestClient, fake_api) -> None:
    _configure(client)
    rule = _rule_for(client, "planning", "execution")
    _set_condition(client, rule["id"], "plan_status", "approved")

    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})
    _set_fact(client, task_id, plan_status="pending")

    _propose_transition(fake_api, "execution")
    client.post(f"/api/chats/{task_id}/messages", json={"content": "Начинай"})

    messages = client.get(f"/api/chats/{task_id}/messages").json()["messages"]
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert "не могу выполнить этот запрос" in messages[-1]["content"]


def test_gate_uses_its_own_api_call(client: TestClient, fake_api) -> None:
    """The pre-flight decision is a separate call, made before the reply."""
    _configure(client)
    _pin_step_extractor(fake_api)
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    client.post(f"/api/chats/{task_id}/messages", json={"content": "Привет"})
    fake_api.wait_for_analysis()

    calls = [
        request
        for request in fake_api.analysis_requests()
        if "Transition Detector" in request["json"]["messages"][0]["content"]
    ]
    assert calls, "the gate must issue its own API call"
    # The gate runs before the reply, so it is the first such call; the
    # post-reply detection is the second one and carries no pending request.
    gate_call = calls[0]
    user_content = gate_call["json"]["messages"][1]["content"]
    assert "Запрос пользователя (ещё не выполнен)" in user_content
    assert "Привет" in user_content


def test_gate_does_not_block_when_the_model_is_unavailable(
    client: TestClient, fake_api
) -> None:
    """A failing detector must not stop the chat from working."""
    _configure(client)
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    fake_api.transition_response = fake_api.transition_response.__class__(
        200, {"choices": [{"message": {"role": "assistant", "content": "не могу"}}]}
    )

    response = client.post(
        f"/api/chats/{task_id}/messages", json={"content": "Привет"}
    )
    assert response.status_code == 200
    assert response.json()["assistant_message"]["content"] == "Привет!"


def test_invariant_conflict_wins_over_the_gate(
    client: TestClient, fake_api
) -> None:
    """A conflicting request is answered with the conflict, not the lifecycle."""
    _configure(client)
    _pin_step_extractor(fake_api)
    invariant = client.post(
        "/api/invariants", json={"rule": "Do not use Redis", "priority": "high"}
    ).json()
    _report_conflict(fake_api, invariant["id"], "Do not use Redis")

    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    response = client.post(
        f"/api/chats/{task_id}/messages", json={"content": "Add Redis"}
    )
    answer = response.json()["assistant_message"]["content"]
    assert "конфликтует" in answer
    assert "не могу выполнить этот запрос" not in answer


def test_gate_reply_text() -> None:
    """The refusal names the transition, the condition and the current value."""
    from backend.services.chat_service import ChatService

    text = ChatService._transition_blocked_reply(
        {
            "from_state": "planning",
            "to_state": "execution",
            "reason": "Условие перехода не выполнено: plan_status == approved.",
            "required_condition": "plan_status == approved",
            "actual": "pending",
        }
    )
    assert "planning → execution" in text
    assert "Требуемое условие: plan_status == approved" in text
    assert "Текущее значение: pending" in text
    assert "запрос не выполнен" in text


def test_gate_reply_without_a_condition() -> None:
    """A missing rule has no condition, so the reason is shown instead."""
    from backend.services.chat_service import ChatService

    text = ChatService._transition_blocked_reply(
        {
            "from_state": "planning",
            "to_state": "done",
            "reason": "Нет активного правила для перехода «Planning → Done».",
            "required_condition": "",
            "actual": "",
        }
    )
    assert "planning → done" in text
    assert "Нет активного правила" in text


# ------------------------------------------------------------- task facts
# Conditions are checked against the task's facts. A condition on a fact the
# task does not carry can never hold, so the user must be able to see and set
# those facts.

def test_facts_endpoint_reports_the_values(client: TestClient) -> None:
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})
    _set_fact(client, task_id, plan_status="approved")

    payload = client.get(f"/api/tasks/{task_id}/facts").json()
    assert payload["facts"]["plan_status"] == "approved"
    # The machine position is part of the facts too.
    assert payload["facts"]["stage"] == "planning"
    assert payload["facts"]["status"] == "active"


def test_facts_endpoint_lists_missing_fields(client: TestClient) -> None:
    """A rule reading a fact the task lacks is reported as unsatisfiable."""
    rule = _rule_for(client, "planning", "execution")
    _set_condition(client, rule["id"], "plan_status", "approved")

    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    payload = client.get(f"/api/tasks/{task_id}/facts").json()
    assert "plan_status" in payload["missing"]


def test_missing_field_disappears_once_set(client: TestClient) -> None:
    rule = _rule_for(client, "planning", "execution")
    _set_condition(client, rule["id"], "plan_status", "approved")

    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    client.put(
        f"/api/tasks/{task_id}/facts", json={"facts": {"plan_status": "approved"}}
    )
    payload = client.get(f"/api/tasks/{task_id}/facts").json()
    assert payload["missing"] == []
    assert payload["facts"]["plan_status"] == "approved"


def test_setting_facts_unblocks_the_transition(client: TestClient) -> None:
    """The reported fix actually works: set the fact, the move is allowed."""
    rule = _rule_for(client, "planning", "execution")
    _set_condition(client, rule["id"], "plan_status", "approved")

    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    blocked = client.post(
        f"/api/tasks/{task_id}/transitions/apply", json={"to_state": "execution"}
    ).json()
    assert blocked["allowed"] is False
    assert blocked["required_field"] == "plan_status"
    assert blocked["field_is_set"] is False

    client.put(
        f"/api/tasks/{task_id}/facts", json={"facts": {"plan_status": "approved"}}
    )
    allowed = client.post(
        f"/api/tasks/{task_id}/transitions/apply", json={"to_state": "execution"}
    ).json()
    assert allowed["allowed"] is True


def test_empty_fact_value_clears_it(client: TestClient) -> None:
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})
    _set_fact(client, task_id, plan_status="approved")

    client.put(
        f"/api/tasks/{task_id}/facts", json={"facts": {"plan_status": ""}}
    )
    payload = client.get(f"/api/tasks/{task_id}/facts").json()
    assert "plan_status" not in payload["facts"]


def test_facts_cannot_forge_the_stage(client: TestClient) -> None:
    """The machine position is derived, not settable through the facts."""
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    client.put(
        f"/api/tasks/{task_id}/facts", json={"facts": {"stage": "done"}}
    )
    state = client.get(f"/api/tasks/{task_id}/state").json()
    assert state["data"]["stage"] == "planning"


def test_refusal_names_the_missing_fact(client: TestClient, fake_api) -> None:
    """The refusal says the fact is not set, not that its value is empty."""
    _configure(client)
    rule = _rule_for(client, "planning", "execution")
    _set_condition(client, rule["id"], "plan_status", "approved")

    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    _propose_transition(fake_api, "execution")
    response = client.post(
        f"/api/chats/{task_id}/messages", json={"content": "Начинай реализацию"}
    )
    answer = response.json()["assistant_message"]["content"]
    assert "plan_status" in answer
    assert "не задан" in answer
    assert "Изменить факты" in answer


def test_refusal_shows_the_value_when_the_fact_is_set(
    client: TestClient, fake_api
) -> None:
    """A fact that holds the wrong value is reported with that value."""
    _configure(client)
    rule = _rule_for(client, "planning", "execution")
    _set_condition(client, rule["id"], "plan_status", "approved")

    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})
    _set_fact(client, task_id, plan_status="pending")

    _propose_transition(fake_api, "execution")
    response = client.post(
        f"/api/chats/{task_id}/messages", json={"content": "Начинай реализацию"}
    )
    answer = response.json()["assistant_message"]["content"]
    assert "Текущее значение: pending" in answer
    assert "не задан" not in answer


def test_rule_check_reports_missing_fields(client: TestClient) -> None:
    rule = _rule_for(client, "planning", "execution")
    _set_condition(client, rule["id"], "plan_status", "approved")

    result = client.post(
        f"/api/transition-rules/{rule['id']}/check", json={}
    ).json()
    assert result["required_fields"] == ["plan_status"]
    assert result["missing_fields"] == ["plan_status"]


def test_rule_check_without_conditions_has_no_fields(client: TestClient) -> None:
    rule = _rule_for(client, "execution", "validation")
    result = client.post(
        f"/api/transition-rules/{rule['id']}/check", json={}
    ).json()
    assert result["required_fields"] == []
    assert result["missing_fields"] == []


def test_required_fields_cover_nested_conditions(database) -> None:
    manager = _manager(database)
    manager.ensure_initialized()
    rule = manager.list_rules()[0]
    manager.update_rule(
        rule.id,
        TransitionRuleUpdate(
            conditions=[
                Condition(
                    type="all_conditions",
                    conditions=[
                        Condition(type="field_equals", field="a", value="1"),
                        Condition(type="field_not_empty", field="b"),
                    ],
                )
            ]
        ),
    )
    assert manager.required_fields() == ["a", "b"]


def test_facts_response_marks_editable_fields(client: TestClient) -> None:
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})
    _set_fact(client, task_id, plan_status="approved")

    payload = client.get(f"/api/tasks/{task_id}/facts").json()
    assert "plan_status" in payload["editable"]


def test_facts_are_isolated_per_task(client: TestClient) -> None:
    first = _create_chat(client)
    second = _create_chat(client)
    client.post(f"/api/tasks/{first['id']}/state", json={})
    client.post(f"/api/tasks/{second['id']}/state", json={})

    client.put(
        f"/api/tasks/{first['id']}/facts", json={"facts": {"plan_status": "approved"}}
    )
    assert (
        client.get(f"/api/tasks/{first['id']}/facts").json()["facts"]["plan_status"]
        == "approved"
    )
    assert (
        "plan_status"
        not in client.get(f"/api/tasks/{second['id']}/facts").json()["facts"]
    )


def test_facts_survive_a_restart(client: TestClient, app_config) -> None:
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})
    client.put(
        f"/api/tasks/{task_id}/facts", json={"facts": {"plan_status": "approved"}}
    )

    from backend.main import create_app

    with TestClient(create_app()) as second_client:
        payload = second_client.get(f"/api/tasks/{task_id}/facts").json()
        assert payload["facts"]["plan_status"] == "approved"


def test_refusal_reply_text_for_a_missing_fact() -> None:
    from backend.services.chat_service import ChatService

    text = ChatService._transition_blocked_reply(
        {
            "from_state": "planning",
            "to_state": "execution",
            "reason": "Условие перехода не выполнено: plan_status == approved.",
            "required_condition": "plan_status == approved",
            "actual": "",
            "required_field": "plan_status",
            "field_is_set": False,
        }
    )
    assert "plan_status" in text
    assert "не задан" in text
    assert "Изменить факты" in text


# ------------------------------------------------- automatic fact extraction
# The values conditions need are read out of the user's own message, so the
# user does not have to type them by hand.

def _propose_facts(fake_api, facts: dict, confidence: float = 0.9) -> None:
    """Make the fake fact extractor return the given values."""
    fake_api.fact_response = fake_api.fact_response.__class__(
        200,
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(
                            {"facts": facts, "confidence": confidence},
                            ensure_ascii=False,
                        ),
                    }
                }
            ]
        },
    )


def test_facts_are_extracted_from_the_message(
    client: TestClient, fake_api
) -> None:
    """The user writes the fact; the app reads it and applies the transition."""
    _configure(client)
    rule = _rule_for(client, "planning", "execution")
    _set_condition(client, rule["id"], "plan_status", "approved")

    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    _propose_facts(fake_api, {"plan_status": "approved"})
    _propose_transition(fake_api, "execution")
    client.post(
        f"/api/chats/{task_id}/messages",
        json={"content": "План утверждён, начинаем реализацию."},
    )

    # The fact was read from the message...
    facts = client.get(f"/api/tasks/{task_id}/facts").json()
    assert facts["facts"]["plan_status"] == "approved"
    # ...and the transition went through in the same request.
    assert client.get(f"/api/tasks/{task_id}/state").json()["data"]["stage"] == "execution"


def test_extraction_marks_the_fact_as_read_from_the_message(
    client: TestClient, fake_api
) -> None:
    _configure(client)
    rule = _rule_for(client, "planning", "execution")
    _set_condition(client, rule["id"], "plan_status", "approved")

    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    _propose_facts(fake_api, {"plan_status": "approved"})
    client.post(f"/api/chats/{task_id}/messages", json={"content": "План утверждён"})

    facts = client.get(f"/api/tasks/{task_id}/facts").json()
    assert "plan_status" in facts["extracted"]


def test_manually_set_facts_are_not_marked_as_extracted(
    client: TestClient,
) -> None:
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})
    client.put(
        f"/api/tasks/{task_id}/facts", json={"facts": {"plan_status": "approved"}}
    )

    facts = client.get(f"/api/tasks/{task_id}/facts").json()
    assert facts["extracted"] == []


def test_extraction_only_accepts_fields_the_rules_read(
    client: TestClient, fake_api
) -> None:
    """A fact the rules do not reference is dropped, not stored."""
    _configure(client)
    rule = _rule_for(client, "planning", "execution")
    _set_condition(client, rule["id"], "plan_status", "approved")

    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    _propose_facts(fake_api, {"plan_status": "approved", "invented": "yes"})
    client.post(f"/api/chats/{task_id}/messages", json={"content": "План утверждён"})

    facts = client.get(f"/api/tasks/{task_id}/facts").json()
    assert facts["facts"]["plan_status"] == "approved"
    assert "invented" not in facts["facts"]


def test_extraction_cannot_forge_the_stage(
    client: TestClient, fake_api
) -> None:
    """The machine position is never taken from the model."""
    _configure(client)
    rule = _rule_for(client, "planning", "execution")
    _set_condition(client, rule["id"], "plan_status", "approved")

    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    _propose_facts(fake_api, {"stage": "done", "plan_status": "approved"})
    client.post(f"/api/chats/{task_id}/messages", json={"content": "План утверждён"})

    state = client.get(f"/api/tasks/{task_id}/state").json()
    assert state["data"]["stage"] in ("planning", "execution")
    assert state["data"]["stage"] != "done"


def test_low_confidence_extraction_is_ignored(
    client: TestClient, fake_api
) -> None:
    _configure(client)
    rule = _rule_for(client, "planning", "execution")
    _set_condition(client, rule["id"], "plan_status", "approved")

    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    _propose_facts(fake_api, {"plan_status": "approved"}, confidence=0.1)
    client.post(f"/api/chats/{task_id}/messages", json={"content": "План утверждён"})

    facts = client.get(f"/api/tasks/{task_id}/facts").json()
    assert "plan_status" not in facts["facts"]


def test_extraction_does_not_overwrite_with_nothing(
    client: TestClient, fake_api
) -> None:
    """A message with no facts leaves the stored values alone."""
    _configure(client)
    rule = _rule_for(client, "planning", "execution")
    _set_condition(client, rule["id"], "plan_status", "approved")

    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})
    client.put(
        f"/api/tasks/{task_id}/facts", json={"facts": {"plan_status": "approved"}}
    )

    # The default fake extractor returns no facts.
    client.post(f"/api/chats/{task_id}/messages", json={"content": "Что такое FastAPI?"})

    facts = client.get(f"/api/tasks/{task_id}/facts").json()
    assert facts["facts"]["plan_status"] == "approved"


def test_extraction_uses_its_own_api_call(client: TestClient, fake_api) -> None:
    _configure(client)
    rule = _rule_for(client, "planning", "execution")
    _set_condition(client, rule["id"], "plan_status", "approved")

    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    client.post(f"/api/chats/{task_id}/messages", json={"content": "Привет"})
    fake_api.wait_for_analysis()

    calls = [
        request
        for request in fake_api.analysis_requests()
        if "Fact Extractor" in request["json"]["messages"][0]["content"]
    ]
    assert calls, "fact extraction must issue its own API call"
    user_content = calls[-1]["json"]["messages"][1]["content"]
    assert "plan_status" in user_content
    assert "Привет" in user_content


def test_extraction_is_skipped_without_conditions(
    client: TestClient, fake_api
) -> None:
    """With no conditions there is no fact to read, so no call is made."""
    _configure(client)
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    client.post(f"/api/chats/{task_id}/messages", json={"content": "Привет"})
    fake_api.wait_for_analysis()

    calls = [
        request
        for request in fake_api.analysis_requests()
        if "Fact Extractor" in request["json"]["messages"][0]["content"]
    ]
    assert calls == []


def test_extraction_failure_does_not_break_the_chat(
    client: TestClient, fake_api
) -> None:
    _configure(client)
    rule = _rule_for(client, "planning", "execution")
    _set_condition(client, rule["id"], "plan_status", "approved")

    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    fake_api.fact_response = fake_api.fact_response.__class__(
        200, {"choices": [{"message": {"role": "assistant", "content": "не могу"}}]}
    )

    response = client.post(
        f"/api/chats/{task_id}/messages", json={"content": "Привет"}
    )
    assert response.status_code == 200


def test_extracted_facts_are_isolated_per_task(
    client: TestClient, fake_api
) -> None:
    _configure(client)
    rule = _rule_for(client, "planning", "execution")
    _set_condition(client, rule["id"], "plan_status", "approved")

    first = _create_chat(client)
    second = _create_chat(client)
    client.post(f"/api/tasks/{first['id']}/state", json={})
    client.post(f"/api/tasks/{second['id']}/state", json={})

    _propose_facts(fake_api, {"plan_status": "approved"})
    client.post(f"/api/chats/{first['id']}/messages", json={"content": "План утверждён"})

    assert (
        client.get(f"/api/tasks/{first['id']}/facts").json()["facts"]["plan_status"]
        == "approved"
    )
    assert (
        "plan_status"
        not in client.get(f"/api/tasks/{second['id']}/facts").json()["facts"]
    )


def test_extracted_facts_survive_a_restart(
    client: TestClient, fake_api, app_config
) -> None:
    _configure(client)
    rule = _rule_for(client, "planning", "execution")
    _set_condition(client, rule["id"], "plan_status", "approved")

    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    _propose_facts(fake_api, {"plan_status": "approved"})
    client.post(f"/api/chats/{task_id}/messages", json={"content": "План утверждён"})

    from backend.main import create_app

    with TestClient(create_app()) as second_client:
        facts = second_client.get(f"/api/tasks/{task_id}/facts").json()
        assert facts["facts"]["plan_status"] == "approved"
        assert "plan_status" in facts["extracted"]


def test_provenance_key_does_not_leak_into_facts(
    client: TestClient, fake_api
) -> None:
    _configure(client)
    rule = _rule_for(client, "planning", "execution")
    _set_condition(client, rule["id"], "plan_status", "approved")

    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    _propose_facts(fake_api, {"plan_status": "approved"})
    client.post(f"/api/chats/{task_id}/messages", json={"content": "План утверждён"})

    facts = client.get(f"/api/tasks/{task_id}/facts").json()
    assert "_extracted_facts" not in facts["facts"]
    assert "_extracted_facts" not in facts["editable"]


# ------------------------------------------------- condition comparison
def test_condition_ignores_yo_and_case() -> None:
    """A rule written with "е" matches a value written with "ё"."""
    condition = Condition(
        type="field_equals", field="plan_status", value="утвержден"
    )
    assert evaluate_condition(condition, {"plan_status": "утверждён"}).satisfied is True
    assert evaluate_condition(condition, {"plan_status": "УТВЕРЖДЁН"}).satisfied is True
    assert evaluate_condition(condition, {"plan_status": "отклонён"}).satisfied is False


def test_condition_ignores_extra_whitespace() -> None:
    condition = Condition(type="field_equals", field="a", value="in  progress")
    assert evaluate_condition(condition, {"a": "  in progress "}).satisfied is True


def test_condition_not_equals_ignores_yo() -> None:
    condition = Condition(
        type="field_not_equals", field="plan_status", value="утвержден"
    )
    assert evaluate_condition(condition, {"plan_status": "утверждён"}).satisfied is False


# ------------------------------------------------------------- prompt block
def test_rules_reach_the_prompt(client: TestClient, fake_api) -> None:
    _configure(client)
    rule = _rule_for(client, "planning", "execution")
    _set_condition(client, rule["id"], "plan_status", "approved")

    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})
    client.post(f"/api/chats/{task_id}/messages", json={"content": "Что дальше?"})

    system = fake_api.chat_requests()[-1]["json"]["messages"][0]["content"]
    assert "## TASK STATE RULES" in system
    assert "plan_status == approved" in system
    assert "TRANSITION RULES" in system
    assert "condition not met" in system


def test_prompt_block_endpoint(client: TestClient) -> None:
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    block = client.get(f"/api/tasks/{task_id}/transition-prompt-block").json()["block"]
    assert "## TASK STATE RULES" in block
    assert "Planning → Execution" in block


def test_no_task_means_no_rules_block(client: TestClient, fake_api) -> None:
    _configure(client)
    chat = _create_chat(client)
    client.post(f"/api/chats/{chat['id']}/messages", json={"content": "Привет"})

    system = fake_api.chat_requests()[-1]["json"]["messages"][0]["content"]
    assert "## TASK STATE RULES" not in system


# ------------------------------------------------------------- persistence
def test_rules_persist_after_restart(client: TestClient, app_config) -> None:
    """A rule edited in the UI survives a restart."""
    rule = _rule_for(client, "planning", "execution")
    _set_condition(client, rule["id"], "plan_status", "approved")
    created = client.post("/api/task-states", json={"name": "Review"}).json()

    from backend.main import create_app

    with TestClient(create_app()) as second_client:
        rules = second_client.get("/api/transition-rules").json()["rules"]
        target = next(item for item in rules if item["id"] == rule["id"])
        assert target["conditions"][0]["field"] == "plan_status"
        assert target["conditions"][0]["value"] == "approved"

        states = second_client.get("/api/task-states").json()["states"]
        assert any(item["id"] == created["id"] for item in states)


def test_history_persists_after_restart(client: TestClient, app_config) -> None:
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})
    client.post(
        f"/api/tasks/{task_id}/transitions/apply", json={"to_state": "execution"}
    )

    from backend.main import create_app

    with TestClient(create_app()) as second_client:
        entries = second_client.get(
            f"/api/tasks/{task_id}/transition-history"
        ).json()["entries"]
        assert len(entries) == 1
        assert entries[0]["result"] == "success"


def test_manager_survives_repository_reopen(database) -> None:
    manager = _manager(database)
    manager.ensure_initialized()
    rule = manager.list_rules()[0]
    manager.update_rule(
        rule.id,
        TransitionRuleUpdate(
            conditions=[Condition(type="field_equals", field="a", value="1")]
        ),
    )

    reopened = _manager(database)
    reloaded = reopened.get_rule(rule.id)
    assert reloaded.conditions[0].field == "a"


# --------------------------------------------------------- dynamic updates
def test_rule_change_applies_without_restart(client: TestClient) -> None:
    """Removing a condition makes the move allowed immediately."""
    rule = _rule_for(client, "planning", "execution")
    _set_condition(client, rule["id"], "plan_status", "approved")

    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    blocked = client.post(
        f"/api/tasks/{task_id}/transitions/apply", json={"to_state": "execution"}
    ).json()
    assert blocked["allowed"] is False

    # The user removes the condition on the rules page.
    client.put(
        f"/api/transition-rules/{rule['id']}",
        json={"condition": "", "conditions": []},
    )

    allowed = client.post(
        f"/api/tasks/{task_id}/transitions/apply", json={"to_state": "execution"}
    ).json()
    assert allowed["allowed"] is True
    assert client.get(f"/api/tasks/{task_id}/state").json()["data"]["stage"] == "execution"


def test_new_rule_applies_without_restart(client: TestClient) -> None:
    """A rule created in the UI allows a move that was impossible before."""
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    before = client.post(
        f"/api/tasks/{task_id}/transitions/apply", json={"to_state": "validation"}
    ).json()
    assert before["allowed"] is False

    client.post(
        "/api/transition-rules",
        json={"from_state": "planning", "to_state": "validation"},
    )

    after = client.post(
        f"/api/tasks/{task_id}/transitions/apply", json={"to_state": "validation"}
    ).json()
    assert after["allowed"] is True


# ------------------------------------------------------------ pause/resume
def test_pause_keeps_stage_and_rules_still_apply(client: TestClient) -> None:
    rule = _rule_for(client, "planning", "execution")
    _set_condition(client, rule["id"], "plan_status", "approved")

    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})
    client.post(f"/api/tasks/{task_id}/pause", json={"reason": "перерыв"})

    state = client.get(f"/api/tasks/{task_id}/state").json()["data"]
    assert state["status"] == "paused"
    assert state["stage"] == "planning"

    # A pause does not let the task bypass the rules.
    outcome = client.post(
        f"/api/tasks/{task_id}/transitions/apply", json={"to_state": "execution"}
    ).json()
    assert outcome["allowed"] is False


def test_resume_uses_the_current_rules(client: TestClient) -> None:
    rule = _rule_for(client, "planning", "execution")
    _set_condition(client, rule["id"], "plan_status", "approved")

    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})
    client.post(f"/api/tasks/{task_id}/pause", json={})
    client.post(f"/api/tasks/{task_id}/resume")

    state = client.get(f"/api/tasks/{task_id}/state").json()["data"]
    assert state["status"] == "active"
    assert state["stage"] == "planning"

    _set_fact(client, task_id, plan_status="approved")
    outcome = client.post(
        f"/api/tasks/{task_id}/transitions/apply", json={"to_state": "execution"}
    ).json()
    assert outcome["allowed"] is True


# ------------------------------------------------------------ unit level
def test_manager_rejects_duplicate_rule(database) -> None:
    manager = _manager(database)
    manager.ensure_initialized()
    with pytest.raises(DuplicateRuleError):
        manager.create_rule(
            TransitionRuleCreate(from_state="planning", to_state="execution")
        )


def test_manager_rejects_unknown_state(database) -> None:
    manager = _manager(database)
    manager.ensure_initialized()
    with pytest.raises(InvalidRuleError):
        manager.create_rule(
            TransitionRuleCreate(from_state="planning", to_state="nope")
        )


def test_manager_protects_states_in_use(database) -> None:
    manager = _manager(database)
    manager.ensure_initialized()
    with pytest.raises(StateInUseError):
        manager.delete_state("execution")


def test_manager_initial_state(database) -> None:
    manager = _manager(database)
    manager.ensure_initialized()
    assert manager.initial_state_id() == "planning"
    assert manager.final_state_ids() == ["done"]


def test_manager_creates_task_in_the_initial_state(database) -> None:
    chat_id = ChatRepository(database).create(model="m").id
    manager = _manager(database)
    manager.ensure_initialized()

    state = manager.ensure_task(chat_id)
    assert state.data.stage == "planning"


def test_manager_available_transitions(database) -> None:
    chat_id = ChatRepository(database).create(model="m").id
    manager = _manager(database)
    manager.ensure_initialized()
    manager.ensure_task(chat_id)

    available = manager.get_available_transitions(chat_id)
    assert [item.to_state for item in available.transitions] == ["execution"]
    assert available.transitions[0].allowed is True


def test_manager_can_transition(database) -> None:
    chat_id = ChatRepository(database).create(model="m").id
    manager = _manager(database)
    manager.ensure_initialized()
    manager.ensure_task(chat_id)

    assert manager.can_transition(chat_id, "execution") is True
    assert manager.can_transition(chat_id, "done") is False


def test_manager_apply_suggestion(database) -> None:
    chat_id = ChatRepository(database).create(model="m").id
    manager = _manager(database)
    manager.ensure_initialized()
    manager.ensure_task(chat_id)

    outcome = manager.apply_suggestion(
        chat_id, TransitionSuggestion(to_state="execution", confidence=0.9)
    )
    assert outcome is not None
    assert outcome.allowed is True
    assert outcome.trigger == "ai_detected"
    assert manager.task_state(chat_id).data.stage == "execution"


def test_manager_apply_empty_suggestion(database) -> None:
    chat_id = ChatRepository(database).create(model="m").id
    manager = _manager(database)
    manager.ensure_initialized()
    manager.ensure_task(chat_id)

    assert manager.apply_suggestion(chat_id, TransitionSuggestion()) is None


def test_manager_facts_include_metadata_and_stage(database) -> None:
    chat_id = ChatRepository(database).create(model="m").id
    manager = _manager(database)
    manager.ensure_initialized()
    manager.ensure_task(chat_id)
    manager._tasks.update_step(chat_id, metadata={"plan_status": "approved"})

    facts = manager.facts_for(chat_id)
    assert facts["plan_status"] == "approved"
    assert facts["stage"] == "planning"
    assert facts["status"] == "active"


def test_manager_describe(database) -> None:
    manager = _manager(database)
    manager.ensure_initialized()
    assert "состояний=4" in manager.describe()
    assert "правил=3" in manager.describe()


def test_manager_edges(database) -> None:
    manager = _manager(database)
    manager.ensure_initialized()
    assert manager.edges() == [
        ("planning", "execution"),
        ("execution", "validation"),
        ("validation", "done"),
    ]


def test_manager_state_labels(database) -> None:
    manager = _manager(database)
    manager.ensure_initialized()
    labels = manager.state_labels()
    assert labels["planning"] == "Planning"
    assert labels["done"] == "Done"


def test_create_state_payload_strips_whitespace() -> None:
    payload = TaskStateDefinitionCreate(name="  Review  ", description="  why  ")
    assert payload.name == "Review"
    assert payload.description == "why"


def test_update_state_payload_strips_whitespace() -> None:
    payload = TaskStateDefinitionUpdate(name="  Review  ")
    assert payload.name == "Review"


def test_condition_rejects_unknown_type() -> None:
    with pytest.raises(Exception):
        Condition(type="run_shell", field="x", value="y")


# ------------------------------------------------------------- isolation
def test_lifecycle_is_separate_from_memory_and_invariants(
    client: TestClient, fake_api
) -> None:
    """The lifecycle layer does not touch memory, profiles or invariants."""
    _configure(client)
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})
    client.post(
        f"/api/tasks/{task_id}/transitions/apply", json={"to_state": "execution"}
    )

    assert client.get("/api/memory/long-term").json()["entries"] == []
    assert client.get("/api/invariants").json()["invariants"] == []
    assert client.get(f"/api/chats/{task_id}/memory/working").json()["exists"] is False


def test_invariants_do_not_create_rules(client: TestClient) -> None:
    before = len(client.get("/api/transition-rules").json()["rules"])
    client.post("/api/invariants", json={"rule": "Do not use Redis"})
    after = len(client.get("/api/transition-rules").json()["rules"])
    assert before == after


def test_rules_do_not_create_invariants(client: TestClient) -> None:
    client.post(
        "/api/transition-rules",
        json={"from_state": "planning", "to_state": "validation"},
    )
    assert client.get("/api/invariants").json()["invariants"] == []


def test_task_state_and_lifecycle_are_different_tables(client: TestClient) -> None:
    """The per-task position and the lifecycle configuration never mix."""
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    # The lifecycle is global configuration...
    states = client.get("/api/task-states").json()["states"]
    assert len(states) == 4
    # ...while the task state is one row per task.
    assert client.get(f"/api/tasks/{task_id}/state").json()["data"]["stage"] == "planning"
    assert client.get("/api/tasks/other-task/state").json()["exists"] is False
