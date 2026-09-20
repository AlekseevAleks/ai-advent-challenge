"""Tests for multiple profiles and switching between them.

The point of these tests is that profiles are *data*: switching the active
profile changes the prompt, never the memory, and never leaks one profile's
settings into another.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.database.profile_repository import UserProfileRepository
from backend.database.repositories import ChatRepository
from backend.memory.manager import MemoryManager
from backend.profile.manager import (
    LastProfileError,
    ProfileInUseError,
    ProfileManager,
)
from backend.profile.models import (
    UserProfileCreate,
    UserProfileData,
    UserProfilePatch,
)
from backend.services.prompt_builder import PromptBuilder

#: The three profiles from the assignment.
DEVELOPER = {
    "language": "ru",
    "style": "concise",
    "format": "markdown",
    "technical_level": "advanced",
    "preferences": ["Prefer code", "Practical examples", "No long introductions"],
    "constraints": [],
    "custom_instructions": "",
}

STUDENT = {
    "language": "ru",
    "style": "detailed",
    "format": "step_by_step",
    "technical_level": "beginner",
    "preferences": [
        "Explain terminology",
        "Give simple examples",
        "Explain concepts gradually",
    ],
    "constraints": [],
    "custom_instructions": "",
}

ENGLISH_WORK = {
    "language": "en",
    "style": "professional",
    "format": "structured",
    "technical_level": "advanced",
    "preferences": ["Business-oriented answers", "No emojis", "Concise conclusions"],
    "constraints": [],
    "custom_instructions": "",
}

QUESTION = "Объясни dependency injection в FastAPI."


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


def _make_profile(client: TestClient, name: str, data: dict) -> dict:
    response = client.post(
        "/api/profiles", json={"name": name, "data": data}
    )
    assert response.status_code == 201, response.text
    return response.json()


# ------------------------------------------------------------ create
def test_create_profile(client: TestClient) -> None:
    profile = _make_profile(client, "Developer", DEVELOPER)
    assert profile["name"] == "Developer"
    assert profile["id"] == "developer"
    assert profile["data"]["style"] == "concise"
    assert profile["data"]["preferences"] == DEVELOPER["preferences"]


def test_create_multiple_profiles(client: TestClient) -> None:
    _make_profile(client, "Developer", DEVELOPER)
    _make_profile(client, "Student", STUDENT)
    _make_profile(client, "English Work", ENGLISH_WORK)

    payload = client.get("/api/profiles").json()
    names = {profile["name"] for profile in payload["profiles"]}
    assert {"Developer", "Student", "English Work"} <= names


def test_create_profile_requires_name(client: TestClient) -> None:
    assert client.post("/api/profiles", json={"name": ""}).status_code == 422


def test_create_profile_generates_unique_ids(client: TestClient) -> None:
    first = _make_profile(client, "Work", DEVELOPER)
    second = _make_profile(client, "Work", STUDENT)
    assert first["id"] != second["id"]


def test_first_created_profile_becomes_active(client: TestClient) -> None:
    """A brand-new install has a default profile; a new one does not steal it."""
    before = client.get("/api/profile/active").json()["id"]
    _make_profile(client, "Developer", DEVELOPER)
    after = client.get("/api/profile/active").json()["id"]
    assert after == before


# ------------------------------------------------------------ update
def test_update_profile(client: TestClient) -> None:
    profile = _make_profile(client, "Developer", DEVELOPER)

    response = client.put(
        f"/api/profiles/{profile['id']}",
        json={"name": "Developer Pro", "data": {**DEVELOPER, "style": "detailed"}},
    )
    assert response.status_code == 200
    updated = response.json()
    assert updated["name"] == "Developer Pro"
    assert updated["data"]["style"] == "detailed"

    reloaded = client.get(f"/api/profiles/{profile['id']}").json()
    assert reloaded["name"] == "Developer Pro"
    assert reloaded["data"]["style"] == "detailed"


def test_update_profile_description_only(client: TestClient) -> None:
    profile = _make_profile(client, "Developer", DEVELOPER)
    response = client.put(
        f"/api/profiles/{profile['id']}", json={"description": "For coding tasks"}
    )
    assert response.status_code == 200
    assert response.json()["description"] == "For coding tasks"
    # Settings are untouched.
    assert response.json()["data"]["style"] == "concise"


def test_update_missing_profile_returns_404(client: TestClient) -> None:
    assert client.put("/api/profiles/nope", json={"name": "x"}).status_code == 404


# ------------------------------------------------------------ delete
def test_delete_profile(client: TestClient) -> None:
    _make_profile(client, "Developer", DEVELOPER)
    student = _make_profile(client, "Student", STUDENT)

    assert client.delete(f"/api/profiles/{student['id']}").status_code == 204
    assert client.get(f"/api/profiles/{student['id']}").status_code == 404


def test_cannot_delete_active_profile(client: TestClient) -> None:
    """The active profile must be switched away from before deletion."""
    developer = _make_profile(client, "Developer", DEVELOPER)
    client.post(f"/api/profiles/{developer['id']}/activate")

    response = client.delete(f"/api/profiles/{developer['id']}")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "profile_in_use"


def test_cannot_delete_last_profile(client: TestClient) -> None:
    """At least one profile must always remain.

    The only profile is also the active one, so the active-profile guard fires
    first; either way the deletion is refused with 409.
    """
    payload = client.get("/api/profiles").json()
    only_id = payload["profiles"][0]["id"]

    response = client.delete(f"/api/profiles/{only_id}")
    assert response.status_code == 409
    assert response.json()["error"]["code"] in {"last_profile", "profile_in_use"}


def test_last_profile_guard_when_not_active(client: TestClient) -> None:
    """With two profiles, deleting the non-active one is allowed; the guard
    then protects the remaining single profile."""
    developer = _make_profile(client, "Developer", DEVELOPER)
    student = _make_profile(client, "Student", STUDENT)

    # Activate Student, delete Developer (allowed: not active, not last).
    client.post(f"/api/profiles/{student['id']}/activate")
    assert client.delete(f"/api/profiles/{developer['id']}").status_code == 204

    # Now Student is the only profile and is active: deletion is refused.
    assert client.delete(f"/api/profiles/{student['id']}").status_code == 409


def test_delete_missing_profile_returns_404(client: TestClient) -> None:
    assert client.delete("/api/profiles/nope").status_code == 404


# ------------------------------------------------------------ duplicate
def test_duplicate_profile(client: TestClient) -> None:
    developer = _make_profile(client, "Developer", DEVELOPER)

    response = client.post(f"/api/profiles/{developer['id']}/duplicate")
    assert response.status_code == 201
    copy = response.json()

    assert copy["id"] != developer["id"]
    assert copy["name"] == "Developer (copy)"
    # Settings are copied verbatim; only the name differs.
    assert copy["data"]["style"] == developer["data"]["style"]
    assert copy["data"]["preferences"] == developer["data"]["preferences"]
    assert copy["data"]["language"] == developer["data"]["language"]
    # The copy is not activated automatically.
    assert copy["is_active"] is False


def test_duplicate_profile_with_custom_name(client: TestClient) -> None:
    developer = _make_profile(client, "Developer", DEVELOPER)
    response = client.post(
        f"/api/profiles/{developer['id']}/duplicate", json={"name": "Developer 2"}
    )
    assert response.json()["name"] == "Developer 2"


def test_duplicate_is_independent(client: TestClient) -> None:
    """Editing a copy must not change the original."""
    developer = _make_profile(client, "Developer", DEVELOPER)
    copy = client.post(f"/api/profiles/{developer['id']}/duplicate").json()

    client.put(
        f"/api/profiles/{copy['id']}",
        json={"data": {**DEVELOPER, "style": "detailed"}},
    )

    original = client.get(f"/api/profiles/{developer['id']}").json()
    assert original["data"]["style"] == "concise"


# ------------------------------------------------------------ activate
def test_activate_profile(client: TestClient) -> None:
    developer = _make_profile(client, "Developer", DEVELOPER)
    student = _make_profile(client, "Student", STUDENT)

    client.post(f"/api/profiles/{developer['id']}/activate")
    assert client.get("/api/profile/active").json()["id"] == developer["id"]

    client.post(f"/api/profiles/{student['id']}/activate")
    assert client.get("/api/profile/active").json()["id"] == student["id"]


def test_only_one_active_profile(client: TestClient) -> None:
    developer = _make_profile(client, "Developer", DEVELOPER)
    student = _make_profile(client, "Student", STUDENT)
    work = _make_profile(client, "English Work", ENGLISH_WORK)

    for profile in (developer, student, work):
        client.post(f"/api/profiles/{profile['id']}/activate")
        payload = client.get("/api/profiles").json()
        active = [p for p in payload["profiles"] if p["is_active"]]
        assert len(active) == 1
        assert active[0]["id"] == profile["id"]
        assert payload["active_profile_id"] == profile["id"]


def test_activate_missing_profile_returns_404(client: TestClient) -> None:
    assert client.post("/api/profiles/nope/activate").status_code == 404


def test_active_profile_survives_restart(client: TestClient, app_config) -> None:
    developer = _make_profile(client, "Developer", DEVELOPER)
    client.post(f"/api/profiles/{developer['id']}/activate")

    from backend.main import create_app

    with TestClient(create_app()) as second_client:
        assert second_client.get("/api/profile/active").json()["id"] == developer["id"]


# ------------------------------------------------- active profile in prompt
def test_active_profile_is_used_in_prompt(client: TestClient, fake_api) -> None:
    _configure(client)
    developer = _make_profile(client, "Developer", DEVELOPER)
    client.post(f"/api/profiles/{developer['id']}/activate")

    chat = _create_chat(client)
    client.post(f"/api/chats/{chat['id']}/messages", json={"content": QUESTION})

    system = _system_prompt(client, fake_api)
    assert "## ACTIVE USER PROFILE" in system
    assert "Name: Developer" in system
    assert "Language: Russian" in system
    assert "Style: concise" in system
    assert "Technical level: advanced" in system
    assert "Prefer code" in system


def test_switching_profile_changes_prompt(client: TestClient, fake_api) -> None:
    """Profile A → request → prompt has A; switch to B → prompt has B only."""
    _configure(client)
    developer = _make_profile(client, "Developer", DEVELOPER)
    student = _make_profile(client, "Student", STUDENT)
    chat = _create_chat(client)

    client.post(f"/api/profiles/{developer['id']}/activate")
    client.post(f"/api/chats/{chat['id']}/messages", json={"content": QUESTION})
    first = _system_prompt(client, fake_api)
    assert "Name: Developer" in first
    assert "Style: concise" in first
    assert "Name: Student" not in first

    client.post(f"/api/profiles/{student['id']}/activate")
    client.post(f"/api/chats/{chat['id']}/messages", json={"content": QUESTION})
    second = _system_prompt(client, fake_api)
    assert "Name: Student" in second
    assert "Style: detailed" in second
    assert "step-by-step" in second
    # Nothing from the previous profile leaks in.
    assert "Name: Developer" not in second
    assert "Style: concise" not in second
    assert "Prefer code" not in second


def test_three_profiles_produce_three_prompts(client: TestClient, fake_api) -> None:
    """The three assignment profiles each yield their own prompt."""
    _configure(client)
    developer = _make_profile(client, "Developer", DEVELOPER)
    student = _make_profile(client, "Student", STUDENT)
    work = _make_profile(client, "English Work", ENGLISH_WORK)
    chat = _create_chat(client)

    prompts = {}
    for profile in (developer, student, work):
        client.post(f"/api/profiles/{profile['id']}/activate")
        client.post(f"/api/chats/{chat['id']}/messages", json={"content": QUESTION})
        prompts[profile["name"]] = _system_prompt(client, fake_api)

    assert "Language: Russian" in prompts["Developer"]
    assert "Style: concise" in prompts["Developer"]
    assert "Technical level: advanced" in prompts["Developer"]

    assert "Language: Russian" in prompts["Student"]
    assert "Style: detailed" in prompts["Student"]
    assert "Technical level: beginner" in prompts["Student"]
    assert "step-by-step" in prompts["Student"]

    assert "Language: English" in prompts["English Work"]
    assert "Style: professional" in prompts["English Work"]
    assert "structured" in prompts["English Work"]

    # All three prompts are genuinely different.
    assert len(set(prompts.values())) == 3


def test_switching_does_not_require_restart(client: TestClient, fake_api) -> None:
    """A switch applies to the very next message, in the same process."""
    _configure(client)
    developer = _make_profile(client, "Developer", DEVELOPER)
    student = _make_profile(client, "Student", STUDENT)
    chat = _create_chat(client)

    client.post(f"/api/profiles/{developer['id']}/activate")
    client.post(f"/api/chats/{chat['id']}/messages", json={"content": "Первый"})
    assert "Name: Developer" in _system_prompt(client, fake_api)

    client.post(f"/api/profiles/{student['id']}/activate")
    client.post(f"/api/chats/{chat['id']}/messages", json={"content": "Второй"})
    assert "Name: Student" in _system_prompt(client, fake_api)


# ------------------------------------------------------------ isolation
def test_profiles_are_isolated(client: TestClient) -> None:
    developer = _make_profile(client, "Developer", DEVELOPER)
    student = _make_profile(client, "Student", STUDENT)

    dev = client.get(f"/api/profiles/{developer['id']}").json()
    std = client.get(f"/api/profiles/{student['id']}").json()

    assert dev["data"]["style"] == "concise"
    assert std["data"]["style"] == "detailed"
    assert dev["data"]["preferences"] != std["data"]["preferences"]


def test_profile_prompt_blocks_are_isolated(client: TestClient) -> None:
    developer = _make_profile(client, "Developer", DEVELOPER)
    student = _make_profile(client, "Student", STUDENT)

    dev_block = client.get(
        f"/api/profile/prompt-block?profile_id={developer['id']}"
    ).json()["block"]
    std_block = client.get(
        f"/api/profile/prompt-block?profile_id={student['id']}"
    ).json()["block"]

    assert "Prefer code" in dev_block
    assert "Prefer code" not in std_block
    assert "Explain terminology" in std_block
    assert "Explain terminology" not in dev_block


def test_editing_one_profile_does_not_touch_another(client: TestClient) -> None:
    developer = _make_profile(client, "Developer", DEVELOPER)
    student = _make_profile(client, "Student", STUDENT)

    client.put(
        f"/api/profiles/{developer['id']}",
        json={"data": {**DEVELOPER, "language": "en"}},
    )

    assert client.get(f"/api/profiles/{student['id']}").json()["data"]["language"] == "ru"


# ------------------------------------------------------- profile vs memory
def test_memory_is_preserved_when_switching_profile(
    client: TestClient, fake_api
) -> None:
    """Switching profiles must not touch any memory layer."""
    _configure(client)
    developer = _make_profile(client, "Developer", DEVELOPER)
    student = _make_profile(client, "Student", STUDENT)
    chat = _create_chat(client)

    client.post(f"/api/profiles/{developer['id']}/activate")
    client.post(
        f"/api/chats/{chat['id']}/messages",
        json={"content": "Я предпочитаю Python. Сейчас мы разрабатываем API магазина"},
    )

    long_term_before = client.get("/api/memory/long-term").json()["entries"]
    working_before = client.get(f"/api/chats/{chat['id']}/memory/working").json()
    short_term_before = client.get(
        f"/api/chats/{chat['id']}/memory/short-term"
    ).json()["total_messages"]
    assert long_term_before, "long-term memory should have been extracted"

    client.post(f"/api/profiles/{student['id']}/activate")

    assert client.get("/api/memory/long-term").json()["entries"] == long_term_before
    assert (
        client.get(f"/api/chats/{chat['id']}/memory/working").json() == working_before
    )
    assert (
        client.get(f"/api/chats/{chat['id']}/memory/short-term").json()[
            "total_messages"
        ]
        == short_term_before
    )


def test_memory_reaches_prompt_under_every_profile(
    client: TestClient, fake_api
) -> None:
    """The same memory is visible regardless of the active profile."""
    _configure(client)
    developer = _make_profile(client, "Developer", DEVELOPER)
    student = _make_profile(client, "Student", STUDENT)
    chat = _create_chat(client)

    client.post(f"/api/profiles/{developer['id']}/activate")
    client.post(f"/api/chats/{chat['id']}/messages", json={"content": "Я предпочитаю Python"})
    client.post(f"/api/chats/{chat['id']}/messages", json={"content": "Что дальше?"})

    client.post(f"/api/profiles/{student['id']}/activate")
    client.post(f"/api/chats/{chat['id']}/messages", json={"content": "Что дальше?"})

    system = _system_prompt(client, fake_api)
    assert "Name: Student" in system
    assert "## Long-term memory" in system
    assert "Python" in system


def test_profile_does_not_create_memory(client: TestClient, fake_api) -> None:
    _configure(client)
    _make_profile(client, "Developer", DEVELOPER)
    assert client.get("/api/memory/long-term").json()["entries"] == []


# ------------------------------------------------------------ unit level
def test_manager_creates_default_profile_on_first_use(database) -> None:
    manager = ProfileManager()
    active = manager.get_active_profile_id()
    assert active == "default"
    assert manager.get(active).exists is True


def test_manager_refuses_to_delete_active(database) -> None:
    manager = ProfileManager()
    manager.create(UserProfileCreate(name="Developer", data=UserProfileData(**DEVELOPER)))
    manager.activate("developer")

    with pytest.raises(ProfileInUseError):
        manager.delete("developer")


def test_manager_refuses_to_delete_last(database) -> None:
    """The last remaining profile cannot be removed."""
    manager = ProfileManager()
    manager.get_active_profile_id()  # creates the default profile
    manager.create(UserProfileCreate(name="Developer", data=UserProfileData(**DEVELOPER)))
    manager.activate("developer")

    # Deleting the non-active profile is allowed...
    manager.delete("default")
    assert [p.id for p in manager.list_profiles()] == ["developer"]

    # ...but the last one is protected, even though it is also active.
    with pytest.raises((LastProfileError, ProfileInUseError)):
        manager.delete("developer")
    assert len(manager.list_profiles()) == 1


def test_manager_duplicate_keeps_settings(database) -> None:
    manager = ProfileManager()
    manager.create(UserProfileCreate(name="Developer", data=UserProfileData(**DEVELOPER)))
    copy = manager.duplicate("developer", None)

    assert copy.id != "developer"
    assert copy.data.preferences == DEVELOPER["preferences"]
    assert copy.is_active is False


def test_manager_activate_is_exclusive(database) -> None:
    manager = ProfileManager()
    manager.create(UserProfileCreate(name="Developer", data=UserProfileData(**DEVELOPER)))
    manager.create(UserProfileCreate(name="Student", data=UserProfileData(**STUDENT)))

    manager.activate("developer")
    assert manager.get_active_profile_id() == "developer"
    manager.activate("student")
    assert manager.get_active_profile_id() == "student"

    active = [p for p in manager.list_profiles() if p.is_active]
    assert len(active) == 1


def test_manager_recovers_when_active_profile_is_gone(database) -> None:
    """A dangling active id self-heals instead of breaking requests."""
    repo = UserProfileRepository(database)
    manager = ProfileManager(repo)
    manager.create(UserProfileCreate(name="Developer", data=UserProfileData(**DEVELOPER)))
    manager.activate("developer")

    # Simulate the active profile disappearing out-of-band.
    repo.delete("developer")

    assert manager.get_active_profile_id() == "default"


def test_prompt_builder_uses_active_profile(database) -> None:
    chat_id = ChatRepository(database).create(model="m").id
    memory = MemoryManager()
    profile = ProfileManager()
    profile.create(UserProfileCreate(name="Developer", data=UserProfileData(**DEVELOPER)))
    profile.activate("developer")

    builder = PromptBuilder(memory=memory, profile=profile)
    system = builder.build_messages(chat_id)[0]["content"]

    assert "Name: Developer" in system
    assert "Style: concise" in system


def test_prompt_builder_switches_with_active_profile(database) -> None:
    chat_id = ChatRepository(database).create(model="m").id
    memory = MemoryManager()
    profile = ProfileManager()
    profile.create(UserProfileCreate(name="Developer", data=UserProfileData(**DEVELOPER)))
    profile.create(UserProfileCreate(name="Student", data=UserProfileData(**STUDENT)))
    builder = PromptBuilder(memory=memory, profile=profile)

    profile.activate("developer")
    assert "Name: Developer" in builder.build_messages(chat_id)[0]["content"]

    profile.activate("student")
    system = builder.build_messages(chat_id)[0]["content"]
    assert "Name: Student" in system
    assert "Name: Developer" not in system


def test_profile_summary_label(database) -> None:
    manager = ProfileManager()
    manager.create(UserProfileCreate(name="Developer", data=UserProfileData(**DEVELOPER)))
    summary = next(p for p in manager.list_profiles() if p.id == "developer")
    assert summary.label() == "Advanced · Russian · Concise"


def test_update_profile_via_manager(database) -> None:
    manager = ProfileManager()
    manager.create(UserProfileCreate(name="Developer", data=UserProfileData(**DEVELOPER)))

    updated = manager.update(
        "developer", UserProfilePatch(name="Dev", description="Coding")
    )
    assert updated.name == "Dev"
    assert updated.description == "Coding"
    assert updated.data.style == "concise"

# ------------------------------------------------------------ migration
def test_migration_adds_columns_to_existing_database(tmp_path) -> None:
    """An older database without name/description is upgraded in place."""
    import sqlite3

    from backend.database.database import Database

    db_path = tmp_path / "old.db"

    # Simulate the previous schema: user_profiles without name/description.
    legacy = sqlite3.connect(str(db_path))
    legacy.executescript(
        """
        CREATE TABLE user_profiles (
            id          TEXT PRIMARY KEY,
            data        TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        );
        """
    )
    legacy.execute(
        "INSERT INTO user_profiles (id, data, created_at, updated_at)"
        " VALUES (?, ?, ?, ?)",
        ("default", '{"language": "ru", "style": "concise"}', "2024-01-01T00:00:00+00:00",
         "2024-01-01T00:00:00+00:00"),
    )
    legacy.commit()
    legacy.close()

    # Opening it with the current code must migrate, not crash.
    database = Database(db_path)
    repo = UserProfileRepository(database)

    meta = repo.get_meta("default")
    assert meta is not None
    assert meta[0] == ""  # name column added with a default
    assert meta[1] == ""

    # The pre-existing settings survived the migration.
    data = repo.get("default")
    assert data is not None
    assert data.language == "ru"
    assert data.style == "concise"

    # And the new columns are writable.
    repo.save("default", data, name="Migrated", description="from legacy")
    assert repo.get_meta("default")[0] == "Migrated"
    database.close()


def test_migration_is_idempotent(tmp_path) -> None:
    """Re-opening a migrated database must not fail or duplicate columns."""
    from backend.database.database import Database

    db_path = tmp_path / "twice.db"
    first = Database(db_path)
    first.close()
    second = Database(db_path)  # must not raise
    repo = UserProfileRepository(second)
    assert repo.count() == 0
    second.close()
