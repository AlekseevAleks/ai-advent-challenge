"""Агент: сущность, которая ведёт собственный чат с LLM."""

from typing import Optional
from uuid import uuid4

from agent_store import AgentStore
from llm_client import LlmClient


class Agent:
    """Хранит имя, модель и историю сообщений; умеет получать ответ от LLM."""

    def __init__(
        self,
        name: str,
        model: str,
        agent_id: Optional[str] = None,
        history: Optional[list[dict]] = None,
        store: Optional[AgentStore] = None,
    ):
        self.id = agent_id if agent_id else uuid4().hex
        self.name = name
        self.model = model
        self._history: list[dict] = list(history) if history else []
        self._store = store

    @property
    def history(self) -> list[dict]:
        """История чата в формате Gradio messages."""
        return list(self._history)

    def add_user_message(self, text: str) -> None:
        self._history.append({"role": "user", "content": text})
        self._persist_message("user", text)

    def reply(self, llm_client: LlmClient) -> str:
        """Запрашивает ответ LLM с учётом истории и добавляет его в чат."""
        answer = llm_client.send(self.model, self._history)
        self._history.append({"role": "assistant", "content": answer})
        self._persist_message("assistant", answer)
        return answer

    def _persist_message(self, role: str, content: str) -> None:
        if self._store is not None:
            self._store.append_message(self.id, role, content)
