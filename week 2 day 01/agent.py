"""Агент: сущность, которая ведёт собственный чат с LLM."""

from uuid import uuid4

from llm_client import LlmClient


class Agent:
    """Хранит имя, модель и историю сообщений; умеет получать ответ от LLM."""

    def __init__(self, name: str, model: str):
        self.id = uuid4().hex
        self.name = name
        self.model = model
        self._history: list[dict] = []

    @property
    def history(self) -> list[dict]:
        """История чата в формате Gradio messages."""
        return list(self._history)

    def add_user_message(self, text: str) -> None:
        self._history.append({"role": "user", "content": text})

    def reply(self, llm_client: LlmClient) -> str:
        """Запрашивает ответ LLM с учётом истории и добавляет его в чат."""
        answer = llm_client.send(self.model, self._history)
        self._history.append({"role": "assistant", "content": answer})
        return answer
