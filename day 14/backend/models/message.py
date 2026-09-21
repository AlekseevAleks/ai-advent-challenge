"""Pydantic schemas for messages."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

Role = Literal["system", "user", "assistant"]


class MessageCreate(BaseModel):
    content: str = Field(..., min_length=1)
    stream: bool = True

    @field_validator("content")
    @classmethod
    def _strip_content(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Сообщение не может быть пустым.")
        return value


class Message(BaseModel):
    id: str
    chat_id: str
    role: Role
    content: str
    created_at: datetime


class MessageList(BaseModel):
    messages: list[Message]


class MessageExchange(BaseModel):
    """Result of a non-streaming message exchange."""

    user_message: Message
    assistant_message: Message
    chat: "ChatRef"


class ChatRef(BaseModel):
    id: str
    title: str
    model: str
    updated_at: datetime


class ModelInfo(BaseModel):
    id: str
    owned_by: Optional[str] = None
    created: Optional[int] = None


class ModelList(BaseModel):
    models: list[ModelInfo]