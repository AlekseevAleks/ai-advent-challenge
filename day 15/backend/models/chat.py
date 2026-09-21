"""Pydantic schemas for chats."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class ChatCreate(BaseModel):
    model: str = Field(..., min_length=1, description="Model id selected by the user.")
    title: Optional[str] = Field(default=None, max_length=200)

    @field_validator("model")
    @classmethod
    def _strip_model(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Модель не может быть пустой.")
        return value

    @field_validator("title")
    @classmethod
    def _strip_title(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        return value or None


class ChatUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    model: Optional[str] = None

    @field_validator("title")
    @classmethod
    def _strip_title(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        return value or None


class Chat(BaseModel):
    id: str
    title: str
    model: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


class ChatList(BaseModel):
    chats: list[Chat]