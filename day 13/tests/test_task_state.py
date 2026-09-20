"""Tests for the task state machine.

The task state is a formalised finite-state machine, so these tests focus on
three things: the allowed edges, the pause/resume cycle (including across a
restart), and the fact that the state reaches the model on every request.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.database.repositories import ChatRepository
from backend.database.task_repository import TaskStateRepository
from backend.memory.manager import MemoryManager
from backend.profile.manager import ProfileManager
from backend.services.prompt_builder import PromptBuilder
from backend.tasks.manager import InvalidTransitionError, TaskStateManager
from backend.tasks.models import (
    TaskPauseRequest,
    TaskStateCreate,
    TaskStateData,
    TaskStateUpdate,
    TaskTransitionRequest,
)


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


# ------------------------------------------------------------ initial state
def test_initial_task_state(client: TestClient) -> None:
    """A new task starts in ``planning`` and is active."""
    chat = _create_chat(client)
    response = client.post(f"/api/tasks/{chat['id']}/state", json={})
    assert response.status_code == 201

    state = response.json()
    assert state["data"]["stage"] == "planning"
    assert state["data"]["status"] == "active"
    assert state["data"]["current_step"] == ""
    assert state["exists"] is True


def test_missing_task_state_is_reported_as_absent(client: TestClient) -> None:
    chat = _create_chat(client)
    payload = client.get(f"/api/tasks/{chat['id']}/state").json()
    assert payload["exists"] is False
    assert payload["data"]["stage"] == "planning"


def test_task_state_progress_markers(client: TestClient) -> None:
    """The UI needs to know which stages are done, current and pending."""
    chat = _create_chat(client)
    client.post(f"/api/tasks/{chat['id']}/state", json={})
    client.post(f"/api/tasks/{chat['id']}/transition", json={"stage": "execution"})

    state = client.get(f"/api/tasks/{chat['id']}/state").json()
    markers = {item["stage"]: item["marker"] for item in state["progress"]}
    assert markers == {
        "planning": "done",
        "execution": "current",
        "validation": "pending",
        "done": "pending",
    }


# ------------------------------------------------------------ transitions
def test_valid_transition(client: TestClient) -> None:
    """planning → execution → validation → done, one edge at a time."""
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    for stage in ("execution", "validation", "done"):
        response = client.post(
            f"/api/tasks/{task_id}/transition", json={"stage": stage}
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["stage"] == stage

    final = client.get(f"/api/tasks/{task_id}/state").json()
    assert final["data"]["status"] == "completed"


def test_invalid_transition(client: TestClient) -> None:
    """planning → done must be refused: the edge does not exist."""
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    response = client.post(f"/api/tasks/{task_id}/transition", json={"stage": "done"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_transition"

    # The state is unchanged.
    assert client.get(f"/api/tasks/{task_id}/state").json()["data"]["stage"] == "planning"


def test_backward_transition_is_refused(client: TestClient) -> None:
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})
    client.post(f"/api/tasks/{task_id}/transition", json={"stage": "execution"})

    response = client.post(
        f"/api/tasks/{task_id}/transition", json={"stage": "planning"}
    )
    assert response.status_code == 409


def test_transition_records_completed_step(client: TestClient) -> None:
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(
        f"/api/tasks/{task_id}/state",
        json={"current_step": "implement registration"},
    )
    client.post(
        f"/api/tasks/{task_id}/transition",
        json={"stage": "execution", "current_step": "implement authentication"},
    )

    state = client.get(f"/api/tasks/{task_id}/state").json()
    assert state["data"]["completed_steps"] == ["implement registration"]
    assert state["data"]["current_step"] == "implement authentication"


def test_transition_updates_step_and_expected_action(client: TestClient) -> None:
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    response = client.post(
        f"/api/tasks/{task_id}/transition",
        json={
            "stage": "execution",
            "current_step": "implement registration",
            "expected_action": "create registration endpoint",
        },
    )
    data = response.json()["data"]
    assert data["current_step"] == "implement registration"
    assert data["expected_action"] == "create registration endpoint"


def test_update_step_without_changing_stage(client: TestClient) -> None:
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})
    client.post(f"/api/tasks/{task_id}/transition", json={"stage": "execution"})

    response = client.put(
        f"/api/tasks/{task_id}/state",
        json={
            "current_step": "implement authentication",
            "expected_action": "create login endpoint",
        },
    )
    data = response.json()["data"]
    assert data["stage"] == "execution"  # unchanged
    assert data["current_step"] == "implement authentication"


# ------------------------------------------------------------ pause / resume
def test_pause_preserves_state(client: TestClient) -> None:
    """Pausing keeps the stage, the step and the expected action."""
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})
    client.post(
        f"/api/tasks/{task_id}/transition",
        json={
            "stage": "execution",
            "current_step": "implement authentication",
            "expected_action": "create login endpoint",
        },
    )

    response = client.post(f"/api/tasks/{task_id}/pause", json={"reason": "перерыв"})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "paused"
    assert data["stage"] == "execution"
    assert data["current_step"] == "implement authentication"
    assert data["expected_action"] == "create login endpoint"
    assert data["pause_reason"] == "перерыв"


def test_resume_restores_state(client: TestClient) -> None:
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})
    client.post(
        f"/api/tasks/{task_id}/transition",
        json={"stage": "execution", "current_step": "implement authentication"},
    )
    client.post(f"/api/tasks/{task_id}/pause", json={})

    response = client.post(f"/api/tasks/{task_id}/resume")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "active"
    assert data["stage"] == "execution"
    assert data["current_step"] == "implement authentication"


def test_pause_is_allowed_on_every_stage(client: TestClient) -> None:
    """planning, execution and validation can all be paused."""
    # Walk the stages in order, pausing at each one in turn.
    for index, stage in enumerate(("planning", "execution", "validation")):
        chat = _create_chat(client)
        task_id = chat["id"]
        client.post(f"/api/tasks/{task_id}/state", json={})

        # Advance to the stage under test by following the allowed edges.
        for step in ("execution", "validation")[:index]:
            client.post(f"/api/tasks/{task_id}/transition", json={"stage": step})

        assert client.get(f"/api/tasks/{task_id}/state").json()["data"]["stage"] == stage

        response = client.post(f"/api/tasks/{task_id}/pause", json={})
        assert response.status_code == 200, stage
        assert response.json()["data"]["status"] == "paused"
        assert response.json()["data"]["stage"] == stage


def test_pause_does_not_touch_memory(client: TestClient, fake_api) -> None:
    """Pausing must not delete working memory, long-term memory or the dialogue."""
    _configure(client)
    chat = _create_chat(client)
    task_id = chat["id"]

    client.post(f"/api/chats/{task_id}/messages", json={"content": "Я предпочитаю Python"})
    client.post(f"/api/tasks/{task_id}/state", json={})
    client.post(f"/api/tasks/{task_id}/transition", json={"stage": "execution"})

    long_term_before = client.get("/api/memory/long-term").json()["entries"]
    short_term_before = client.get(
        f"/api/chats/{task_id}/memory/short-term"
    ).json()["total_messages"]

    client.post(f"/api/tasks/{task_id}/pause", json={})

    assert client.get("/api/memory/long-term").json()["entries"] == long_term_before
    assert (
        client.get(f"/api/chats/{task_id}/memory/short-term").json()["total_messages"]
        == short_term_before
    )


def test_paused_task_cannot_be_completed_directly(client: TestClient) -> None:
    """Completion walks the stages in order, so the machine is never bypassed."""
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})
    client.post(f"/api/tasks/{task_id}/pause", json={})

    response = client.post(f"/api/tasks/{task_id}/complete")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["stage"] == "done"
    assert data["status"] == "completed"


# ------------------------------------------------------------ completion
def test_task_completion(client: TestClient) -> None:
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})
    client.post(f"/api/tasks/{task_id}/transition", json={"stage": "execution"})

    response = client.post(f"/api/tasks/{task_id}/complete")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["stage"] == "done"
    assert data["status"] == "completed"


def test_completed_task_cannot_be_paused(client: TestClient) -> None:
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})
    client.post(f"/api/tasks/{task_id}/complete")

    response = client.post(f"/api/tasks/{task_id}/pause", json={})
    assert response.status_code == 409


# ------------------------------------------------------------ persistence
def test_state_persists_after_restart(client: TestClient, app_config) -> None:
    """The full pause → restart → resume cycle keeps every field."""
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})
    client.post(
        f"/api/tasks/{task_id}/transition",
        json={
            "stage": "execution",
            "current_step": "implement authentication",
            "expected_action": "create login endpoint",
        },
    )
    client.post(f"/api/tasks/{task_id}/pause", json={"reason": "перерыв"})

    from backend.main import create_app

    with TestClient(create_app()) as second_client:
        restored = second_client.get(f"/api/tasks/{task_id}/state").json()
        assert restored["data"]["status"] == "paused"
        assert restored["data"]["stage"] == "execution"
        assert restored["data"]["current_step"] == "implement authentication"
        assert restored["data"]["expected_action"] == "create login endpoint"
        assert restored["data"]["pause_reason"] == "перерыв"

        # Resume continues from the same step.
        resumed = second_client.post(f"/api/tasks/{task_id}/resume").json()
        assert resumed["data"]["status"] == "active"
        assert resumed["data"]["stage"] == "execution"
        assert resumed["data"]["current_step"] == "implement authentication"


def test_state_survives_repository_reopen(database) -> None:
    chat_id = ChatRepository(database).create(model="m").id
    manager = TaskStateManager(TaskStateRepository(database))
    manager.create_state(chat_id)
    manager.transition(chat_id, "execution", current_step="step one")
    manager.pause(chat_id, TaskPauseRequest(reason="later"))

    # A fresh manager over the same database sees the same state.
    reopened = TaskStateManager(TaskStateRepository(database))
    data = reopened.get_data(chat_id)
    assert data.status == "paused"
    assert data.stage == "execution"
    assert data.current_step == "step one"
    assert data.pause_reason == "later"


# ------------------------------------------------------------ prompt
def test_state_is_added_to_prompt(client: TestClient, fake_api) -> None:
    _configure(client)
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})
    client.post(
        f"/api/tasks/{task_id}/transition",
        json={
            "stage": "execution",
            "current_step": "implement refresh token",
            "expected_action": "write refresh token endpoint",
        },
    )

    client.post(f"/api/chats/{task_id}/messages", json={"content": "Что дальше?"})

    system = _system_prompt(client, fake_api)
    assert "## TASK STATE" in system
    assert "Stage: Execution" in system
    assert "Current step: implement refresh token" in system
    assert "Expected action: write refresh token endpoint" in system
    assert "Status: Active" in system


def test_paused_state_is_visible_in_prompt(client: TestClient, fake_api) -> None:
    _configure(client)
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})
    client.post(
        f"/api/tasks/{task_id}/transition",
        json={"stage": "execution", "current_step": "implement authentication"},
    )
    client.post(f"/api/tasks/{task_id}/pause", json={"reason": "перерыв"})

    client.post(f"/api/chats/{task_id}/messages", json={"content": "Что дальше?"})

    system = _system_prompt(client, fake_api)
    assert "Status: Paused" in system
    assert "Pause reason: перерыв" in system
    assert "Current step: implement authentication" in system


def test_prompt_block_endpoint(client: TestClient) -> None:
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})
    client.post(f"/api/tasks/{task_id}/transition", json={"stage": "execution"})

    payload = client.get(f"/api/tasks/{task_id}/prompt-block").json()
    assert "## TASK STATE" in payload["block"]
    assert "Stage: Execution" in payload["block"]


def test_no_task_state_means_no_block(client: TestClient, fake_api) -> None:
    """A chat without a task must not get an empty TASK STATE section."""
    _configure(client)
    chat = _create_chat(client)
    client.post(f"/api/chats/{chat['id']}/messages", json={"content": "Привет"})

    assert "## TASK STATE" not in _system_prompt(client, fake_api)


def test_prompt_order_profile_memory_task_dialogue(
    client: TestClient, fake_api
) -> None:
    """profile → long-term → working → task state → dialogue."""
    _configure(client)
    chat = _create_chat(client)
    task_id = chat["id"]

    client.post(f"/api/chats/{task_id}/messages", json={"content": "Я предпочитаю Python"})
    client.post(
        f"/api/chats/{task_id}/messages",
        json={"content": "Сейчас мы разрабатываем API интернет-магазина"},
    )
    client.post(f"/api/tasks/{task_id}/state", json={})
    client.post(f"/api/tasks/{task_id}/transition", json={"stage": "execution"})
    client.post(f"/api/chats/{task_id}/messages", json={"content": "Что дальше?"})

    system = _system_prompt(client, fake_api)
    profile_at = system.index("## ACTIVE USER PROFILE")
    long_term_at = system.index("## Long-term memory")
    working_at = system.index("## Working memory")
    task_at = system.index("## TASK STATE")
    assert profile_at < long_term_at < working_at < task_at


# ------------------------------------------------- automatic updates
def test_plan_approval_moves_to_execution(client: TestClient, fake_api) -> None:
    _configure(client)
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    client.post(f"/api/chats/{task_id}/messages", json={"content": "Подтверждаю план"})

    state = client.get(f"/api/tasks/{task_id}/state").json()
    assert state["data"]["stage"] == "execution"


def test_pause_command_pauses_task(client: TestClient, fake_api) -> None:
    _configure(client)
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})
    client.post(f"/api/tasks/{task_id}/transition", json={"stage": "execution"})

    client.post(f"/api/chats/{task_id}/messages", json={"content": "Поставь задачу на паузу"})

    assert client.get(f"/api/tasks/{task_id}/state").json()["data"]["status"] == "paused"


def test_resume_command_resumes_task(client: TestClient, fake_api) -> None:
    _configure(client)
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})
    client.post(
        f"/api/tasks/{task_id}/transition",
        json={"stage": "execution", "current_step": "implement authentication"},
    )
    client.post(f"/api/tasks/{task_id}/pause", json={})

    client.post(f"/api/chats/{task_id}/messages", json={"content": "Продолжить"})

    state = client.get(f"/api/tasks/{task_id}/state").json()
    assert state["data"]["status"] == "active"
    assert state["data"]["stage"] == "execution"
    assert state["data"]["current_step"] == "implement authentication"


def test_plain_message_does_not_change_state(client: TestClient, fake_api) -> None:
    """The state must not move on unrelated messages."""
    _configure(client)
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})
    client.post(f"/api/tasks/{task_id}/transition", json={"stage": "execution"})

    client.post(f"/api/chats/{task_id}/messages", json={"content": "Расскажи про Python"})

    assert client.get(f"/api/tasks/{task_id}/state").json()["data"]["stage"] == "execution"


# ------------------------------------------------------------ isolation
def test_task_state_is_separate_from_working_memory(
    client: TestClient, fake_api
) -> None:
    """Task state and working memory are different entities."""
    _configure(client)
    chat = _create_chat(client)
    task_id = chat["id"]

    client.post(
        f"/api/chats/{task_id}/messages",
        json={"content": "Сейчас мы разрабатываем API интернет-магазина"},
    )
    client.post(f"/api/tasks/{task_id}/state", json={})
    client.post(
        f"/api/tasks/{task_id}/transition",
        json={"stage": "execution", "current_step": "implement refresh token"},
    )

    working = client.get(f"/api/chats/{task_id}/memory/working").json()
    state = client.get(f"/api/tasks/{task_id}/state").json()

    # Working memory holds the task context...
    assert "интернет-магазина" in working["data"]["task"]
    # ...while the task state holds the machine position.
    assert state["data"]["stage"] == "execution"
    assert state["data"]["current_step"] == "implement refresh token"
    # Neither leaks into the other.
    assert "stage" not in working["data"]
    assert "интернет-магазина" not in state["data"]["current_step"]


def test_task_states_are_isolated_per_chat(client: TestClient) -> None:
    first = _create_chat(client)
    second = _create_chat(client)

    client.post(f"/api/tasks/{first['id']}/state", json={})
    client.post(f"/api/tasks/{first['id']}/transition", json={"stage": "execution"})

    assert client.get(f"/api/tasks/{first['id']}/state").json()["data"]["stage"] == "execution"
    assert client.get(f"/api/tasks/{second['id']}/state").json()["exists"] is False


def test_task_state_removed_with_chat(client: TestClient) -> None:
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    client.delete(f"/api/chats/{task_id}")

    assert client.get(f"/api/tasks/{task_id}/state").json()["exists"] is False


# ------------------------------------------------------------ unit level
def test_manager_rejects_invalid_transition(database) -> None:
    chat_id = ChatRepository(database).create(model="m").id
    manager = TaskStateManager(TaskStateRepository(database))
    manager.create_state(chat_id)

    with pytest.raises(InvalidTransitionError):
        manager.transition(chat_id, "done")


def test_manager_allowed_transitions(database) -> None:
    chat_id = ChatRepository(database).create(model="m").id
    manager = TaskStateManager(TaskStateRepository(database))
    manager.create_state(chat_id)

    assert manager.allowed_transitions("planning") == ("execution",)
    assert manager.allowed_transitions("execution") == ("validation",)
    assert manager.allowed_transitions("validation") == ("done",)
    assert manager.allowed_transitions("done") == ()
    assert manager.can_transition(chat_id, "execution") is True
    assert manager.can_transition(chat_id, "done") is False


def test_manager_pause_and_resume_are_idempotent(database) -> None:
    chat_id = ChatRepository(database).create(model="m").id
    manager = TaskStateManager(TaskStateRepository(database))
    manager.create_state(chat_id)
    manager.transition(chat_id, "execution")

    manager.pause(chat_id)
    manager.pause(chat_id)  # second pause is a no-op
    assert manager.get_data(chat_id).status == "paused"

    manager.resume(chat_id)
    manager.resume(chat_id)  # second resume is a no-op
    assert manager.get_data(chat_id).status == "active"


def test_manager_create_is_idempotent(database) -> None:
    chat_id = ChatRepository(database).create(model="m").id
    manager = TaskStateManager(TaskStateRepository(database))
    manager.create_state(chat_id)
    manager.transition(chat_id, "execution")

    # Creating again must not reset the state.
    manager.create_state(chat_id)
    assert manager.get_data(chat_id).stage == "execution"


def test_manager_format_state(database) -> None:
    block = TaskStateManager.format_state(
        TaskStateData(
            stage="execution",
            current_step="implement refresh token",
            expected_action="write endpoint",
        )
    )
    assert "Stage: Execution" in block
    assert "Current step: implement refresh token" in block
    assert "Expected action: write endpoint" in block
    assert "Status: Active" in block


def test_prompt_builder_includes_task_state(database) -> None:
    chat_id = ChatRepository(database).create(model="m").id
    tasks = TaskStateManager(TaskStateRepository(database))
    tasks.create_state(chat_id)
    tasks.transition(chat_id, "execution", current_step="step one")

    builder = PromptBuilder(
        memory=MemoryManager(), profile=ProfileManager(), tasks=tasks
    )
    system = builder.build_messages(chat_id)[0]["content"]
    assert "## TASK STATE" in system
    assert "Current step: step one" in system


def test_prompt_builder_without_task_manager(database) -> None:
    """The builder still works when no task manager is wired in."""
    chat_id = ChatRepository(database).create(model="m").id
    builder = PromptBuilder(memory=MemoryManager(), profile=ProfileManager())
    system = builder.build_messages(chat_id)[0]["content"]
    assert "## TASK STATE" not in system


def test_update_step_via_manager(database) -> None:
    chat_id = ChatRepository(database).create(model="m").id
    manager = TaskStateManager(TaskStateRepository(database))
    manager.create_state(chat_id)

    updated = manager.apply_update(
        chat_id,
        TaskStateUpdate(current_step="new step", expected_action="new action"),
    )
    assert updated.data.current_step == "new step"
    assert updated.data.expected_action == "new action"
    assert updated.data.stage == "planning"


def test_create_state_with_payload(database) -> None:
    chat_id = ChatRepository(database).create(model="m").id
    manager = TaskStateManager(TaskStateRepository(database))
    state = manager.create_state(
        chat_id,
        payload=TaskStateCreate(
            stage="execution",
            current_step="step",
            expected_action="action",
            metadata={"source": "test"},
        ),
    )
    assert state.data.stage == "execution"
    assert state.data.metadata == {"source": "test"}


def test_apply_transition_payload(database) -> None:
    chat_id = ChatRepository(database).create(model="m").id
    manager = TaskStateManager(TaskStateRepository(database))
    manager.create_state(chat_id)

    state = manager.apply_transition(
        chat_id,
        TaskTransitionRequest(
            stage="execution", current_step="step", reason="plan approved"
        ),
    )
    assert state.data.stage == "execution"
    assert state.data.current_step == "step"

# ------------------------------------------------- step extraction (LLM)
def test_step_is_computed_after_reply(client: TestClient, fake_api) -> None:
    """current_step and expected_action are derived from the dialogue."""
    _configure(client)
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})
    client.post(f"/api/tasks/{task_id}/transition", json={"stage": "execution"})

    client.post(
        f"/api/chats/{task_id}/messages",
        json={"content": "Реализуем авторизацию через JWT"},
    )
    fake_api.wait_for_analysis()

    state = client.get(f"/api/tasks/{task_id}/state").json()
    assert state["data"]["current_step"] == "implement authentication"
    assert state["data"]["expected_action"] == "create login endpoint"


def test_step_extraction_uses_a_separate_api_call(
    client: TestClient, fake_api
) -> None:
    """The step is computed by its own request, not by the chat call."""
    _configure(client)
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    client.post(f"/api/chats/{task_id}/messages", json={"content": "Привет"})
    fake_api.wait_for_analysis()

    analysis = fake_api.analysis_requests()
    step_calls = [
        request
        for request in analysis
        if "Task State Extractor" in request["json"]["messages"][0]["content"]
    ]
    assert step_calls, "step extraction must issue its own API call"
    # The call carries the dialogue and the current stage.
    user_content = step_calls[-1]["json"]["messages"][1]["content"]
    assert "Текущий этап" in user_content
    assert "Привет" in user_content


def test_step_extraction_does_not_block_the_reply(
    client: TestClient, fake_api
) -> None:
    """The assistant's answer is returned even if step extraction fails."""
    _configure(client)
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    # Make the step extractor return unusable output.
    fake_api.step_response = fake_api.step_response.__class__(
        200,
        {"choices": [{"message": {"role": "assistant", "content": "не могу"}}]},
    )

    response = client.post(
        f"/api/chats/{task_id}/messages", json={"content": "Привет"}
    )
    assert response.status_code == 200
    assert response.json()["assistant_message"]["content"] == "Привет!"


def test_low_confidence_step_is_ignored(client: TestClient, fake_api) -> None:
    """A low-confidence suggestion must not overwrite the step."""
    _configure(client)
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})
    client.put(
        f"/api/tasks/{task_id}/state",
        json={"current_step": "manual step", "expected_action": "manual action"},
    )

    fake_api.step_response = fake_api.step_response.__class__(
        200,
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": (
                            '{"current_step": "guessed",'
                            ' "expected_action": "guessed", "confidence": 0.1}'
                        ),
                    }
                }
            ]
        },
    )

    client.post(f"/api/chats/{task_id}/messages", json={"content": "Привет"})
    fake_api.wait_for_analysis()

    state = client.get(f"/api/tasks/{task_id}/state").json()
    assert state["data"]["current_step"] == "manual step"
    assert state["data"]["expected_action"] == "manual action"


def test_empty_step_suggestion_is_ignored(client: TestClient, fake_api) -> None:
    _configure(client)
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    fake_api.step_response = fake_api.step_response.__class__(
        200,
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": (
                            '{"current_step": "", "expected_action": "",'
                            ' "confidence": 0.9}'
                        ),
                    }
                }
            ]
        },
    )

    client.post(f"/api/chats/{task_id}/messages", json={"content": "Привет"})
    fake_api.wait_for_analysis()

    state = client.get(f"/api/tasks/{task_id}/state").json()
    assert state["data"]["current_step"] == ""


def test_step_refresh_endpoint(client: TestClient, fake_api) -> None:
    """The endpoint forces a recomputation on demand."""
    _configure(client)
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})
    client.post(f"/api/tasks/{task_id}/transition", json={"stage": "execution"})

    response = client.post(f"/api/tasks/{task_id}/refresh-step")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["current_step"] == "implement authentication"
    assert data["expected_action"] == "create login endpoint"


def test_step_refresh_keeps_stage_and_status(client: TestClient, fake_api) -> None:
    """Recomputing the step must not move the state machine."""
    _configure(client)
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})
    client.post(f"/api/tasks/{task_id}/transition", json={"stage": "execution"})
    client.post(f"/api/tasks/{task_id}/pause", json={})

    client.post(f"/api/tasks/{task_id}/refresh-step")

    state = client.get(f"/api/tasks/{task_id}/state").json()
    assert state["data"]["stage"] == "execution"
    assert state["data"]["status"] == "paused"


def test_step_is_visible_in_prompt(client: TestClient, fake_api) -> None:
    """The computed step reaches the model on the next request."""
    _configure(client)
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})
    client.post(f"/api/tasks/{task_id}/transition", json={"stage": "execution"})

    client.post(f"/api/chats/{task_id}/messages", json={"content": "Первый"})
    fake_api.wait_for_analysis()
    client.post(f"/api/chats/{task_id}/messages", json={"content": "Второй"})

    system = _system_prompt(client, fake_api)
    assert "Current step: implement authentication" in system
    assert "Expected action: create login endpoint" in system


def test_step_extraction_is_isolated_per_chat(client: TestClient, fake_api) -> None:
    first = _create_chat(client)
    second = _create_chat(client)
    _configure(client)

    client.post(f"/api/tasks/{first['id']}/state", json={})
    client.post(f"/api/chats/{first['id']}/messages", json={"content": "Привет"})
    fake_api.wait_for_analysis()

    assert client.get(f"/api/tasks/{first['id']}/state").json()["data"][
        "current_step"
    ]
    assert (
        client.get(f"/api/tasks/{second['id']}/state").json()["exists"] is False
    )


# ------------------------------------------------- step extractor unit level
@pytest.mark.asyncio
async def test_extractor_parses_model_answer(monkeypatch) -> None:
    from backend.services.ai_client import AIClient
    from backend.tasks.extractor import TaskStepExtractor

    async def fake_complete(self, model, messages, **kwargs):
        return (
            '```json\n{"current_step": "implement refresh token",'
            ' "expected_action": "write endpoint", "confidence": 0.8}\n```'
        )

    monkeypatch.setattr(AIClient, "complete", fake_complete)

    client = AIClient("https://api.example.com/v1", "sk-test")
    extractor = TaskStepExtractor(client, model="gpt-4o-mini")
    suggestion = await extractor.extract(stage="execution")

    assert suggestion.current_step == "implement refresh token"
    assert suggestion.expected_action == "write endpoint"
    assert suggestion.confidence == 0.8
    assert suggestion.source == "llm"


@pytest.mark.asyncio
async def test_extractor_without_client_is_unavailable() -> None:
    from backend.tasks.extractor import TaskStepExtractor

    extractor = TaskStepExtractor(None)
    suggestion = await extractor.extract(stage="planning")
    assert suggestion.source == "unavailable"
    assert suggestion.is_empty()


@pytest.mark.asyncio
async def test_extractor_handles_garbage(monkeypatch) -> None:
    from backend.services.ai_client import AIClient
    from backend.tasks.extractor import TaskStepExtractor

    async def fake_complete(self, model, messages, **kwargs):
        return "извините, не могу"

    monkeypatch.setattr(AIClient, "complete", fake_complete)

    client = AIClient("https://api.example.com/v1", "sk-test")
    extractor = TaskStepExtractor(client, model="gpt-4o-mini")
    suggestion = await extractor.extract(stage="execution")

    assert suggestion.source == "unparsed"
    assert suggestion.is_empty()


@pytest.mark.asyncio
async def test_extractor_handles_api_error(monkeypatch) -> None:
    from backend.services.ai_client import AIClient
    from backend.tasks.extractor import TaskStepExtractor

    async def fake_complete(self, model, messages, **kwargs):
        raise RuntimeError("api down")

    monkeypatch.setattr(AIClient, "complete", fake_complete)

    client = AIClient("https://api.example.com/v1", "sk-test")
    extractor = TaskStepExtractor(client, model="gpt-4o-mini")
    suggestion = await extractor.extract(stage="execution")

    assert suggestion.source == "error"
    assert suggestion.is_empty()


def test_extractor_usability_rules() -> None:
    from backend.tasks.extractor import TaskStepExtractor
    from backend.tasks.models import TaskStepSuggestion

    assert TaskStepExtractor.is_usable(
        TaskStepSuggestion(current_step="step", confidence=0.9)
    )
    assert not TaskStepExtractor.is_usable(
        TaskStepSuggestion(current_step="step", confidence=0.1)
    )
    assert not TaskStepExtractor.is_usable(TaskStepSuggestion(confidence=0.9))


def test_manager_applies_step_suggestion(database) -> None:
    from backend.tasks.manager import TaskStateManager
    from backend.tasks.models import TaskStepSuggestion

    chat_id = ChatRepository(database).create(model="m").id
    manager = TaskStateManager(TaskStateRepository(database))
    manager.create_state(chat_id)
    manager.transition(chat_id, "execution")

    state = manager.apply_step_suggestion(
        chat_id,
        TaskStepSuggestion(
            current_step="implement authentication",
            expected_action="create login endpoint",
            confidence=0.9,
        ),
    )
    assert state is not None
    assert state.data.current_step == "implement authentication"
    assert state.data.expected_action == "create login endpoint"
    # The state machine is untouched.
    assert state.data.stage == "execution"
    assert state.data.status == "active"


def test_manager_ignores_empty_suggestion(database) -> None:
    from backend.tasks.manager import TaskStateManager
    from backend.tasks.models import TaskStepSuggestion

    chat_id = ChatRepository(database).create(model="m").id
    manager = TaskStateManager(TaskStateRepository(database))
    manager.create_state(chat_id)

    assert manager.apply_step_suggestion(chat_id, TaskStepSuggestion()) is None

# ------------------------------------------- stage in the same extraction call
def test_stage_is_computed_in_the_same_call(client: TestClient, fake_api) -> None:
    """One extraction call returns the stage together with the step."""
    _configure(client)
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    client.post(f"/api/chats/{task_id}/messages", json={"content": "Начинаем работу"})
    fake_api.wait_for_analysis()

    state = client.get(f"/api/tasks/{task_id}/state").json()
    # The fake extractor answers with stage=execution, step and action.
    assert state["data"]["stage"] == "execution"
    assert state["data"]["current_step"] == "implement authentication"
    assert state["data"]["expected_action"] == "create login endpoint"

    # Exactly one extraction call produced all three fields.
    step_calls = [
        request
        for request in fake_api.analysis_requests()
        if "Task State Extractor" in request["json"]["messages"][0]["content"]
    ]
    assert len(step_calls) == 1


def test_extraction_prompt_asks_for_the_stage(client: TestClient, fake_api) -> None:
    """The prompt must request the stage, not only the step."""
    _configure(client)
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    client.post(f"/api/chats/{task_id}/messages", json={"content": "Привет"})
    fake_api.wait_for_analysis()

    step_call = next(
        request
        for request in fake_api.analysis_requests()
        if "Task State Extractor" in request["json"]["messages"][0]["content"]
    )
    system = step_call["json"]["messages"][0]["content"]
    assert '"stage"' in system
    assert "planning" in system and "execution" in system
    assert "validation" in system and "done" in system


def test_stage_only_suggestion_is_applied(client: TestClient, fake_api) -> None:
    """A suggestion with a stage but no step still moves the task."""
    _configure(client)
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    fake_api.step_response = fake_api.step_response.__class__(
        200,
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": (
                            '{"stage": "execution", "current_step": "",'
                            ' "expected_action": "", "confidence": 0.9}'
                        ),
                    }
                }
            ]
        },
    )

    client.post(f"/api/chats/{task_id}/messages", json={"content": "Привет"})
    fake_api.wait_for_analysis()

    assert client.get(f"/api/tasks/{task_id}/state").json()["data"]["stage"] == "execution"


def test_unknown_stage_is_ignored(client: TestClient, fake_api) -> None:
    """A stage outside the vocabulary must not be applied."""
    _configure(client)
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    fake_api.step_response = fake_api.step_response.__class__(
        200,
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": (
                            '{"stage": "nonsense", "current_step": "step",'
                            ' "expected_action": "action", "confidence": 0.9}'
                        ),
                    }
                }
            ]
        },
    )

    client.post(f"/api/chats/{task_id}/messages", json={"content": "Привет"})
    fake_api.wait_for_analysis()

    state = client.get(f"/api/tasks/{task_id}/state").json()
    assert state["data"]["stage"] == "planning"  # unchanged
    assert state["data"]["current_step"] == "step"  # step still applied


def test_stage_jump_walks_intermediate_stages(client: TestClient, fake_api) -> None:
    """A proposed jump is walked in order, never taken directly."""
    _configure(client)
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})

    fake_api.step_response = fake_api.step_response.__class__(
        200,
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": (
                            '{"stage": "done", "current_step": "finished",'
                            ' "expected_action": "", "confidence": 0.9}'
                        ),
                    }
                }
            ]
        },
    )

    client.post(f"/api/chats/{task_id}/messages", json={"content": "Всё готово"})
    fake_api.wait_for_analysis()

    state = client.get(f"/api/tasks/{task_id}/state").json()
    # planning → execution → validation → done, one edge at a time.
    assert state["data"]["stage"] == "done"
    assert state["data"]["status"] == "completed"


def test_stage_does_not_move_backwards(client: TestClient, fake_api) -> None:
    """A proposal to go back is refused; the step is still stored."""
    _configure(client)
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})
    client.post(f"/api/tasks/{task_id}/transition", json={"stage": "execution"})

    fake_api.step_response = fake_api.step_response.__class__(
        200,
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": (
                            '{"stage": "planning", "current_step": "back",'
                            ' "expected_action": "back", "confidence": 0.9}'
                        ),
                    }
                }
            ]
        },
    )

    client.post(f"/api/chats/{task_id}/messages", json={"content": "Привет"})
    fake_api.wait_for_analysis()

    state = client.get(f"/api/tasks/{task_id}/state").json()
    assert state["data"]["stage"] == "execution"  # not moved back
    assert state["data"]["current_step"] == "back"


def test_paused_task_keeps_status_when_stage_is_recomputed(
    client: TestClient, fake_api
) -> None:
    """Recomputing the state must not silently resume a paused task."""
    _configure(client)
    chat = _create_chat(client)
    task_id = chat["id"]
    client.post(f"/api/tasks/{task_id}/state", json={})
    client.post(f"/api/tasks/{task_id}/transition", json={"stage": "execution"})
    client.post(f"/api/tasks/{task_id}/pause", json={})

    # The extractor proposes the same stage, so nothing should change.
    fake_api.step_response = fake_api.step_response.__class__(
        200,
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": (
                            '{"stage": "execution", "current_step": "step",'
                            ' "expected_action": "action", "confidence": 0.9}'
                        ),
                    }
                }
            ]
        },
    )

    client.post(f"/api/chats/{task_id}/messages", json={"content": "Привет"})
    fake_api.wait_for_analysis()

    state = client.get(f"/api/tasks/{task_id}/state").json()
    assert state["data"]["status"] == "paused"
    assert state["data"]["stage"] == "execution"


def test_manager_applies_stage_from_suggestion(database) -> None:
    from backend.tasks.manager import TaskStateManager
    from backend.tasks.models import TaskStepSuggestion

    chat_id = ChatRepository(database).create(model="m").id
    manager = TaskStateManager(TaskStateRepository(database))
    manager.create_state(chat_id)

    state = manager.apply_step_suggestion(
        chat_id,
        TaskStepSuggestion(
            stage="execution",
            current_step="implement authentication",
            expected_action="create login endpoint",
            confidence=0.9,
        ),
    )
    assert state is not None
    assert state.data.stage == "execution"
    assert state.data.current_step == "implement authentication"


def test_manager_walks_stage_jump(database) -> None:
    from backend.tasks.manager import TaskStateManager
    from backend.tasks.models import TaskStepSuggestion

    chat_id = ChatRepository(database).create(model="m").id
    manager = TaskStateManager(TaskStateRepository(database))
    manager.create_state(chat_id)

    state = manager.apply_step_suggestion(
        chat_id, TaskStepSuggestion(stage="done", confidence=0.9)
    )
    assert state is not None
    assert state.data.stage == "done"
    assert state.data.status == "completed"


def test_manager_ignores_backward_stage(database) -> None:
    from backend.tasks.manager import TaskStateManager
    from backend.tasks.models import TaskStepSuggestion

    chat_id = ChatRepository(database).create(model="m").id
    manager = TaskStateManager(TaskStateRepository(database))
    manager.create_state(chat_id)
    manager.transition(chat_id, "execution")

    state = manager.apply_step_suggestion(
        chat_id, TaskStepSuggestion(stage="planning", confidence=0.9)
    )
    assert state is not None
    assert state.data.stage == "execution"


def test_extractor_parses_stage() -> None:
    from backend.tasks.extractor import TaskStepExtractor

    suggestion = TaskStepExtractor._to_suggestion(
        {"stage": "validation", "current_step": "check", "confidence": 0.8}
    )
    assert suggestion.stage == "validation"


def test_extractor_drops_unknown_stage() -> None:
    from backend.tasks.extractor import TaskStepExtractor

    suggestion = TaskStepExtractor._to_suggestion(
        {"stage": "nonsense", "current_step": "check", "confidence": 0.8}
    )
    assert suggestion.stage is None
    assert suggestion.current_step == "check"


def test_extractor_stage_only_is_usable() -> None:
    from backend.tasks.extractor import TaskStepExtractor
    from backend.tasks.models import TaskStepSuggestion

    assert TaskStepExtractor.is_usable(
        TaskStepSuggestion(stage="execution", confidence=0.9)
    )
    assert not TaskStepExtractor.is_usable(
        TaskStepSuggestion(stage="execution", confidence=0.1)
    )
