"""User profile: how the assistant should answer.

Kept separate from :mod:`backend.memory`, which describes what is known:

* profile    — language, style, format, technical level, preferences;
* short-term — the current dialogue;
* working    — the state of the current task;
* long-term  — durable facts about the user.

:class:`backend.profile.manager.ProfileManager` is the single entry point.
"""

from __future__ import annotations

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
    UserProfileUpdate,
)

__all__ = [
    "FORMAT_LABELS",
    "LANGUAGE_LABELS",
    "LEVEL_LABELS",
    "STYLE_LABELS",
    "ProfileDuplicateRequest",
    "UserProfile",
    "UserProfileCreate",
    "UserProfileData",
    "UserProfileList",
    "UserProfilePatch",
    "UserProfileSummary",
    "UserProfileUpdate",
]