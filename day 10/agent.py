"""Агент: сущность, которая ведёт собственный чат с LLM."""

import json
from typing import Optional, Tuple
from uuid import uuid4

from agent_store import AgentStore
from llm_client import LlmClient, LlmReply, FACTS_SYSTEM_PROMPT, SUMMARY_SYSTEM_PROMPT

# Грубая оценка расхода токенов: в среднем около трёх символов на токен.
CHARS_PER_TOKEN = 3

# Стратегии управления контекстом.
STRATEGY_SUMMARY = "Summary"
STRATEGY_SLIDING = "Sliding Window"
STRATEGY_FACTS = "Sticky Facts / Key-Value Memory"
STRATEGY_BRANCHING = "Branching"
ALL_STRATEGIES = [
    STRATEGY_SUMMARY,
    STRATEGY_SLIDING,
    STRATEGY_FACTS,
    STRATEGY_BRANCHING,
]
DEFAULT_STRATEGY = STRATEGY_SUMMARY

# Шаблоны запроса суммаризатору: текущее резюме + одно вытесненное сообщение.
SUMMARY_USER_TEMPLATE = (
    "Текущее резюме:\n{summary}\n\n"
    "Новое сообщение для добавления:\n{role}: {content}"
)
SUMMARY_FIRST_USER_TEMPLATE = (
    "Текущее резюме:\n\nНовое сообщение для добавления:\n{role}: {content}"
)

# Шаблон запроса экстрактору фактов: текущие факты + новое сообщение пользователя.
FACTS_USER_TEMPLATE = (
    "Текущие факты:\n{facts}\n\n"
    "Новое сообщение для добавления:\n{content}"
)
FACTS_FIRST_USER_TEMPLATE = (
    "Текущие факты:\n\nНовое сообщение для добавления:\n{content}"
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
        strategy: str = DEFAULT_STRATEGY,
    ):
        self.id = agent_id if agent_id else uuid4().hex
        self.name = name
        self.model = model
        self.context_limit = context_limit
        self.recent_messages_limit = recent_messages_limit
        self.strategy = strategy if strategy in ALL_STRATEGIES else DEFAULT_STRATEGY
        self._history: list[dict] = list(history) if history else []
        self._store = store
        # Сводка старых сообщений и граница: сколько сообщений истории уже
        # учтено в ней (индекс в self._history, не включительно).
        self._summary: Optional[str] = None
        self._summary_upto: int = 0
        self._summary_tokens: int = 0
        # Факты диалога (стратегия Sticky Facts): JSON-объект ключ-значение.
        self._facts: dict[str, str] = {}
        self._facts_tokens: int = 0
        # Ветки диалога (стратегия Branching): id -> {parent_id, name, upto}.
        self._branches: dict[str, dict] = {}
        self._active_branch_id: Optional[str] = None

    @property
    def branch_history(self) -> list[dict]:
        """Сообщения активной ветки: полный снимок (база + свои сообщения)."""
        if self._active_branch_id is None:
            return list(self._history)
        return self._branch_only_messages()

    @property
    def history(self) -> list[dict]:
        """История активной ветки для API-запросов: только role и content."""
        return [
            {"role": message["role"], "content": message["content"]}
            for message in self.branch_history
        ]

    @property
    def chat_messages(self) -> list[dict]:
        """История активной ветки для чата: с заголовками токенов у ответов."""
        return [
            self._to_chat_message(message)
            for message in self.branch_history
        ]

    def _active_branch_base(self) -> list[dict]:
        """Общая часть истории до точки ветвления активной ветки."""
        if self._active_branch_id is None:
            return list(self._history)
        branch = self._branches.get(self._active_branch_id)
        if branch is None:
            return list(self._history)
        return self._history[: branch.get("upto", len(self._history))]

    def _branch_only_messages(self) -> list[dict]:
        """Сообщения, добавленные внутри активной ветки."""
        if self._active_branch_id is None:
            return []
        return [
            message
            for message in self._history
            if message.get("branch_id") == self._active_branch_id
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
        message = {"role": "user", "content": text}
        if self._active_branch_id is not None:
            message["branch_id"] = self._active_branch_id
        self._history.append(message)
        self._persist_message("user", text)

    def reply(self, llm_client: LlmClient) -> LlmReply:
        """Запрашивает ответ LLM с учётом стратегии и добавляет его в чат."""
        if self.strategy == STRATEGY_SUMMARY:
            self._update_summary(llm_client)
        elif self.strategy == STRATEGY_FACTS:
            self._update_facts(llm_client)
        reply = llm_client.send(
            self.model,
            self._history_for_request(),
            system_prompt=self._system_prompt(),
        )
        message = {
            "role": "assistant",
            "content": reply.answer,
            "prompt_tokens": reply.prompt_tokens,
            "completion_tokens": reply.completion_tokens,
            "total_tokens": reply.total_tokens,
        }
        if self._active_branch_id is not None:
            message["branch_id"] = self._active_branch_id
        self._history.append(message)
        self._persist_message(
            "assistant",
            reply.answer,
            reply.prompt_tokens,
            reply.completion_tokens,
            reply.total_tokens,
        )
        return reply

    def _history_for_request(self) -> list[dict]:
        """Собирает сообщения для запроса по стратегии.

        Summary и Sticky Facts: последние recent_messages_limit сообщений.
        Sliding Window и Branching: вся история ветки без обрезки (ветка уже
        отделена от основного диалога). Затем общая обрезка под лимит
        контекста с учётом system-памяти; последнее сообщение всегда остаётся.
        """
        branch_messages = self.branch_history
        if self.strategy in (STRATEGY_SUMMARY, STRATEGY_SLIDING, STRATEGY_FACTS):
            window = (
                list(branch_messages)
                if not self.recent_messages_limit
                else list(branch_messages[-self.recent_messages_limit :])
            )
            memory_tokens = (
                self._summary_token_estimate()
                if self.strategy == STRATEGY_SUMMARY
                else self._facts_token_estimate()
            )
        else:
            window = list(branch_messages)
            memory_tokens = 0
        if not self.context_limit:
            return window
        budget = self.context_limit - memory_tokens
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
        """System-память основного запроса по стратегии; None, если пусто."""
        if self.strategy == STRATEGY_SUMMARY and self._summary:
            return f"Сжатая история диалога:\n{self._summary}"
        if self.strategy == STRATEGY_FACTS and self._facts:
            facts_text = "\n".join(
                f"- {key}: {value}" for key, value in self._facts.items()
            )
            return f"Важные факты диалога:\n{facts_text}"
        return None

    def _summary_token_estimate(self) -> int:
        """Оценка токенов сводки для расчёта бюджета контекста."""
        if not self._summary:
            return 0
        return max(1, round(len(self._summary) / CHARS_PER_TOKEN))

    def _facts_token_estimate(self) -> int:
        """Оценка токенов фактов для расчёта бюджета контекста."""
        if not self._facts:
            return 0
        facts_text = "\n".join(
            f"- {key}: {value}" for key, value in self._facts.items()
        )
        return max(1, round(len(facts_text) / CHARS_PER_TOKEN))

    def _update_summary(self, llm_client: LlmClient) -> None:
        """Инкрементально обновляет резюме вытесненными сообщениями.

        Пока сырых сообщений больше recent_messages_limit, самое старое
        неучтённое сообщение отправляется суммаризатору вместе с текущим
        резюме; возвращённый текст заменяет резюме целиком. Запросы к модели
        не показываются пользователю; резюме хранится в базе.
        """
        if not self.recent_messages_limit:
            return
        while len(self.branch_history) - self._summary_upto > self.recent_messages_limit:
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

    def _update_facts(self, llm_client: LlmClient) -> None:
        """Обновляет факты по последнему сообщению пользователя.

        Экстрактор возвращает JSON-объект ключ-значение; он заменяет прежние
        факты целиком. Вызывается после каждого сообщения пользователя.
        """
        if not self._history:
            return
        last_user = next(
            (m for m in reversed(self._history) if m["role"] == "user"), None
        )
        if last_user is None:
            return
        facts_reply = llm_client.send(
            self.model,
            self._facts_request_messages(last_user),
            system_prompt=FACTS_SYSTEM_PROMPT,
        )
        parsed = self._parse_facts_json(facts_reply.answer)
        if parsed is None:
            return
        self._facts = parsed
        self._facts_tokens += facts_reply.total_tokens
        if self._store is not None:
            self._store.save_facts(
                self.id, json.dumps(self._facts, ensure_ascii=False), self._facts_tokens
            )

    @staticmethod
    def _parse_facts_json(answer: str) -> Optional[dict[str, str]]:
        """Разбирает JSON-факты из ответа модели; None, если ответ невалиден."""
        start = answer.find("{")
        end = answer.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            data = json.loads(answer[start : end + 1])
        except ValueError:
            return None
        if not isinstance(data, dict):
            return None
        return {
            str(key): str(value)
            for key, value in data.items()
            if str(value).strip()
        }

    def _facts_request_messages(self, last_user: dict) -> list[dict]:
        """Запрос экстрактору фактов: текущие факты + сообщение пользователя."""
        template = (
            FACTS_USER_TEMPLATE if self._facts else FACTS_FIRST_USER_TEMPLATE
        )
        return [
            {
                "role": "user",
                "content": template.format(
                    facts=json.dumps(self._facts, ensure_ascii=False),
                    content=last_user["content"],
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

    def restore_facts(self, facts: Optional[str], facts_tokens: int) -> None:
        """Восстанавливает факты из базы при старте сервера."""
        self._facts = self._parse_facts_json(facts or "{}") or {}
        self._facts_tokens = facts_tokens

    def summary_text(self) -> Optional[str]:
        """Текущая сводка старых сообщений, если она есть."""
        return self._summary

    def summary_tokens(self) -> int:
        """Токены, потраченные на суммаризации за весь диалог."""
        return self._summary_tokens

    def facts_text(self) -> str:
        """Факты диалога отформатированным списком ключ-значение."""
        return "\n".join(f"- {key}: {value}" for key, value in self._facts.items())

    def facts_tokens(self) -> int:
        """Токены, потраченные на извлечение фактов за весь диалог."""
        return self._facts_tokens

    def branches(self) -> list[dict]:
        """Ветки диалога: id, имя и флаг активности."""
        return [
            {"id": branch_id, "name": branch["name"], "active": branch_id == self._active_branch_id}
            for branch_id, branch in self._branches.items()
        ]

    def _active_branch_upto(self) -> int:
        """Сколько сообщений активной ветки видно: до точки ветвления или всё."""
        if self._active_branch_id is None:
            return len(self._history)
        branch = self._branches.get(self._active_branch_id)
        if branch is None:
            return len(self._history)
        return branch.get("upto", len(self._history))

    def create_branch(self, upto: Optional[int] = None, name: Optional[str] = None) -> dict:
        """Создаёт ветку от точки upto (по умолчанию — конец истории).

        Ветка получает копию сообщений [0:upto] как отправную точку и дальше
        развивается независимо. Новая ветка сразу становится активной.
        """
        if upto is None:
            upto = len(self._history)
        branch_id = uuid4().hex
        branch_name = name or f"Ветка {len(self._branches) + 1}"
        parent_id = self._active_branch_id
        snapshot = []
        for index, message in enumerate(self._history[:upto]):
            copied = dict(message)
            copied["branch_id"] = branch_id
            snapshot.append(copied)
            self._history.append(copied)
        self._branches[branch_id] = {
            "parent_id": parent_id,
            "name": branch_name,
            "upto": upto,
        }
        if self._store is not None:
            self._store.save_branch(branch_id, self.id, parent_id, branch_name, upto)
            self._store.save_branch_messages(branch_id, self.id, snapshot)
        self.switch_branch(branch_id)
        return {"id": branch_id, "name": branch_name}

    def _active_branch_base_len(self) -> int:
        """Длина общей части истории текущей активной ветки."""
        if self._active_branch_id is None:
            return len(self._history)
        branch = self._branches.get(self._active_branch_id)
        if branch is None:
            return len(self._history)
        return branch.get("upto", len(self._history))

    def switch_branch(self, branch_id: Optional[str]) -> None:
        """Переключает активную ветку диалога."""
        if branch_id is not None and branch_id not in self._branches:
            return
        self._active_branch_id = branch_id
        if self._store is not None:
            self._store.save_active_branch(self.id, branch_id)

    def restore_branches(
        self,
        branch_records: list[dict],
        active_branch_id: Optional[str],
        branch_messages: Optional[dict[str, list[dict]]] = None,
    ) -> None:
        """Восстанавливает ветки и их сообщения из базы при старте сервера."""
        for record in branch_records:
            self._branches[record["id"]] = {
                "parent_id": record.get("parent_id"),
                "name": record["name"],
                "upto": record.get("upto", 0),
            }
        for branch_id, messages in (branch_messages or {}).items():
            for message in messages:
                tagged = dict(message)
                tagged["branch_id"] = branch_id
                self._history.append(tagged)
        if active_branch_id and active_branch_id in self._branches:
            self._active_branch_id = active_branch_id

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
                self.id,
                role,
                content,
                prompt_tokens,
                completion_tokens,
                total_tokens,
                branch_id=self._active_branch_id,
            )
