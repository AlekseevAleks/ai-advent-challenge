"""Chat orchestration: persistence + LLM interaction."""

from __future__ import annotations

import asyncio
import re
from typing import AsyncIterator, Dict, List, Optional, Set, Tuple

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
        self._background_tasks: Set[asyncio.Task] = set()

    def _spawn_background(self, coro) -> None:
        """Run a coroutine in the background, keeping a strong reference.

        The step refresh must not delay the assistant's answer, so it is
        scheduled after the reply is delivered. The reference is kept until the
        task finishes, otherwise it could be garbage-collected mid-flight.
        """
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

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
        """Build the LLM context from the profile and all three memory layers.

        Layout: system instructions → user profile → long-term → working →
        short-term dialogue. Falls back to the plain transcript if the memory
        service is unavailable.
        """
        memory = self._memory()
        if memory is not None:
            try:
                # The prompt builder loads the ACTIVE profile on every
                # request, so a profile switch applies to the very next
                # message without a restart.
                memory.prompt_builder.log_request(chat_id)
                return memory.build_messages(
                    chat_id, history_limit=MAX_CONTEXT_MESSAGES
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

    def _sync_task_state(self, chat_id: str, user_text: str) -> None:
        """Handle the explicit pause/resume commands from the user's message.

        The stage itself is derived by the model in the same call that computes
        the step (see :meth:`_refresh_task_step`), so this method only reacts to
        the two commands the user states directly. Everything else is left to
        the extractor, which keeps the state from moving by accident.
        """
        memory = self._memory()
        if memory is None:
            return
        try:
            tasks = memory.tasks
            state = tasks.get_or_create(chat_id)
            data = state.data
            text = (user_text or "").strip().lower()

            # Explicit resume: restore the paused stage and step.
            if any(
                marker in text
                for marker in ("продолжить", "продолжи", "resume", "continue")
            ):
                if data.status == "paused":
                    tasks.resume(chat_id)
                return

            # Explicit pause. "пауза" covers "поставь задачу на паузу",
            # "на паузу", "pause" and similar phrasings.
            if any(marker in text for marker in ("пауза", "паузу", "pause")):
                tasks.pause(chat_id)
        except Exception:  # noqa: BLE001 - never break the chat
            logger.exception(
                "[TASK] Не удалось обработать команду состояния (чат %s)", chat_id
            )

    async def _check_invariants(
        self, chat_id: str, user_text: str
    ) -> Optional[Dict[str, object]]:
        """Check the request against the active invariants.

        Returns ``None`` when there is no conflict, or a payload describing the
        conflict so the caller can answer without asking the model for a
        solution that would violate a rule.

        When the user *explicitly* asks to change a rule, the change is applied
        here, through the manager, before the model answers. That way the
        assistant can never claim an update that did not happen.
        """
        memory = self._memory()
        if memory is None:
            return None
        try:
            result = await memory.check_invariants(user_text, task_id=chat_id)
        except Exception:  # noqa: BLE001 - never break the chat
            logger.exception("[INVARIANT] Проверка конфликтов не удалась (чат %s)", chat_id)
            return None

        # An explicit decision change is applied, not just reported.
        if result.explicit_change:
            applied = self._apply_invariant_change(memory, result, chat_id, user_text)
            if applied:
                return {
                    "conflicts": [],
                    "alternative": "",
                    "applied_change": applied,
                }

        if not result.has_conflict:
            return None

        logger.info(
            "[INVARIANT] Конфликт в чате %s: %s", chat_id, result.summary()
        )
        return {
            "conflicts": [
                {
                    "invariant_id": conflict.invariant_id,
                    "rule": conflict.rule,
                    "category": conflict.category,
                    "priority": conflict.priority,
                    "requested": conflict.requested,
                    "reason": conflict.reason,
                }
                for conflict in result.conflicts
            ],
            "alternative": result.alternative,
        }

    def _apply_invariant_change(
        self, memory, result, chat_id: str, user_text: str
    ) -> List[Dict[str, str]]:
        """Deactivate the rules the user asked to change and record the new one.

        The new rule text is taken from the user's own message, so the change
        reflects what was actually decided.
        """
        try:
            targets = memory.invariants.resolve_change_targets(
                result, task_id=chat_id
            )
            if not targets:
                return []

            new_rule = self._derive_new_rule(user_text, targets)
            applied: List[Dict[str, str]] = []
            for target in targets:
                memory.invariants.replace_rule(
                    old_invariant_id=target.id,
                    new_rule=new_rule,
                    description=f"Заменяет: {target.data.rule}",
                )
                applied.append(
                    {"old_rule": target.data.rule, "new_rule": new_rule}
                )
            logger.info(
                "[INVARIANT] Явное изменение решения в чате %s: %s",
                chat_id,
                "; ".join(
                    f"{item['old_rule']} → {item['new_rule']}" for item in applied
                ),
            )
            return applied
        except Exception:  # noqa: BLE001 - never break the chat
            logger.exception(
                "[INVARIANT] Не удалось применить изменение инварианта (чат %s)",
                chat_id,
            )
            return []

    #: Phrases that introduce the new decision, stripped from the rule text.
    _CHANGE_PREFIXES = (
        "мы приняли новое решение",
        "мы отменяем это ограничение",
        "мы отменяем ограничение",
        "отменяем это ограничение",
        "отменяем ограничение",
        "измени соответствующий инвариант",
        "измени инвариант",
        "обнови соответствующий инвариант",
        "обнови инвариант",
        "теперь",
    )

    @classmethod
    def _derive_new_rule(cls, user_text: str, targets: List[object]) -> str:
        """Build the new rule text from the user's message.

        The message is cleaned of the phrases that introduce the change, so the
        stored rule reads as a rule rather than as a sentence. When nothing
        usable remains, the old rule is kept with the change appended.
        """
        text = " ".join((user_text or "").split()).strip(" .!?")
        lowered = text.lower()

        # Drop the leading "we decided that…" style phrases.
        for prefix in cls._CHANGE_PREFIXES:
            if lowered.startswith(prefix):
                text = text[len(prefix) :].lstrip(" ,.:;—-")
                lowered = text.lower()

        # Drop a trailing instruction to update the invariant.
        for suffix in ("измени соответствующий инвариант", "измени инвариант",
                       "обнови соответствующий инвариант", "обнови инвариант"):
            if lowered.endswith(suffix):
                text = text[: -len(suffix)].rstrip(" ,.:;—-")
                lowered = text.lower()

        text = text.strip(" .!?")
        if 0 < len(text) <= 200:
            return text

        old_rule = targets[0].data.rule if targets else ""  # type: ignore[attr-defined]
        return f"{old_rule} (изменено: {text[:150]})"

    @staticmethod
    def _change_reply(payload: Dict[str, object]) -> str:
        """The answer given after an explicit invariant change was applied."""
        applied = payload.get("applied_change") or []
        lines = ["Инвариант обновлён по вашему явному решению.", ""]
        for item in applied:  # type: ignore[union-attr]
            lines.append(f"Деактивировано: «{item.get('old_rule', '')}»")
            lines.append(f"Активировано: «{item.get('new_rule', '')}»")
            lines.append("")
        lines.append(
            "Следующие запросы будут учитывать новое ограничение."
        )
        return "\n".join(lines)

    @staticmethod
    def _conflict_reply(payload: Dict[str, object]) -> str:
        """The answer given when a request violates an active invariant.

        The conflicting solution is not proposed; the violated rule is named
        explicitly and a compatible alternative is offered when one exists.
        """
        conflicts = payload.get("conflicts") or []
        lines = [
            "Я не могу предложить это решение: запрос конфликтует с активным "
            "инвариантом проекта.",
            "",
        ]
        for conflict in conflicts:  # type: ignore[union-attr]
            priority = str(conflict.get("priority", "")).upper()
            marker = f" [{priority}]" if priority == "CRITICAL" else ""
            lines.append(f"Нарушаемое ограничение{marker}:")
            lines.append(f"«{conflict.get('rule', '')}»")
            requested = conflict.get("requested")
            if requested:
                lines.append(f"Запрошено: «{requested}»")
            lines.append("")

        lines.append(
            "Я не буду менять это ограничение автоматически. Если решение "
            "действительно изменилось, скажите об этом явно — тогда я обновлю "
            "инвариант."
        )

        alternative = payload.get("alternative")
        if alternative:
            lines.append("")
            lines.append(f"Совместимая альтернатива: {alternative}")

        return "\n".join(lines)

    async def _check_transition_gate(
        self, chat_id: str, user_text: str
    ) -> Optional[Dict[str, object]]:
        """Decide whether the request may run, given the task lifecycle.

        When a task is active, the transition the request would cause is
        determined *before* the request is executed and checked against the
        configured rules:

        * the request does not move the task, or there is nothing to gate —
          returns ``None`` and the request runs normally;
        * the move is allowed — the stage is advanced and ``None`` is returned,
          so the request runs;
        * the move is forbidden — returns a payload describing the refusal, so
          the caller answers with it and **does not execute the request**.
        """
        memory = self._memory()
        if memory is None:
            return None
        try:
            outcome = await memory.check_transition_gate(chat_id, user_text)
        except Exception:  # noqa: BLE001 - never break the chat
            logger.exception(
                "[TRANSITION] Проверка перехода перед запросом не удалась (чат %s)",
                chat_id,
            )
            return None

        if outcome is None or outcome.allowed:
            if outcome is not None:
                logger.info(
                    "[TRANSITION] Запрос разрешён, переход '%s': %s → %s",
                    chat_id,
                    outcome.from_state,
                    outcome.to_state,
                )
            return None

        logger.info(
            "[TRANSITION] Запрос заблокирован в чате %s: %s → %s (%s)",
            chat_id,
            outcome.from_state,
            outcome.to_state,
            outcome.reason,
        )
        return {
            "from_state": outcome.from_state,
            "to_state": outcome.to_state,
            "reason": outcome.reason,
            "required_condition": outcome.required_condition,
            "actual": outcome.actual,
            "required_field": outcome.required_field,
            "field_is_set": outcome.field_is_set,
        }

    @staticmethod
    def _transition_blocked_reply(payload: Dict[str, object]) -> str:
        """The answer given when a request would break the lifecycle.

        The request is not executed: the assistant explains which transition it
        would require and why that transition is not allowed.
        """
        from_state = str(payload.get("from_state") or "")
        to_state = str(payload.get("to_state") or "")
        lines = [
            "Я не могу выполнить этот запрос: он требует перехода, который "
            "запрещён правилами жизненного цикла задачи.",
            "",
            f"Запрошенный переход: {from_state} → {to_state}",
        ]

        required = payload.get("required_condition")
        if required:
            lines.append(f"Требуемое условие: {required}")

        field = str(payload.get("required_field") or "")
        is_set = payload.get("field_is_set", True)
        if field and not is_set:
            # The condition reads a fact the task does not carry, so it can
            # never hold. Saying "current value: (empty)" would be misleading:
            # the user has to set the fact first.
            lines.append(
                f"Факт «{field}» у задачи не задан, поэтому условие не может "
                f"выполниться."
            )
        else:
            actual = payload.get("actual")
            if actual:
                lines.append(f"Текущее значение: {actual}")

        reason = payload.get("reason")
        if reason and not required:
            lines.append(f"Причина: {reason}")

        lines.append("")
        if field and not is_set:
            lines.append(
                "Состояние задачи не изменено, запрос не выполнен. Укажите "
                f"факт «{field}» в блоке Task state (кнопка «Изменить факты») "
                "или измените правила на странице Task State Rules."
            )
        else:
            lines.append(
                "Состояние задачи не изменено, запрос не выполнен. Выполните "
                "условие перехода или измените правила на странице Task State Rules."
            )
        return "\n".join(lines)

    async def _refresh_task_step(self, chat_id: str) -> None:
        """Recompute the task step in the background after an exchange.

        Failures are logged and swallowed: the step is a convenience, not a
        prerequisite for answering.
        """
        memory = self._memory()
        if memory is None:
            return
        try:
            await memory.refresh_task_step(chat_id)
        except Exception:  # noqa: BLE001 - never break the chat
            logger.exception("[TASK] Фоновый пересчёт шага не удался (чат %s)", chat_id)

    async def _detect_transition(self, chat_id: str) -> None:
        """Let the model propose a transition, then let the manager decide.

        The AI is allowed to notice that the task has moved on; it is not
        allowed to perform the move. The proposal goes through
        ``TransitionManager``, which loads the user's rules from the database
        and either applies the transition or refuses it. A refusal is logged
        and the stage is left untouched.
        """
        memory = self._memory()
        if memory is None:
            return
        try:
            outcome = await memory.detect_transition(chat_id)
        except Exception:  # noqa: BLE001 - never break the chat
            logger.exception(
                "[TRANSITION] Определение перехода не удалось (чат %s)", chat_id
            )
            return
        if outcome is None:
            return
        if outcome.allowed:
            logger.info(
                "[TRANSITION] AI инициировал переход '%s': %s → %s",
                chat_id,
                outcome.from_state,
                outcome.to_state,
            )
        else:
            logger.info(
                "[TRANSITION] AI предложил переход '%s', но он отклонён: %s",
                chat_id,
                outcome.reason,
            )

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

        # Invariants are checked before the model is asked for a solution, so a
        # violating request is answered with the conflict instead.
        conflict = await self._check_invariants(chat_id, content)
        # The lifecycle is checked next: a request that would require a
        # forbidden transition is not executed at all.
        blocked = (
            None
            if conflict is not None
            else await self._check_transition_gate(chat_id, content)
        )
        if conflict is not None and conflict.get("applied_change"):
            reply_text = self._change_reply(conflict)
        elif conflict is not None:
            reply_text = self._conflict_reply(conflict)
        elif blocked is not None:
            reply_text = self._transition_blocked_reply(blocked)
        else:
            context = self._build_context(chat_id)
            reply_text = await ai.complete(chat.model, context)

        assistant_message = self.messages.add(chat_id, "assistant", reply_text)
        chat = self.chats.touch(chat_id) or chat

        await self._analyze_memory(chat_id, content, reply_text)
        self._sync_task_state(chat_id, content)
        # The step is derived from the dialogue, so it is computed after the
        # reply exists — in the background, so the response is not delayed.
        self._spawn_background(self._refresh_task_step(chat_id))
        # The AI may decide that the task has moved on. The proposal goes
        # through TransitionManager, which applies the user's rules.
        self._spawn_background(self._detect_transition(chat_id))

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

        # Invariants are checked before the model is asked for a solution. A
        # conflicting request is answered with the conflict itself, streamed
        # like any other reply so the UI needs no special case.
        conflict = await self._check_invariants(chat_id, content)
        # The lifecycle is checked next: a request that would require a
        # forbidden transition is not executed at all.
        blocked = (
            None
            if conflict is not None
            else await self._check_transition_gate(chat_id, content)
        )
        if conflict is not None or blocked is not None:
            if conflict is not None:
                text = (
                    self._change_reply(conflict)
                    if conflict.get("applied_change")
                    else self._conflict_reply(conflict)
                )
            else:
                text = self._transition_blocked_reply(blocked)
            for chunk in text.split(" "):
                yield "delta", f"{chunk} "
            assistant_message = self.messages.add(chat_id, "assistant", text)
            self.chats.touch(chat_id)
            await self._analyze_memory(chat_id, content, text)
            self._sync_task_state(chat_id, content)
            self._spawn_background(self._refresh_task_step(chat_id))
            self._spawn_background(self._detect_transition(chat_id))
            yield "done", assistant_message
            return

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
        self._sync_task_state(chat_id, content)
        self._spawn_background(self._refresh_task_step(chat_id))
        self._spawn_background(self._detect_transition(chat_id))
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