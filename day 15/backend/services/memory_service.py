"""Service layer for the agent memory model.

Wraps :class:`~backend.memory.manager.MemoryManager` with the pieces that need
application context: the configured AI client (for LLM-based extraction) and
chat existence checks.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from backend.database.memory_repositories import (
    LongTermMemoryRepository,
    WorkingMemoryRepository,
)
from backend.database.invariant_repository import InvariantRepository
from backend.database.profile_repository import UserProfileRepository
from backend.database.repositories import ChatRepository, MessageRepository
from backend.database.task_repository import TaskStateRepository
from backend.database.transition_repository import (
    TaskStateDefinitionRepository,
    TransitionHistoryRepository,
    TransitionRuleRepository,
)
from backend.invariants.detector import InvariantConflictDetector
from backend.invariants.manager import InvariantManager
from backend.invariants.models import (
    ConflictCheckResult,
    Invariant,
    InvariantCreate,
    InvariantList,
    InvariantUpdate,
)
from backend.memory.extractor import MemoryExtractor
from backend.memory.long_term import LongTermMemory
from backend.memory.manager import MemoryManager
from backend.memory.models import (
    LongTermCreate,
    LongTermEntry,
    LongTermMemory as LongTermMemoryModel,
    LongTermUpdate,
    MemoryAnalysisReport,
    MemoryOverview,
    ShortTermMemory as ShortTermMemoryModel,
    WorkingMemory as WorkingMemoryModel,
    WorkingMemoryData,
    WorkingMemoryUpdate,
)
from backend.memory.short_term import ShortTermMemory
from backend.memory.working import WorkingMemory
from backend.profile.manager import ProfileManager
from backend.profile.models import (
    ProfileDuplicateRequest,
    UserProfile,
    UserProfileCreate,
    UserProfileList,
    UserProfilePatch,
    UserProfileUpdate,
)
from backend.services.ai_client import AIClient, build_client_from_settings
from backend.services.prompt_builder import PromptBuilder
from backend.tasks.extractor import TaskStepExtractor
from backend.tasks.manager import TaskStateManager
from backend.tasks.models import (
    TaskPauseRequest,
    TaskState,
    TaskStateCreate,
    TaskStateUpdate,
    TaskStepSuggestion,
    TaskTransitionRequest,
)
from backend.transitions.detector import TransitionDetector
from backend.transitions.facts import FactExtractor
from backend.transitions.manager import TransitionManager
from backend.transitions.models import (
    AvailableTransitions,
    TaskFacts,
    TaskStateDefinition,
    TaskStateDefinitionCreate,
    TaskStateDefinitionList,
    TaskStateDefinitionUpdate,
    TransitionHistoryEntry,
    TransitionOutcome,
    TransitionRule,
    TransitionRuleCreate,
    TransitionRuleUpdate,
    TransitionSuggestion,
)
from backend.utils.errors import NotFoundError
from backend.utils.logging_config import get_logger

logger = get_logger(__name__)


class MemoryService:
    """Application-facing API for the three memory layers."""

    def __init__(
        self,
        *,
        chats: Optional[ChatRepository] = None,
        messages: Optional[MessageRepository] = None,
        working_repo: Optional[WorkingMemoryRepository] = None,
        long_term_repo: Optional[LongTermMemoryRepository] = None,
        profile_repo: Optional[UserProfileRepository] = None,
        task_repo: Optional[TaskStateRepository] = None,
        invariant_repo: Optional[InvariantRepository] = None,
        state_repo: Optional[TaskStateDefinitionRepository] = None,
        rule_repo: Optional[TransitionRuleRepository] = None,
        history_repo: Optional[TransitionHistoryRepository] = None,
        manager: Optional[MemoryManager] = None,
        profile_manager: Optional[ProfileManager] = None,
        task_manager: Optional[TaskStateManager] = None,
        invariant_manager: Optional[InvariantManager] = None,
        transition_manager: Optional[TransitionManager] = None,
    ) -> None:
        self.chats = chats or ChatRepository()
        self._manager = manager or MemoryManager(
            short_term=ShortTermMemory(messages or MessageRepository()),
            working=WorkingMemory(working_repo or WorkingMemoryRepository()),
            long_term=LongTermMemory(long_term_repo or LongTermMemoryRepository()),
        )
        self.profile = profile_manager or ProfileManager(
            profile_repo or UserProfileRepository()
        )
        self.tasks = task_manager or TaskStateManager(
            task_repo or TaskStateRepository()
        )
        self.invariants = invariant_manager or InvariantManager(
            invariant_repo or InvariantRepository()
        )
        # The lifecycle layer owns the vocabulary of states and the rules
        # between them; the task manager only knows how to store a position.
        self.transitions = transition_manager or TransitionManager(
            states=state_repo or TaskStateDefinitionRepository(),
            rules=rule_repo or TransitionRuleRepository(),
            history=history_repo or TransitionHistoryRepository(),
            tasks=self.tasks,
        )
        self.prompt_builder = PromptBuilder(
            memory=self._manager,
            profile=self.profile,
            tasks=self.tasks,
            invariants=self.invariants,
            transitions=self.transitions,
        )

    @property
    def manager(self) -> MemoryManager:
        return self._manager

    # ------------------------------------------------------------- read API
    def _ensure_chat(self, chat_id: str) -> None:
        if self.chats.get(chat_id) is None:
            raise NotFoundError("Чат не найден.")

    def get_short_term(self, chat_id: str) -> ShortTermMemoryModel:
        self._ensure_chat(chat_id)
        return self._manager.get_short_term_memory(chat_id)

    def get_working(self, chat_id: str) -> WorkingMemoryModel:
        self._ensure_chat(chat_id)
        return self._manager.get_working_memory(chat_id)

    def get_long_term(self) -> LongTermMemoryModel:
        return self._manager.get_long_term_memory()

    def get_overview(self, chat_id: Optional[str] = None) -> MemoryOverview:
        if chat_id is not None:
            self._ensure_chat(chat_id)
        return self._manager.get_overview(chat_id)

    # ------------------------------------------------------------ write API
    def replace_working(
        self, chat_id: str, payload: WorkingMemoryUpdate
    ) -> WorkingMemoryModel:
        self._ensure_chat(chat_id)
        return self._manager.replace_working_memory(chat_id, payload.data)

    def clear_working(self, chat_id: str) -> None:
        self._ensure_chat(chat_id)
        self._manager.clear_working_memory(chat_id)

    def create_long_term(self, payload: LongTermCreate) -> LongTermEntry:
        return self._manager.save_to_long_term(
            category=payload.category,
            key=payload.key,
            value=payload.value,
            source=payload.source,
            confidence=payload.confidence,
        )

    def update_long_term(
        self, memory_id: str, payload: LongTermUpdate
    ) -> LongTermEntry:
        entry = self._manager.update_long_term(
            memory_id,
            category=payload.category,
            key=payload.key,
            value=payload.value,
            confidence=payload.confidence,
        )
        if entry is None:
            raise NotFoundError("Запись долговременной памяти не найдена.")
        return entry

    def delete_long_term(self, memory_id: str) -> None:
        if not self._manager.forget_long_term(memory_id):
            raise NotFoundError("Запись долговременной памяти не найдена.")

    # -------------------------------------------------------------- analysis
    def _extraction_client(self) -> Optional[AIClient]:
        """Build a client for extraction, or ``None`` to use rule-based fallback."""
        try:
            client = build_client_from_settings()
        except Exception:  # noqa: BLE001 - extraction must never break the chat
            return None
        if not client.base_url:
            return None
        return client

    async def analyze(
        self,
        chat_id: str,
        *,
        user_message: str,
        assistant_message: str = "",
        persist: bool = True,
    ) -> MemoryAnalysisReport:
        """Run the extraction pipeline for one exchange."""
        chat = self.chats.get(chat_id)
        if chat is None:
            raise NotFoundError("Чат не найден.")
        # Extraction uses the same model as the chat it analyses.
        self._manager.extractor = MemoryExtractor(
            self._extraction_client(), model=chat.model
        )
        return await self._manager.analyze(
            chat_id,
            user_message,
            assistant_message=assistant_message,
            persist=persist,
        )

    async def analyze_last_exchange(self, chat_id: str) -> MemoryAnalysisReport:
        """Re-analyse the most recent user message of a chat."""
        self._ensure_chat(chat_id)
        history = self._manager.short_term.get(chat_id)
        user_entries = [entry for entry in history.entries if entry.role == "user"]
        if not user_entries:
            raise NotFoundError("В чате нет сообщений пользователя для анализа.")
        last_user = user_entries[-1]
        assistant_text = ""
        for entry in reversed(history.entries):
            if entry.role == "assistant":
                assistant_text = entry.content
                break
        return await self.analyze(
            chat_id,
            user_message=last_user.content,
            assistant_message=assistant_text,
        )

    # ------------------------------------------------------------- lifecycle
    def on_chat_deleted(self, chat_id: str) -> None:
        self._manager.on_chat_deleted(chat_id)
        self.tasks.on_chat_deleted(chat_id)
        # Task-scoped invariants belong to the task; global ones are kept.
        self.invariants.on_task_deleted(chat_id)
        # The transition history of the task goes with it; the configured
        # lifecycle itself is global and is kept.
        self.transitions.on_task_deleted(chat_id)

    def build_messages(
        self,
        chat_id: str,
        *,
        history_limit: Optional[int] = None,
        profile_id: Optional[str] = None,
    ) -> list:
        """Full request context: system + profile + memory + dialogue."""
        return self.prompt_builder.build_messages(
            chat_id, profile_id=profile_id, history_limit=history_limit
        )

    def build_prompt_context(self, chat_id: str) -> str:
        return self._manager.build_prompt_context(chat_id)

    # --------------------------------------------------------------- profile
    def get_profile(self, profile_id: Optional[str] = None) -> UserProfile:
        """One profile; without an id, the active one."""
        return self.profile.get(profile_id)

    def get_active_profile(self) -> UserProfile:
        return self.profile.get(self.profile.get_active_profile_id())

    def list_profiles(self) -> UserProfileList:
        return self.profile.list_response()

    def create_profile(self, payload: UserProfileCreate) -> UserProfile:
        return self.profile.create(payload)

    def update_profile(
        self, profile_id: str, payload: UserProfilePatch
    ) -> UserProfile:
        return self.profile.update(profile_id, payload)

    def delete_profile(self, profile_id: str) -> None:
        self.profile.delete(profile_id)

    def duplicate_profile(
        self,
        profile_id: str,
        payload: Optional[ProfileDuplicateRequest] = None,
    ) -> UserProfile:
        return self.profile.duplicate(profile_id, payload)

    def activate_profile(self, profile_id: str) -> UserProfile:
        return self.profile.activate(profile_id)

    def save_profile(
        self, payload: UserProfileUpdate, profile_id: Optional[str] = None
    ) -> UserProfile:
        """Backwards-compatible single-profile save (used by the old UI)."""
        resolved = profile_id or self.profile.get_active_profile_id()
        patch = UserProfilePatch(data=payload.data)
        if self.profile._repo.exists(resolved):
            return self.profile.update(resolved, patch)
        return self.profile.create(
            UserProfileCreate(
                name=payload.data.name or resolved,
                description=payload.data.description,
                data=payload.data,
            )
        )

    def reset_profile(self, profile_id: Optional[str] = None) -> UserProfile:
        return self.profile.reset(profile_id)

    def profile_prompt_block(self, profile_id: Optional[str] = None) -> str:
        return self.profile.build_prompt_block(profile_id)

    def working_data(self, chat_id: str) -> WorkingMemoryData:
        return self._manager.working.get_data(chat_id)

    # ------------------------------------------------------------ task state
    def get_task_state(self, task_id: str) -> TaskState:
        return self.tasks.get_state(task_id)

    def ensure_task_state(self, task_id: str) -> TaskState:
        """Return the state, creating a ``planning`` one when absent."""
        return self.tasks.get_or_create(task_id)

    def create_task_state(
        self, task_id: str, payload: Optional[TaskStateCreate] = None
    ) -> TaskState:
        return self.tasks.create_state(task_id, payload=payload)

    def update_task_state(self, task_id: str, payload: TaskStateUpdate) -> TaskState:
        return self.tasks.apply_update(task_id, payload)

    def transition_task(
        self, task_id: str, payload: TaskTransitionRequest
    ) -> TaskState:
        return self.tasks.apply_transition(task_id, payload)

    def pause_task(
        self, task_id: str, payload: Optional[TaskPauseRequest] = None
    ) -> TaskState:
        return self.tasks.pause(task_id, payload)

    def resume_task(self, task_id: str) -> TaskState:
        return self.tasks.resume(task_id)

    def complete_task(self, task_id: str) -> TaskState:
        return self.tasks.complete(task_id)

    def task_prompt_block(self, task_id: str) -> str:
        return self.tasks.build_prompt_block(task_id)

    # ------------------------------------------------------- transition rules
    def list_task_states(self) -> TaskStateDefinitionList:
        return self.transitions.states_response()

    def get_task_state_definition(self, state_id: str) -> TaskStateDefinition:
        return self.transitions.get_state(state_id)

    def create_task_state_definition(
        self, payload: TaskStateDefinitionCreate
    ) -> TaskStateDefinition:
        return self.transitions.create_state(payload)

    def update_task_state_definition(
        self, state_id: str, payload: TaskStateDefinitionUpdate
    ) -> TaskStateDefinition:
        return self.transitions.update_state(state_id, payload)

    def delete_task_state_definition(self, state_id: str) -> None:
        self.transitions.delete_state(state_id)

    def list_transition_rules(self, *, active_only: bool = False) -> List[TransitionRule]:
        return self.transitions.list_rules(active_only=active_only)

    def get_transition_rule(self, rule_id: str) -> TransitionRule:
        return self.transitions.get_rule(rule_id)

    def create_transition_rule(self, payload: TransitionRuleCreate) -> TransitionRule:
        return self.transitions.create_rule(payload)

    def update_transition_rule(
        self, rule_id: str, payload: TransitionRuleUpdate
    ) -> TransitionRule:
        return self.transitions.update_rule(rule_id, payload)

    def delete_transition_rule(self, rule_id: str) -> None:
        self.transitions.delete_rule(rule_id)

    def activate_transition_rule(self, rule_id: str) -> TransitionRule:
        return self.transitions.activate_rule(rule_id)

    def deactivate_transition_rule(self, rule_id: str) -> TransitionRule:
        return self.transitions.deactivate_rule(rule_id)

    def check_transition_rule(
        self, rule_id: str, facts: Optional[dict] = None
    ) -> dict:
        return self.transitions.check_rule(rule_id, facts)

    def available_transitions(self, task_id: str) -> AvailableTransitions:
        return self.transitions.get_available_transitions(task_id)

    def transition_task_to(
        self,
        task_id: str,
        target_stage: str,
        *,
        reason: str = "",
        trigger: str = "user",
        current_step: Optional[str] = None,
        expected_action: Optional[str] = None,
    ) -> TransitionOutcome:
        return self.transitions.transition(
            task_id,
            target_stage,
            reason=reason,
            trigger=trigger,
            current_step=current_step,
            expected_action=expected_action,
        )

    def transition_history(
        self, task_id: str, *, limit: int = 50
    ) -> List[TransitionHistoryEntry]:
        return self.transitions.history(task_id, limit=limit)

    def transition_prompt_block(self, task_id: str) -> str:
        return self.transitions.build_prompt_block(task_id)

    def task_facts(self, task_id: str) -> TaskFacts:
        """The facts conditions are checked against, plus the missing ones."""
        return self.transitions.facts_response(task_id)

    def set_task_facts(self, task_id: str, facts: dict) -> TaskFacts:
        """Set the task's own facts (its metadata)."""
        return self.transitions.set_facts(task_id, facts)

    async def detect_transition(
        self, task_id: str, *, history_limit: int = 10
    ) -> Optional[TransitionOutcome]:
        """Let the model propose a transition, then let the manager decide.

        The model only says *which* move it considers necessary; whether the
        move happens is decided by the configured rules. A rejected proposal is
        returned as an outcome with ``allowed=False`` so the caller can explain
        it to the user.
        """
        available = self.transitions.get_available_transitions(task_id)
        if not available.transitions:
            return None

        client = self._extraction_client()
        if client is None:
            return None

        chat = self.chats.get(task_id)
        model = chat.model if chat else None
        if not model:
            return None

        history = [
            {"role": entry.role, "content": entry.content}
            for entry in self._manager.short_term.get(
                task_id, limit=history_limit
            ).entries
        ]

        detector = TransitionDetector(client, model=model)
        suggestion: TransitionSuggestion = await detector.detect(
            stage=available.stage,
            available=[
                {
                    "from_state": item.from_state,
                    "to_state": item.to_state,
                    "condition": item.condition,
                }
                for item in available.transitions
            ],
            history=history,
        )

        if not TransitionDetector.is_usable(suggestion):
            logger.debug(
                "[TRANSITION] Предложение перехода отклонено "
                "(confidence %.2f, source %s)",
                suggestion.confidence,
                suggestion.source,
            )
            return None

        return self.transitions.apply_suggestion(task_id, suggestion)

    async def check_transition_gate(
        self, task_id: str, request: str, *, history_limit: int = 10
    ) -> Optional[TransitionOutcome]:
        """Decide whether a request may be executed, given the lifecycle.

        This is the pre-flight check. The model is asked which state the task
        will be in *after* the request is carried out; the answer is then
        validated against the configured rules. The outcome tells the caller
        whether the request may run:

        * ``None`` — there is nothing to gate (no task, no rules, no model, or
          the request does not move the task), so the request runs normally;
        * ``allowed=True`` — the move is permitted, so the request runs and the
          stage is advanced;
        * ``allowed=False`` — the move is forbidden, so the request must **not**
          be executed and the reason is reported to the user.

        The stage is only changed when the move is allowed; a refusal leaves the
        task exactly where it was and is recorded in the history.
        """
        state = self.tasks.get_state(task_id)
        if not state.exists:
            return None

        available = self.transitions.get_available_transitions(task_id)
        if not available.transitions:
            return None

        client = self._extraction_client()
        if client is None:
            return None

        chat = self.chats.get(task_id)
        model = chat.model if chat else None
        if not model:
            return None

        history = [
            {"role": entry.role, "content": entry.content}
            for entry in self._manager.short_term.get(
                task_id, limit=history_limit
            ).entries
        ]

        # The facts the rules read are taken from the user's own message first:
        # "план утверждён" *is* the value of plan_status, so asking the user to
        # type it by hand would be busywork. Extraction only fills fields the
        # rules reference, and never the machine position.
        await self.extract_facts(task_id, request, history=history)

        detector = TransitionDetector(client, model=model)
        suggestion: TransitionSuggestion = await detector.detect_for_request(
            stage=available.stage,
            available=[
                {
                    "from_state": item.from_state,
                    "to_state": item.to_state,
                    "condition": item.condition,
                }
                for item in available.transitions
            ],
            request=request,
            history=history,
        )

        if not TransitionDetector.is_usable(suggestion):
            logger.debug(
                "[TRANSITION] Запрос не меняет состояние задачи "
                "(confidence %.2f, source %s)",
                suggestion.confidence,
                suggestion.source,
            )
            return None

        # The proposal is only a request: the manager decides, using the rules.
        return self.transitions.transition(
            task_id,
            suggestion.to_state,
            reason=suggestion.reason or "переход определён по запросу пользователя",
            trigger="ai_detected",
        )

    async def extract_facts(
        self,
        task_id: str,
        request: str,
        *,
        history: Optional[List[dict]] = None,
        history_limit: int = 8,
    ) -> Dict[str, str]:
        """Read the fact values the rules need out of the user's message.

        Only the fields the active rules reference are requested, and only
        those are accepted back, so the model cannot add facts of its own. The
        machine position is never touched. Returns the values that were stored.
        """
        fields = self.transitions.required_fields()
        if not fields:
            return {}

        client = self._extraction_client()
        if client is None:
            return {}

        chat = self.chats.get(task_id)
        model = chat.model if chat else None
        if not model:
            return {}

        if history is None:
            history = [
                {"role": entry.role, "content": entry.content}
                for entry in self._manager.short_term.get(
                    task_id, limit=history_limit
                ).entries
            ]

        current = self.transitions.facts_for(task_id)
        extractor = FactExtractor(client, model=model)
        proposed = await extractor.extract(
            request=request,
            fields=fields,
            current=current,
            history=history,
        )
        if not proposed:
            return {}

        # Only the fields the rules read are accepted, and the machine position
        # is refused outright.
        before = dict(current)
        self.transitions.set_facts(
            task_id, proposed, only_required=True, extracted=True
        )
        applied = {
            name: value
            for name, value in proposed.items()
            if before.get(name) != value
        }
        if applied:
            logger.info(
                "[FACT] Из сообщения извлечены факты задачи '%s': %s",
                task_id,
                ", ".join(f"{k}={v}" for k, v in sorted(applied.items())),
            )
        return applied

    # ------------------------------------------------------------ invariants
    def get_invariant(self, invariant_id: str) -> Invariant:
        return self.invariants.get(invariant_id)

    def list_invariants(
        self,
        *,
        scope: Optional[str] = None,
        task_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> InvariantList:
        return InvariantList(
            invariants=self.invariants.list_invariants(
                scope=scope, task_id=task_id, status=status
            )
        )

    def list_active_invariants(self, task_id: Optional[str] = None) -> InvariantList:
        return InvariantList(invariants=self.invariants.list_active(task_id))

    def create_invariant(self, payload: InvariantCreate) -> Invariant:
        return self.invariants.create_invariant(payload)

    def update_invariant(
        self, invariant_id: str, payload: InvariantUpdate
    ) -> Invariant:
        return self.invariants.update_invariant(invariant_id, payload)

    def delete_invariant(self, invariant_id: str) -> None:
        self.invariants.delete_invariant(invariant_id)

    def activate_invariant(self, invariant_id: str) -> Invariant:
        return self.invariants.activate_invariant(invariant_id)

    def deactivate_invariant(self, invariant_id: str) -> Invariant:
        return self.invariants.deactivate_invariant(invariant_id)

    def invariant_prompt_block(self, task_id: Optional[str] = None) -> str:
        return self.invariants.build_prompt_block(task_id)

    async def check_invariants(
        self, request: str, *, task_id: Optional[str] = None
    ) -> ConflictCheckResult:
        """Check a request against the active invariants.

        The detector proposes conflicts; the manager validates them, so a rule
        the model invented is never reported.
        """
        active = self.invariants.list_active(task_id)
        if not active:
            return ConflictCheckResult(has_conflict=False, source="no-invariants")

        client = self._extraction_client()
        if client is None:
            return ConflictCheckResult(has_conflict=False, source="unavailable")

        # The check may run without a chat (the /check endpoint), so fall back
        # to the model of the most recent chat when there is no task context.
        model = None
        if task_id:
            chat = self.chats.get(task_id)
            model = chat.model if chat else None
        if not model:
            chats = self.chats.list()
            model = chats[0].model if chats else None
        if not model:
            return ConflictCheckResult(has_conflict=False, source="unavailable")

        history = []
        if task_id:
            history = [
                {"role": entry.role, "content": entry.content}
                for entry in self._manager.short_term.get(task_id, limit=6).entries
            ]

        detector = InvariantConflictDetector(client, model=model)
        proposal = await detector.check(request, active, history=history)
        return self.invariants.check_conflict(
            request, task_id=task_id, result=proposal
        )

    def apply_invariant_change(
        self,
        result: ConflictCheckResult,
        *,
        new_rule: str,
        task_id: Optional[str] = None,
    ) -> List[Invariant]:
        """Apply an explicit decision change requested by the user.

        Deactivates the rules the user asked to change and activates the new
        one. Only called when the user explicitly requested the change.
        """
        targets = self.invariants.resolve_change_targets(result, task_id=task_id)
        created: List[Invariant] = []
        for target in targets:
            created.append(
                self.invariants.replace_rule(
                    old_invariant_id=target.id,
                    new_rule=new_rule,
                    description=f"Заменяет: {target.data.rule}",
                )
            )
        return created

    async def refresh_task_step(
        self, task_id: str, *, history_limit: int = 12
    ) -> Optional[TaskState]:
        """Recompute the whole task state from the dialogue in one call.

        A single model call returns the stage together with ``current_step``
        and ``expected_action``, so the three fields stay consistent. Runs in
        the background after the assistant has answered. Returns ``None`` when
        the model is unavailable or the suggestion is not usable.
        """
        state = self.tasks.get_or_create(task_id)
        data = state.data

        client = self._extraction_client()
        if client is None:
            logger.debug("[TASK] Шаг не пересчитан: API не настроен")
            return None

        chat = self.chats.get(task_id)
        model = chat.model if chat else None
        if not model:
            return None

        history = [
            {"role": entry.role, "content": entry.content}
            for entry in self._manager.short_term.get(
                task_id, limit=history_limit
            ).entries
        ]

        extractor = TaskStepExtractor(client, model=model)
        suggestion: TaskStepSuggestion = await extractor.extract(
            stage=data.stage,
            current_step=data.current_step,
            expected_action=data.expected_action,
            history=history,
        )

        if not TaskStepExtractor.is_usable(suggestion):
            logger.debug(
                "[TASK] Предложение шага отклонено (confidence %.2f, source %s)",
                suggestion.confidence,
                suggestion.source,
            )
            return None

        # Only the descriptive fields are applied here. The stage is decided by
        # the pre-flight gate, which runs *before* a request is executed and
        # checks it against the rules; letting this background pass move the
        # stage as well would give the task a second, unchecked way to advance.
        if suggestion.stage and suggestion.stage != data.stage:
            logger.debug(
                "[TASK] Предложенный этап %s не применяется: этап меняет "
                "только TransitionManager по запросу пользователя",
                suggestion.stage,
            )

        return self.tasks.apply_step_suggestion(task_id, suggestion)