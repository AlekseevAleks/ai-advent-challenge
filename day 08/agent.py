"""Агент: сущность, которая ведёт собственный чат с LLM."""

from typing import Optional, Tuple
from uuid import uuid4

from agent_store import AgentStore
from llm_client import LlmClient, LlmReply

# Грубая оценка расхода токенов: в среднем около трёх символов на токен.
CHARS_PER_TOKEN = 3


class Agent:
    """Хранит имя, модель, лимит контекста и историю сообщений."""

    def __init__(
        self,
        name: str,
        model: str,
        agent_id: Optional[str] = None,
        history: Optional[list[dict]] = None,
        store: Optional[AgentStore] = None,
        context_limit: Optional[int] = None,
    ):
        self.id = agent_id if agent_id else uuid4().hex
        self.name = name
        self.model = model
        self.context_limit = context_limit
        self._history: list[dict] = list(history) if history else []
        self._store = store

    @property
    def history(self) -> list[dict]:
        """История для API-запросов: только role и content."""
        return [
            {"role": message["role"], "content": message["content"]}
            for message in self._history
        ]

    @property
    def chat_messages(self) -> list[dict]:
        """История для отображения в чате: с заголовками токенов у ответов."""
        return [
            self._to_chat_message(message)
            for message in self._history
        ]

    @staticmethod
    def _to_chat_message(message: dict) -> dict:
        """Добавляет сообщению строку с токенами, если они известны."""
        chat_message = {
            "role": message["role"],
            "content": message["content"],
        }
        total = message.get("total_tokens", 0)
        if total:
            token_line = (
                f"*Токены: запрос {message.get('prompt_tokens', 0)} / "
                f"ответ {message.get('completion_tokens', 0)} / всего {total}*"
            )
            chat_message["content"] = f"{token_line}\n\n{message['content']}"
        return chat_message

    def last_message_tokens(self) -> Optional[Tuple[int, int, int]]:
        """Токены последнего ответа модели: (запрос, ответ, всего)."""
        for message in reversed(self._history):
            if message["role"] != "assistant":
                continue
            if not message.get("total_tokens"):
                return None
            return (
                message.get("prompt_tokens", 0),
                message.get("completion_tokens", 0),
                message.get("total_tokens", 0),
            )
        return None

    def add_user_message(self, text: str) -> None:
        self._history.append({"role": "user", "content": text})
        self._persist_message("user", text)

    def reply(self, llm_client: LlmClient) -> LlmReply:
        """Запрашивает ответ LLM с учётом лимита контекста и добавляет его в чат."""
        reply = llm_client.send(self.model, self._history_for_request())
        self._history.append(
            {
                "role": "assistant",
                "content": reply.answer,
                "prompt_tokens": reply.prompt_tokens,
                "completion_tokens": reply.completion_tokens,
                "total_tokens": reply.total_tokens,
            }
        )
        self._persist_message(
            "assistant",
            reply.answer,
            reply.prompt_tokens,
            reply.completion_tokens,
            reply.total_tokens,
        )
        return reply

    def _history_for_request(self) -> list[dict]:
        """Обрезает историю так, чтобы она уместилась в лимит контекста.

        Сообщения отбрасываются с самых старых; последнее всегда остаётся,
        даже если одно оно превышает лимит.
        """
        if not self.context_limit:
            return list(self._history)
        kept: list[dict] = []
        used_tokens = 0
        for message in reversed(self._history):
            message_tokens = self._estimate_tokens(message)
            if kept and used_tokens + message_tokens > self.context_limit:
                break
            kept.append(message)
            used_tokens += message_tokens
        kept.reverse()
        return kept

    @staticmethod
    def _estimate_tokens(message: dict) -> int:
        """Оценивает токены сообщения: реальный расход ответа или длина текста."""
        if message["role"] == "assistant" and message.get("completion_tokens"):
            return message["completion_tokens"]
        return max(1, round(len(message["content"]) / CHARS_PER_TOKEN))

    def total_tokens(self) -> int:
        """Суммарный расход токенов за весь диалог (из базы)."""
        if self._store is None:
            return sum(
                message.get("total_tokens", 0)
                for message in self._history
                if message["role"] == "assistant"
            )
        return self._store.total_tokens_for_agent(self.id)

    def _persist_message(
        self,
        role: str,
        content: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
    ) -> None:
        if self._store is not None:
            self._store.append_message(
                self.id, role, content, prompt_tokens, completion_tokens, total_tokens
            )
