"""Pydantic schemas for the user profile.

The profile answers a different question than the memory layers:

* profile     — *how* should the assistant answer?
* short-term  — what was said in this conversation?
* working     — what is the state of the current task?
* long-term   — what should be remembered about the user?

It is therefore stored separately and never merged into a memory layer.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

ResponseLanguage = Literal["auto", "ru", "en"]
ResponseStyle = Literal["concise", "balanced", "detailed", "professional"]
ResponseFormat = Literal["markdown", "plain", "step_by_step", "structured"]
TechnicalLevel = Literal["beginner", "intermediate", "advanced"]

#: Human-readable labels used when rendering the profile into the prompt.
LANGUAGE_LABELS = {
    "auto": "the same language the user writes in",
    "ru": "Russian",
    "en": "English",
}

STYLE_LABELS = {
    "concise": "concise — short answers, no filler, straight to the point",
    "balanced": "balanced — enough detail to be useful, without padding",
    "detailed": "detailed — thorough explanations with context and examples",
    "professional": (
        "professional — business-oriented tone, no emojis, "
        "clear conclusions"
    ),
}

FORMAT_LABELS = {
    "markdown": "markdown — headings, lists and fenced code blocks",
    "plain": "plain text — no markdown syntax",
    "step_by_step": "step-by-step — numbered steps the user can follow in order",
    "structured": (
        "structured — clearly separated sections with headings and summaries"
    ),
}

LEVEL_LABELS = {
    "beginner": (
        "beginner — avoid unexplained jargon, explain terminology, "
        "give concrete examples"
    ),
    "intermediate": "intermediate — assume general familiarity with the domain",
    "advanced": (
        "advanced — be precise and dense, skip basics, focus on trade-offs "
        "and edge cases"
    ),
}


class UserProfileData(BaseModel):
    """The profile itself: how the assistant should answer."""

    name: str = ""
    description: str = ""
    display_name: str = ""
    language: ResponseLanguage = "auto"
    style: ResponseStyle = "balanced"
    format: ResponseFormat = "markdown"
    technical_level: TechnicalLevel = "intermediate"
    preferences: List[str] = Field(default_factory=list)
    constraints: List[str] = Field(default_factory=list)
    custom_instructions: str = ""

    @field_validator("preferences", "constraints")
    @classmethod
    def _clean_list(cls, value: List[str]) -> List[str]:
        cleaned: List[str] = []
        for item in value:
            text = str(item).strip()
            if text and text not in cleaned:
                cleaned.append(text)
        return cleaned

    @field_validator("name", "description", "display_name", "custom_instructions")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    def is_default(self) -> bool:
        """True when the profile carries no personalisation at all."""
        return (
            not self.name
            and not self.description
            and not self.display_name
            and self.language == "auto"
            and self.style == "balanced"
            and self.format == "markdown"
            and self.technical_level == "intermediate"
            and not self.preferences
            and not self.constraints
            and not self.custom_instructions
        )


class UserProfile(BaseModel):
    """A stored profile, as returned by the API."""

    id: str
    name: str = ""
    description: str = ""
    data: UserProfileData = Field(default_factory=UserProfileData)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    exists: bool = False
    is_active: bool = False


class UserProfileUpdate(BaseModel):
    """Payload for creating or updating a profile."""

    data: UserProfileData


class UserProfileSummary(BaseModel):
    """Short description used in lists and selectors."""

    id: str
    name: str = ""
    description: str = ""
    language: ResponseLanguage = "auto"
    style: ResponseStyle = "balanced"
    format: ResponseFormat = "markdown"
    technical_level: TechnicalLevel = "intermediate"
    is_active: bool = False

    def label(self) -> str:
        """Human-readable one-liner, e.g. ``Advanced · Russian · Concise``."""
        return " · ".join(
            [
                self.technical_level.capitalize(),
                LANGUAGE_LABELS[self.language].split(" — ")[0].capitalize(),
                self.style.capitalize(),
            ]
        )


class UserProfileList(BaseModel):
    profiles: List[UserProfileSummary] = Field(default_factory=list)
    active_profile_id: str = "default"


class UserProfileCreate(BaseModel):
    """Payload for creating a profile."""

    name: str = Field(..., min_length=1, max_length=80)
    description: str = Field(default="", max_length=300)
    data: Optional[UserProfileData] = None

    @field_validator("name", "description")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class UserProfilePatch(BaseModel):
    """Payload for updating a profile (all fields optional)."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    description: Optional[str] = Field(default=None, max_length=300)
    data: Optional[UserProfileData] = None

    @field_validator("name", "description")
    @classmethod
    def _strip(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if value is not None else None


class ProfileDuplicateRequest(BaseModel):
    """Optional new name when duplicating a profile."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def _strip(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if value is not None else None