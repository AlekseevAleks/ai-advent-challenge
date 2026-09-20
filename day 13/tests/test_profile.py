"""Tests for the user profile layer.

The profile answers *how* to respond, so these tests check that it is stored
separately, survives restarts, reaches the model on every request, and stays
isolated between different profiles.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.database.profile_repository import UserProfileRepository
from backend.database.repositories import ChatRepository
from backend.memory.manager import MemoryManager
from backend.profile.manager import ProfileManager
from backend.profile.models import (
    UserProfileCreate,
    UserProfileData,
    UserProfileUpdate,
)
from backend.services.prompt_builder import PromptBuilder

#: Profile A from the assignment: Russian, concise, advanced, markdown, code.
PROFILE_A = {
    "display_name": "A",
    "language": "ru",
    "style": "concise",
    "format": "markdown",
    "technical_level": "advanced",
    "preferences": ["Prefer code"],
    "constraints": [],
    "custom_instructions": "",
}

#: Profile B from the assignment: English, detailed, beginner, step-by-step.
PROFILE_B = {
    "display_name": "B",
    "language": "en",
    "style": "detailed",
    "format": "step_by_step",
    "technical_level": "beginner",
    "preferences": [],
    "constraints": ["Explain terminology"],
    "custom_instructions": "",
}


def _configure(client: TestClient) -> None:
    client.put(
        "/api/settings",
        json={"api_base_url": "https://api.example.com/v1", "api_key": "sk-test123456"},
    )


def _create_chat(client: TestClient, model: str = "gpt-4o-mini") -> dict:
    return client.post("/api/chats", json={"model": model}).json()


def _system_prompt(client: TestClient, fake_api) -> str:
    """The system message of the most recent chat request."""
    requests = fake_api.chat_requests()
    assert requests, "no chat completion request was recorded"
    return requests[-1]["json"]["messages"][0]["content"]


# ------------------------------------------------------- save / load
def test_profile_defaults_when_never_saved(client: TestClient) -> None:
    """A fresh install self-heals: one default profile exists and is active."""
    payload = client.get("/api/profile").json()
    assert payload["id"] == "default"
    assert payload["exists"] is True
    assert payload["is_active"] is True
    assert payload["data"]["language"] == "auto"
    assert payload["data"]["style"] == "balanced"
    assert payload["data"]["format"] == "markdown"
    assert payload["data"]["technical_level"] == "intermediate"


def test_profile_save_and_load(client: TestClient) -> None:
    response = client.put("/api/profile", json={"data": PROFILE_A})
    assert response.status_code == 200
    saved = response.json()
    assert saved["exists"] is True
    assert saved["data"]["language"] == "ru"
    assert saved["data"]["style"] == "concise"
    assert saved["data"]["preferences"] == ["Prefer code"]

    reloaded = client.get("/api/profile").json()
    assert reloaded["data"] == saved["data"]


def test_profile_survives_restart(client: TestClient, app_config) -> None:
    client.put("/api/profile", json={"data": PROFILE_B})

    from backend.main import create_app

    with TestClient(create_app()) as second_client:
        payload = second_client.get("/api/profile").json()
        assert payload["data"]["language"] == "en"
        assert payload["data"]["technical_level"] == "beginner"
        assert payload["data"]["constraints"] == ["Explain terminology"]


def test_profile_reset(client: TestClient) -> None:
    """Reset clears the settings but keeps the profile itself."""
    client.put("/api/profile", json={"data": PROFILE_A})
    response = client.delete("/api/profile")
    assert response.status_code == 200
    assert response.json()["exists"] is True
    assert client.get("/api/profile").json()["data"]["language"] == "auto"


def test_profile_validation_rejects_unknown_values(client: TestClient) -> None:
    response = client.put(
        "/api/profile", json={"data": {"language": "klingon"}}
    )
    assert response.status_code == 422


def test_profile_lists_are_deduplicated(client: TestClient) -> None:
    payload = dict(PROFILE_A)
    payload["preferences"] = ["Prefer code", "Prefer code", "  "]
    saved = client.put("/api/profile", json={"data": payload}).json()
    assert saved["data"]["preferences"] == ["Prefer code"]


# ------------------------------------------------------- prompt injection
def test_profile_reaches_the_model(client: TestClient, fake_api) -> None:
    """The profile is sent to the API on every request, automatically."""
    _configure(client)
    client.put("/api/profile", json={"data": PROFILE_A})
    chat = _create_chat(client)

    client.post(f"/api/chats/{chat['id']}/messages", json={"content": "Привет"})

    system = _system_prompt(client, fake_api)
    assert "## ACTIVE USER PROFILE" in system
    assert "Language: Russian" in system
    assert "Style: concise" in system
    assert "Technical level: advanced" in system
    assert "Prefer code" in system


def test_profile_applied_without_user_asking(client: TestClient, fake_api) -> None:
    """The user never repeats preferences: the profile is applied by default."""
    _configure(client)
    client.put("/api/profile", json={"data": PROFILE_B})
    chat = _create_chat(client)

    client.post(
        f"/api/chats/{chat['id']}/messages",
        json={"content": "Explain dependency injection in FastAPI."},
    )

    system = _system_prompt(client, fake_api)
    assert "Language: English" in system
    assert "Style: detailed" in system
    assert "step-by-step" in system
    assert "beginner" in system
    assert "Explain terminology" in system


def test_default_profile_adds_no_personalisation(
    client: TestClient, fake_api
) -> None:
    """The untouched default profile must not impose any behaviour."""
    _configure(client)
    chat = _create_chat(client)
    client.post(f"/api/chats/{chat['id']}/messages", json={"content": "Привет"})

    system = _system_prompt(client, fake_api)
    # It may name itself, but it must not dictate language/style/level.
    assert "Language: the same language the user writes in" in system
    assert "Style: balanced" in system
    assert "Technical level: intermediate" in system
    assert "Preferences:" not in system
    assert "Constraints:" not in system


def test_profile_change_applies_to_next_message(client: TestClient, fake_api) -> None:
    """The profile is loaded per request, so edits take effect immediately."""
    _configure(client)
    chat = _create_chat(client)

    client.put("/api/profile", json={"data": PROFILE_A})
    client.post(f"/api/chats/{chat['id']}/messages", json={"content": "Первый"})
    assert "Language: Russian" in _system_prompt(client, fake_api)

    client.put("/api/profile", json={"data": PROFILE_B})
    client.post(f"/api/chats/{chat['id']}/messages", json={"content": "Second"})
    system = _system_prompt(client, fake_api)
    assert "Language: English" in system
    assert "Language: Russian" not in system


def test_prompt_order_is_profile_then_memory_then_dialogue(
    client: TestClient, fake_api
) -> None:
    """System instructions → profile → long-term → working → short-term."""
    _configure(client)
    client.put("/api/profile", json={"data": PROFILE_A})
    chat = _create_chat(client)

    client.post(f"/api/chats/{chat['id']}/messages", json={"content": "Я предпочитаю Python"})
    client.post(
        f"/api/chats/{chat['id']}/messages",
        json={"content": "Сейчас мы разрабатываем API интернет-магазина"},
    )
    client.post(f"/api/chats/{chat['id']}/messages", json={"content": "Что дальше?"})

    messages = fake_api.chat_requests()[-1]["json"]["messages"]
    system = messages[0]["content"]

    assert messages[0]["role"] == "system"
    profile_at = system.index("## ACTIVE USER PROFILE")
    long_term_at = system.index("## Long-term memory")
    working_at = system.index("## Working memory")
    assert profile_at < long_term_at < working_at

    # Short-term memory is the dialogue that follows the system message.
    assert [m["role"] for m in messages[1:]] == [
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
    ]


def test_profile_prompt_block_endpoint(client: TestClient) -> None:
    client.put("/api/profile", json={"data": PROFILE_A})
    payload = client.get("/api/profile/prompt-block").json()
    assert "## ACTIVE USER PROFILE" in payload["block"]
    assert "Russian" in payload["block"]


# ------------------------------------------------------- isolation
def test_profiles_are_isolated(client: TestClient, fake_api) -> None:
    """Two profiles never mix: each request uses exactly one of them."""
    _configure(client)
    client.put("/api/profile?profile_id=alice", json={"data": PROFILE_A})
    client.put("/api/profile?profile_id=bob", json={"data": PROFILE_B})

    alice = client.get("/api/profile?profile_id=alice").json()
    bob = client.get("/api/profile?profile_id=bob").json()

    assert alice["data"]["language"] == "ru"
    assert bob["data"]["language"] == "en"
    assert alice["data"]["style"] == "concise"
    assert bob["data"]["style"] == "detailed"


def test_profile_isolation_in_prompt(client: TestClient, fake_api) -> None:
    """The prompt block of one profile never contains the other's settings."""
    _configure(client)
    client.put("/api/profile?profile_id=alice", json={"data": PROFILE_A})
    client.put("/api/profile?profile_id=bob", json={"data": PROFILE_B})

    alice_block = client.get("/api/profile/prompt-block?profile_id=alice").json()["block"]
    bob_block = client.get("/api/profile/prompt-block?profile_id=bob").json()["block"]

    assert "Russian" in alice_block and "English" not in alice_block
    assert "English" in bob_block and "Russian" not in bob_block
    assert "Prefer code" in alice_block and "Prefer code" not in bob_block
    assert "Explain terminology" in bob_block
    assert "Explain terminology" not in alice_block


def test_profile_list_shows_both_profiles(client: TestClient) -> None:
    client.put("/api/profile?profile_id=alice", json={"data": PROFILE_A})
    client.put("/api/profile?profile_id=bob", json={"data": PROFILE_B})

    payload = client.get("/api/profiles").json()
    ids = {profile["id"] for profile in payload["profiles"]}
    assert {"alice", "bob"} <= ids


def test_profile_does_not_touch_memory_layers(client: TestClient, fake_api) -> None:
    """Saving a profile must not create memory entries."""
    _configure(client)
    client.put("/api/profile", json={"data": PROFILE_A})

    assert client.get("/api/memory/long-term").json()["entries"] == []
    chat = _create_chat(client)
    assert client.get(f"/api/chats/{chat['id']}/memory/working").json()["exists"] is False


def test_memory_does_not_leak_into_profile(client: TestClient, fake_api) -> None:
    """Long-term memory stays in its own layer, not in the profile."""
    _configure(client)
    chat = _create_chat(client)
    client.post(f"/api/chats/{chat['id']}/messages", json={"content": "Я предпочитаю Python"})

    profile = client.get("/api/profile").json()
    assert profile["data"]["preferences"] == []
    assert client.get("/api/memory/long-term").json()["entries"]


# ------------------------------------------------------- unit level
def test_format_profile_renders_all_fields(database) -> None:
    manager = ProfileManager()
    block = manager.format_profile(UserProfileData(**PROFILE_A))

    assert "Language: Russian" in block
    assert "Style: concise" in block
    assert "Format: markdown" in block
    assert "Technical level: advanced" in block
    assert "Preferences:" in block
    assert "- Prefer code" in block


def test_format_profile_empty_for_defaults(database) -> None:
    """A profile with no personalisation adds nothing to the prompt."""
    manager = ProfileManager()
    assert manager.format_profile(UserProfileData()) == ""
    # The auto-created default profile carries only a name, so it renders.
    assert "Language:" in manager.build_prompt_block()


def test_format_profile_includes_custom_instructions(database) -> None:
    manager = ProfileManager()
    data = UserProfileData(custom_instructions="Always answer with a table.")
    block = manager.format_profile(data)
    assert "Custom instructions:" in block
    assert "Always answer with a table." in block


def test_profile_manager_save_and_get(database) -> None:
    manager = ProfileManager()
    manager.create(
        UserProfileCreate(name="B", data=UserProfileData(**PROFILE_B))
    )
    manager.activate("b")

    stored = manager.get()
    assert stored.exists is True
    assert stored.data.language == "en"
    assert stored.data.technical_level == "beginner"


def test_profile_manager_isolates_by_id(database) -> None:
    manager = ProfileManager()
    manager.create(UserProfileCreate(name="alice", data=UserProfileData(**PROFILE_A)))
    manager.create(UserProfileCreate(name="bob", data=UserProfileData(**PROFILE_B)))

    assert manager.get_data("alice").language == "ru"
    assert manager.get_data("bob").language == "en"
    # An unknown id falls back to defaults instead of borrowing another profile.
    assert manager.get_data("carol").language == "auto"


def test_repository_keeps_profiles_separate(database) -> None:
    repo = UserProfileRepository(database)
    repo.save("alice", UserProfileData(**PROFILE_A), name="alice")
    repo.save("bob", UserProfileData(**PROFILE_B), name="bob")

    assert repo.get("alice").language == "ru"
    assert repo.get("bob").language == "en"
    assert repo.get("nobody") is None


def test_prompt_builder_orders_sections(database) -> None:
    chat_id = ChatRepository(database).create(model="m").id
    memory = MemoryManager()
    profile = ProfileManager()
    profile.create(UserProfileCreate(name="A", data=UserProfileData(**PROFILE_A)))

    memory.save_to_short_term(chat_id, "user", "Привет")
    memory.save_to_long_term(
        category="preference", key="preferred_language", value="Python"
    )

    builder = PromptBuilder(memory=memory, profile=profile)
    messages = builder.build_messages(chat_id)

    system = messages[0]["content"]
    assert system.index("## ACTIVE USER PROFILE") < system.index("## Long-term memory")
    assert [m["role"] for m in messages[1:]] == ["user"]


def test_prompt_builder_without_profile(database) -> None:
    """With no personalisation the system message stays minimal."""
    chat_id = ChatRepository(database).create(model="m").id
    builder = PromptBuilder(memory=MemoryManager(), profile=ProfileManager())
    messages = builder.build_messages(chat_id)
    system = messages[0]["content"]
    assert "Preferences:" not in system
    assert "Constraints:" not in system
    assert "Custom instructions:" not in system


@pytest.mark.asyncio
async def test_profile_applies_to_streaming_too(client: TestClient, fake_api) -> None:
    """Streaming requests carry the profile as well."""
    _configure(client)
    client.put("/api/profile", json={"data": PROFILE_B})
    chat = _create_chat(client)

    client.post(
        f"/api/chats/{chat['id']}/messages/stream",
        json={"content": "Explain dependency injection in FastAPI."},
    )

    stream_requests = fake_api.chat_requests()
    assert stream_requests
    system = stream_requests[-1]["json"]["messages"][0]["content"]
    assert "Language: English" in system
    assert "step-by-step" in system