"""FastAPI dependency providers."""

from __future__ import annotations

from typing import Optional

from backend.database.database import Database, get_database
from backend.database.memory_repositories import (
    LongTermMemoryRepository,
    WorkingMemoryRepository,
)
from backend.database.repositories import ChatRepository, MessageRepository
from backend.services.ai_client import AIClient, build_client_from_settings
from backend.services.chat_service import ChatService
from backend.services.memory_service import MemoryService
from backend.services.settings_service import SettingsService, get_settings_service


def get_db() -> Database:
    return get_database()


def get_chat_repository() -> ChatRepository:
    return ChatRepository(get_db())


def get_message_repository() -> MessageRepository:
    return MessageRepository(get_db())


def get_chat_service() -> ChatService:
    return ChatService(get_chat_repository(), get_message_repository())


def get_memory_service() -> MemoryService:
    """Memory service sharing the same repositories as the chat service."""
    return MemoryService(
        chats=get_chat_repository(),
        messages=get_message_repository(),
        working_repo=WorkingMemoryRepository(get_db()),
        long_term_repo=LongTermMemoryRepository(get_db()),
    )


def get_settings() -> SettingsService:
    return get_settings_service()


def get_ai_client() -> Optional[AIClient]:
    """Build an AI client from the stored settings (``None`` if unconfigured)."""
    settings = get_settings_service()
    if not settings.get_api_base_url():
        return None
    return build_client_from_settings()