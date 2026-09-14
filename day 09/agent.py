"""Агент: сущность, которая ведёт собственный чат с LLM."""

from typing import Optional, Tuple
from uuid import uuid4

from agent_store import AgentStore
from llm_client import LlmClient, LlmReply, SUMMARY_SYSTEM_PROMPT

# Грубая оценка расхода токенов: в среднем около трёх символов на токен.
CHARS_PER_TOKEN = 3

# Шаблоны запроса суммаризатору: текущее резюме + одно вытесненное сообщение.
SUMMARY_USER_TEMPLATE = (
    "Текущее резюме:\n{summary}\n\n"
    "Новое сообщение для добавления:\n{role}: {content}"
)
SUMMARY_FIRST_USER_TEMPLATE = (
    "Текущее резюме:\n\nНовое сообщение для добавления:\n{role}: {content}"
)


class Agent:
    """Хранит имя, модель, лимиты и историю сообщений."""

    def __init__(
        self,
        name: str,
        model: str,
        agent_id: Optional[str] = None,
        history: Optional[list[dict]] = None,
        store: Optional[AgentStore] = None,
        context_limit: Optional[int] = None,
        recent_messages_limit: Optional[int] = None,
    ):
        self.id = agent_id if agent_id else uuid4().hex
        self.name = name
        self.model = model
        self.context_limit = context_limit
        self.recent_messages_limit = recent_messages_limit
        self._history: list[dict] = list(history) if history else []
        self._store = store
        # Сводка старых сообщений и граница: сколько сообщений истории уже
        # учтено в ней (индекс в self._history, не включительно).
        self._summary: Optional[str] = None
        self._summary_upto: int = 0
        self._summary_tokens: int = 0

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
        """Запрашивает ответ LLM с учётом лимитов и добавляет его в чат."""
        self._update_summary(llm_client)
        reply = llm_client.send(
            self.model,
            self._history_for_request(),
            system_prompt=self._system_prompt(),
        )
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
        """Собирает историю для запроса: окно последних сообщений.

        Сначала берутся последние recent_messages_limit сообщений (0 или None
        означают без ограничения), затем обрезка под лимит контекста с конца;
        последнее сообщение всегда остаётся.
        """
        window = (
            list(self._history)
            if not self.recent_messages_limit
            else list(self._history[-self.recent_messages_limit :])
        )
        if not self.context_limit:
            return window
        budget = self.context_limit - self._summary_token_estimate()
        kept: list[dict] = []
        used_tokens = 0
        for message in reversed(window):
            message_tokens = self._estimate_tokens(message)
            if kept and used_tokens + message_tokens > budget:
                break
            kept.append(message)
            used_tokens += message_tokens
        kept.reverse()
        return kept

    def _system_prompt(self) -> Optional[str]:
        """Сжатая история диалога для основного запроса; None, если резюме пусто."""
        if not self._summary:
            return None
        return f"Сжатая история диалога:\n{self._summary}"

    def _summary_token_estimate(self) -> int:
        """Оценка токенов сводки для расчёта бюджета контекста."""
        if not self._summary:
            return 0
        return max(1, round(len(self._summary) / CHARS_PER_TOKEN))

    def _update_summary(self, llm_client: LlmClient) -> None:
        """Инкрементально обновляет резюме вытесненными сообщениями.

        Пока сырых сообщений больше recent_messages_limit, самое старое
        неучтённое сообщение отправляется суммаризатору вместе с текущим
        резюме; возвращённый текст заменяет резюме целиком. Запросы к модели
        не показываются пользователю; резюме хранится в базе.
        """
        if not self.recent_messages_limit:
            return
        while len(self._history) - self._summary_upto > self.recent_messages_limit:
            displaced = self._history[self._summary_upto]
            summary_reply = llm_client.send(
                self.model,
                self._summary_request_messages(displaced),
                system_prompt=SUMMARY_SYSTEM_PROMPT,
            )
            self._summary = summary_reply.answer
            self._summary_upto += 1
            self._summary_tokens += summary_reply.total_tokens
            if self._store is not None:
                self._store.save_summary(
                    self.id, self._summary, self._summary_upto, self._summary_tokens
                )

    def _summary_request_messages(self, displaced: dict) -> list[dict]:
        """Запрос суммаризатору: текущее резюме + одно вытесненное сообщение."""
        template = (
            SUMMARY_USER_TEMPLATE if self._summary else SUMMARY_FIRST_USER_TEMPLATE
        )
        return [
            {
                "role": "user",
                "content": template.format(
                    summary=self._summary or "",
                    role=displaced["role"],
                    content=displaced["content"],
                ),
            }
        ]

    def restore_summary(
        self, summary: Optional[str], summary_upto: int, summary_tokens: int
    ) -> None:
        """Восстанавливает сводку из базы при старте сервера."""
        self._summary = summary
        self._summary_upto = summary_upto
        self._summary_tokens = summary_tokens

    def summary_text(self) -> Optional[str]:
        """Текущая сводка старых сообщений, если она есть."""
        return self._summary

    def summary_tokens(self) -> int:
        """Токены, потраченные на суммаризации за весь диалог."""
        return self._summary_tokens

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
            ) + self._summary_tokens
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
