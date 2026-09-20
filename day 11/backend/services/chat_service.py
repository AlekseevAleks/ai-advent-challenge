"""Chat orchestration: persistence + LLM interaction."""

from __future__ import annotations

import re
from typing import AsyncIterator, Dict, List, Optional, Tuple

from backend.database.repositories import ChatRepository, MessageRepository
from backend.models.chat import Chat
from backend.models.message import Message, MessageExchange, ChatRef
from backend.services.ai_client import AIClient, build_client_from_settings
from backend.utils.errors import NotFoundError, SettingsNotConfiguredError
from backend.utils.logging_config import get_logger

logger = get_logger(__name__)

MAX_TITLE_LENGTH = 60
MAX_CONTEXT_MESSAGES = 200


def derive_title(text: str, *, max_length: int = MAX_TITLE_LENGTH) -> str:
    """Build a short chat title from the first user message."""
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    cleaned = re.sub(r"^[#>*\-\s]+", "", cleaned)
    if not cleaned:
        return "Новый чат"
    if len(cleaned) <= max_length:
        return cleaned
    truncated = cleaned[:max_length].rsplit(" ", 1)[0] or cleaned[:max_length]
    return f"{truncated}…"


class ChatService:
    """High-level operations on chats and messages."""

    def __init__(
        self,
        chats: Optional[ChatRepository] = None,
        messages: Optional[MessageRepository] = None,
        memory: Optional["MemoryService"] = None,
    ) -> None:
        self.chats = chats or ChatRepository()
        self.messages = messages or MessageRepository()
        self.memory = memory

    def _memory(self) -> Optional["MemoryService"]:
        """Lazily build the memory service (kept optional for simple tests)."""
        if self.memory is None:
            try:
                from backend.services.memory_service import MemoryService

                self.memory = MemoryService(
                    chats=self.chats, messages=self.messages
                )
            except Exception:  # noqa: BLE001 - memory must not break chatting
                logger.exception("Не удалось инициализировать память агента")
                return None
        return self.memory

    # ------------------------------------------------------------------ chats
    def list_chats(self) -> List[Chat]:
        return self.chats.list()

    def create_chat(self, model: str, title: Optional[str] = None) -> Chat:
        chat = self.chats.create(model=model, title=title)
        logger.info("Создан чат %s (модель %s)", chat.id, chat.model)
        return chat

    def get_chat(self, chat_id: str) -> Chat:
        chat = self.chats.get(chat_id)
        if chat is None:
            raise NotFoundError("Чат не найден.")
        return chat

    def update_chat(
        self, chat_id: str, *, title: Optional[str] = None, model: Optional[str] = None
    ) -> Chat:
        self.get_chat(chat_id)
        updated = self.chats.update(chat_id, title=title, model=model)
        if updated is None:
            raise NotFoundError("Чат не найден.")
        return updated

    def delete_chat(self, chat_id: str) -> None:
        if not self.chats.delete(chat_id):
            raise NotFoundError("Чат не найден.")
        # Short-term memory is removed with the chat (messages cascade);
        # working memory is chat-scoped and must go too. Long-term memory is
        # user-scoped and is intentionally kept.
        memory = self._memory()
        if memory is not None:
            memory.on_chat_deleted(chat_id)
        logger.info("Удалён чат %s", chat_id)

    # --------------------------------------------------------------- messages
    def list_messages(self, chat_id: str) -> List[Message]:
        self.get_chat(chat_id)
        return self.messages.list_for_chat(chat_id)

    def _build_context(self, chat_id: str) -> List[Dict[str, str]]:
        """Build the LLM context from all three memory layers.

        Layout: system prompt (with long-term + working memory) → short-term
        dialogue. Falls back to the plain transcript if memory is unavailable.
        """
        memory = self._memory()
        if memory is not None:
            try:
                return memory.manager.build_messages(
                    chat_id, "", history_limit=MAX_CONTEXT_MESSAGES
                )
            except Exception:  # noqa: BLE001 - never break the chat
                logger.exception("Не удалось собрать контекст памяти")

        history = self.messages.list_for_chat(chat_id)
        if len(history) > MAX_CONTEXT_MESSAGES:
            history = history[-MAX_CONTEXT_MESSAGES:]
        return [{"role": m.role, "content": m.content} for m in history]

    async def _analyze_memory(
        self, chat_id: str, user_text: str, assistant_text: str
    ) -> None:
        """Run the memory extraction pipeline after an exchange.

        Failures are logged and swallowed: memory is an enhancement, not a
        prerequisite for answering.
        """
        memory = self._memory()
        if memory is None:
            return
        try:
            await memory.analyze(
                chat_id,
                user_message=user_text,
                assistant_message=assistant_text,
            )
        except Exception:  # noqa: BLE001
            logger.exception("[MEMORY] Анализ памяти не удался (чат %s)", chat_id)

    def _client(self, client: Optional[AIClient]) -> AIClient:
        if client is not None:
            return client
        built = build_client_from_settings()
        if not built.base_url:
            raise SettingsNotConfiguredError()
        return built

    def _last_user_text(self, chat_id: str) -> str:
        """Return the most recent user message of a chat (for memory analysis)."""
        for message in reversed(self.messages.list_for_chat(chat_id)):
            if message.role == "user":
                return message.content
        return ""

    def _maybe_rename(self, chat: Chat, user_text: str) -> Chat:
        """Rename a chat based on its first user message."""
        if chat.title != "Новый чат":
            return chat
        if self.messages.count_for_chat(chat.id) > 1:
            return chat
        new_title = derive_title(user_text)
        if new_title == chat.title:
            return chat
        updated = self.chats.update(chat.id, title=new_title)
        return updated or chat

    async def send_message(
        self,
        chat_id: str,
        content: str,
        *,
        client: Optional[AIClient] = None,
    ) -> MessageExchange:
        """Non-streaming exchange: store the user message, call the API, store the reply."""
        chat = self.get_chat(chat_id)
        ai = self._client(client)

        user_message = self.messages.add(chat_id, "user", content)
        chat = self._maybe_rename(chat, content)

        context = self._build_context(chat_id)
        reply_text = await ai.complete(chat.model, context)

        assistant_message = self.messages.add(chat_id, "assistant", reply_text)
        chat = self.chats.touch(chat_id) or chat

        await self._analyze_memory(chat_id, content, reply_text)

        return MessageExchange(
            user_message=user_message,
            assistant_message=assistant_message,
            chat=ChatRef(
                id=chat.id,
                title=chat.title,
                model=chat.model,
                updated_at=chat.updated_at,
            ),
        )

    async def stream_message(
        self,
        chat_id: str,
        content: str,
        *,
        client: Optional[AIClient] = None,
    ) -> AsyncIterator[Tuple[str, object]]:
        """Streaming exchange.

        Yields ``(event, payload)`` tuples:
        ``("user_message", Message)``, ``("delta", str)``,
        ``("done", Message)`` and ``("error", Exception)``.
        """
        chat = self.get_chat(chat_id)
        ai = self._client(client)

        user_message = self.messages.add(chat_id, "user", content)
        chat = self._maybe_rename(chat, content)
        yield "user_message", user_message

        context = self._build_context(chat_id)
        collected: List[str] = []
        try:
            async for delta in ai.stream_completion(chat.model, context):
                collected.append(delta)
                yield "delta", delta
        except Exception as exc:  # noqa: BLE001 - forwarded to the client
            logger.warning("Ошибка streaming для чата %s: %s", chat_id, exc)
            if collected:
                # Persist the partial answer so the user does not lose it.
                self.messages.add(chat_id, "assistant", "".join(collected))
                self.chats.touch(chat_id)
            yield "error", exc
            return

        text = "".join(collected)
        if not text.strip():
            text = "Модель вернула пустой ответ."
        assistant_message = self.messages.add(chat_id, "assistant", text)
        self.chats.touch(chat_id)
        await self._analyze_memory(chat_id, content, text)
        yield "done", assistant_message

    async def regenerate(
        self,
        chat_id: str,
        *,
        client: Optional[AIClient] = None,
    ) -> MessageExchange:
        """Drop the last assistant reply and generate a new one."""
        self.get_chat(chat_id)
        self.messages.delete_last_assistant(chat_id)
        ai = self._client(client)
        chat = self.get_chat(chat_id)
        context = self._build_context(chat_id)
        if not context:
            raise NotFoundError("В чате нет сообщений для повторной генерации.")
        last_user_text = self._last_user_text(chat_id)
        reply_text = await ai.complete(chat.model, context)
        assistant_message = self.messages.add(chat_id, "assistant", reply_text)
        chat = self.chats.touch(chat_id) or chat
        await self._analyze_memory(chat_id, last_user_text, reply_text)
        return MessageExchange(
            user_message=self.messages.list_for_chat(chat_id)[-2]
            if self.messages.count_for_chat(chat_id) >= 2
            else assistant_message,
            assistant_message=assistant_message,
            chat=ChatRef(
                id=chat.id,
                title=chat.title,
                model=chat.model,
                updated_at=chat.updated_at,
            ),
        )

    async def regenerate_stream(
        self,
        chat_id: str,
        *,
        client: Optional[AIClient] = None,
    ) -> AsyncIterator[Tuple[str, object]]:
        """Streaming variant of :meth:`regenerate`."""
        self.get_chat(chat_id)
        self.messages.delete_last_assistant(chat_id)
        ai = self._client(client)
        chat = self.get_chat(chat_id)
        context = self._build_context(chat_id)
        if not context:
            raise NotFoundError("В чате нет сообщений для повторной генерации.")
        last_user_text = self._last_user_text(chat_id)

        collected: List[str] = []
        try:
            async for delta in ai.stream_completion(chat.model, context):
                collected.append(delta)
                yield "delta", delta
        except Exception as exc:  # noqa: BLE001
            logger.warning("Ошибка повторной генерации для чата %s: %s", chat_id, exc)
            if collected:
                self.messages.add(chat_id, "assistant", "".join(collected))
                self.chats.touch(chat_id)
            yield "error", exc
            return

        text = "".join(collected) or "Модель вернула пустой ответ."
        assistant_message = self.messages.add(chat_id, "assistant", text)
        self.chats.touch(chat_id)
        await self._analyze_memory(chat_id, last_user_text, text)
        yield "done", assistant_message