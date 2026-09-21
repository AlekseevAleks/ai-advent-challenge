"""ProfileManager — the single entry point to user profiles.

A profile describes *how* the assistant should answer (language, style, format,
technical level, preferences, constraints, custom instructions). It is kept
apart from the memory layers, which describe *what* is known.

The manager owns three invariants:

* exactly one profile is active at a time (stored in ``app_state``);
* at least one profile always exists;
* the active profile can never be deleted without switching away first.

Profiles are plain data — there is no ``if profile == "developer"`` anywhere.
"""

from __future__ import annotations

import re
import uuid
from typing import List, Optional

from backend.database.profile_repository import (
    DEFAULT_PROFILE_ID,
    UserProfileRepository,
)
from backend.profile.models import (
    FORMAT_LABELS,
    LANGUAGE_LABELS,
    LEVEL_LABELS,
    STYLE_LABELS,
    ProfileDuplicateRequest,
    UserProfile,
    UserProfileCreate,
    UserProfileData,
    UserProfileList,
    UserProfilePatch,
    UserProfileSummary,
)
from backend.utils.errors import AppError, NotFoundError, ValidationError
from backend.utils.logging_config import get_logger

logger = get_logger(__name__)

#: Name given to the profile created automatically on first use.
DEFAULT_PROFILE_NAME = "Default"


class ProfileInUseError(AppError):
    """Raised when trying to delete the active profile."""

    status_code = 409
    code = "profile_in_use"
    default_message = (
        "Нельзя удалить активный профиль. Сначала переключитесь на другой."
    )


class LastProfileError(AppError):
    """Raised when trying to delete the only remaining profile."""

    status_code = 409
    code = "last_profile"
    default_message = "Должен остаться хотя бы один профиль."


def _slugify(value: str) -> str:
    """Turn a profile name into a stable, url-safe id."""
    translit = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
        "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
        "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
        "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    }
    lowered = value.strip().lower()
    converted = "".join(translit.get(char, char) for char in lowered)
    slug = re.sub(r"[^a-z0-9]+", "-", converted).strip("-")
    return slug or "profile"


class ProfileManager:
    """Reads, writes, activates and renders user profiles."""

    def __init__(
        self,
        repository: Optional[UserProfileRepository] = None,
        *,
        default_profile_id: str = DEFAULT_PROFILE_ID,
    ) -> None:
        self._repo = repository or UserProfileRepository()
        self.default_profile_id = default_profile_id

    # ------------------------------------------------------------ invariants
    def ensure_initialized(self) -> str:
        """Guarantee that at least one profile exists and one is active.

        Called on every read of the active profile, so a fresh database (or one
        where the active profile was removed out-of-band) self-heals.
        """
        ids = self._repo.list_ids()
        if not ids:
            data = UserProfileData(name=DEFAULT_PROFILE_NAME)
            self._repo.save(
                self.default_profile_id, data, name=DEFAULT_PROFILE_NAME
            )
            self._repo.set_active_profile_id(self.default_profile_id)
            logger.info(
                "[PROFILE] Создан профиль по умолчанию '%s'", self.default_profile_id
            )
            return self.default_profile_id

        active = self._repo.get_active_profile_id()
        if active is None or active not in ids:
            # The stored active profile is gone: fall back to the first one.
            self._repo.set_active_profile_id(ids[0])
            logger.info(
                "[PROFILE] Активный профиль отсутствовал, выбран '%s'", ids[0]
            )
            return ids[0]
        return active

    def get_active_profile_id(self) -> str:
        return self.ensure_initialized()

    # ------------------------------------------------------------- read API
    def get(self, profile_id: Optional[str] = None) -> UserProfile:
        """Return one profile; without an id, the active one."""
        resolved = profile_id or self.get_active_profile_id()
        data = self._repo.get(resolved)
        if data is None:
            return UserProfile(id=resolved, data=UserProfileData(), exists=False)
        meta = self._repo.get_meta(resolved)
        name, description, created_at, updated_at = meta if meta else (
            data.name,
            data.description,
            None,
            None,
        )
        return UserProfile(
            id=resolved,
            name=name or data.name,
            description=description or data.description,
            data=data,
            created_at=created_at,
            updated_at=updated_at,
            exists=True,
            is_active=resolved == self.get_active_profile_id(),
        )

    def get_data(self, profile_id: Optional[str] = None) -> UserProfileData:
        """The profile data used for a request (active profile by default)."""
        resolved = profile_id or self.get_active_profile_id()
        return self._repo.get(resolved) or UserProfileData()

    def list_profiles(self) -> List[UserProfileSummary]:
        active = self.get_active_profile_id()
        summaries: List[UserProfileSummary] = []
        for profile_id in self._repo.list_ids():
            data = self._repo.get(profile_id) or UserProfileData()
            meta = self._repo.get_meta(profile_id)
            name = (meta[0] if meta else "") or data.name
            description = (meta[1] if meta else "") or data.description
            summaries.append(
                UserProfileSummary(
                    id=profile_id,
                    name=name,
                    description=description,
                    language=data.language,
                    style=data.style,
                    format=data.format,
                    technical_level=data.technical_level,
                    is_active=profile_id == active,
                )
            )
        return summaries

    def list_response(self) -> UserProfileList:
        return UserProfileList(
            profiles=self.list_profiles(),
            active_profile_id=self.get_active_profile_id(),
        )

    # ------------------------------------------------------------ write API
    def _unique_id(self, name: str) -> str:
        base = _slugify(name)
        candidate = base
        suffix = 2
        while self._repo.exists(candidate):
            candidate = f"{base}-{suffix}"
            suffix += 1
        return candidate

    def create(self, payload: UserProfileCreate) -> UserProfile:
        """Create a new profile. The first profile created becomes active."""
        profile_id = self._unique_id(payload.name)
        data = payload.data or UserProfileData()
        data.name = payload.name
        data.description = payload.description
        self._repo.save(
            profile_id, data, name=payload.name, description=payload.description
        )
        if self._repo.get_active_profile_id() is None:
            self._repo.set_active_profile_id(profile_id)
        logger.info("[PROFILE] Создан профиль '%s' (%s)", payload.name, profile_id)
        return self.get(profile_id)

    def update(
        self, profile_id: str, payload: UserProfilePatch
    ) -> UserProfile:
        """Update name, description and/or settings of one profile."""
        if not self._repo.exists(profile_id):
            raise NotFoundError("Профиль не найден.")

        current = self._repo.get(profile_id) or UserProfileData()
        meta = self._repo.get_meta(profile_id)
        name = payload.name if payload.name is not None else (meta[0] if meta else "")
        description = (
            payload.description
            if payload.description is not None
            else (meta[1] if meta else "")
        )

        data = payload.data if payload.data is not None else current
        data.name = name
        data.description = description

        self._repo.save(profile_id, data, name=name, description=description)
        logger.info("[PROFILE] Профиль '%s' обновлён", profile_id)
        return self.get(profile_id)

    def delete(self, profile_id: str) -> None:
        """Delete a profile, refusing to remove the active or the last one.

        The active-profile rule is checked first: it is the more actionable
        message ("switch away first"), and it also covers the case where the
        active profile happens to be the only one.
        """
        if not self._repo.exists(profile_id):
            raise NotFoundError("Профиль не найден.")
        if profile_id == self.get_active_profile_id():
            raise ProfileInUseError()
        if self._repo.count() <= 1:
            raise LastProfileError()
        self._repo.delete(profile_id)
        logger.info("[PROFILE] Профиль '%s' удалён", profile_id)

    def duplicate(
        self,
        profile_id: str,
        payload: Optional[ProfileDuplicateRequest] = None,
    ) -> UserProfile:
        """Copy a profile under a new name. The copy is not activated."""
        if not self._repo.exists(profile_id):
            raise NotFoundError("Профиль не найден.")

        source = self._repo.get(profile_id) or UserProfileData()
        meta = self._repo.get_meta(profile_id)
        source_name = (meta[0] if meta else "") or source.name or profile_id
        new_name = (payload.name if payload and payload.name else f"{source_name} (copy)")

        copy = source.model_copy(deep=True)
        copy.name = new_name
        copy.description = source.description

        new_id = self._unique_id(new_name)
        self._repo.save(new_id, copy, name=new_name, description=copy.description)
        logger.info(
            "[PROFILE] Профиль '%s' скопирован в '%s'", profile_id, new_id
        )
        return self.get(new_id)

    def activate(self, profile_id: str) -> UserProfile:
        """Make one profile active. Exactly one profile is active at a time."""
        if not self._repo.exists(profile_id):
            raise NotFoundError("Профиль не найден.")
        self._repo.set_active_profile_id(profile_id)
        logger.info("[PROFILE] Активный профиль переключён на '%s'", profile_id)
        return self.get(profile_id)

    def reset(self, profile_id: Optional[str] = None) -> UserProfile:
        """Drop a profile's settings back to defaults (keeps the profile)."""
        resolved = profile_id or self.get_active_profile_id()
        if not self._repo.exists(resolved):
            raise NotFoundError("Профиль не найден.")
        meta = self._repo.get_meta(resolved)
        name = (meta[0] if meta else "") or resolved
        data = UserProfileData(name=name)
        self._repo.save(resolved, data, name=name, description="")
        logger.info("[PROFILE] Профиль '%s' сброшен к значениям по умолчанию", resolved)
        return self.get(resolved)

    # ---------------------------------------------------------- prompt block
    @staticmethod
    def format_profile(data: UserProfileData) -> str:
        """Render the profile as compact text for the system prompt.

        Only non-default values are emitted, so a default profile adds nothing
        to the request.
        """
        if data.is_default():
            return ""

        lines: List[str] = []
        if data.name:
            lines.append(f"Name: {data.name}")
        if data.description:
            lines.append(f"Description: {data.description}")
        lines.append(f"Language: {LANGUAGE_LABELS[data.language]}")
        lines.append(f"Style: {STYLE_LABELS[data.style]}")
        lines.append(f"Format: {FORMAT_LABELS[data.format]}")
        lines.append(f"Technical level: {LEVEL_LABELS[data.technical_level]}")

        if data.preferences:
            lines.append("Preferences:")
            lines.extend(f"- {item}" for item in data.preferences)
        if data.constraints:
            lines.append("Constraints:")
            lines.extend(f"- {item}" for item in data.constraints)
        if data.custom_instructions:
            lines.append(f"Custom instructions:\n{data.custom_instructions}")

        return "\n".join(lines)

    def build_prompt_block(self, profile_id: Optional[str] = None) -> str:
        """The profile section as it appears in the prompt (empty if default)."""
        resolved = profile_id or self.get_active_profile_id()
        data = self._repo.get(resolved) or UserProfileData()
        block = self.format_profile(data)
        if not block:
            return ""
        return f"## ACTIVE USER PROFILE\n\n{block}"

    def describe(self, profile_id: Optional[str] = None) -> str:
        """One-line summary, used in logs and the UI."""
        resolved = profile_id or self.get_active_profile_id()
        data = self._repo.get(resolved) or UserProfileData()
        return (
            f"id={resolved}, language={data.language}, style={data.style}, "
            f"format={data.format}, level={data.technical_level}"
        )