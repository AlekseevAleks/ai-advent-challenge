"""TransitionManager — the only way a task changes stage.

The division of labour is the point of this layer:

```
AI decides that a transition is needed
        ↓
TransitionManager
        ↓
loads the rules from the database
        ↓
checks the conditions
        ↓
allowed  → the stage changes
rejected → the stage does not change
```

The model is free to *propose* a move; it is never free to bypass a rule. Every
attempt — accepted or rejected — is written to ``task_state_transitions``, so
the lifecycle is auditable.

The manager owns four invariants:

* the vocabulary of states lives in the database, not in code;
* a move is allowed only when an **active** rule exists for that exact edge and
  every one of its conditions holds;
* the lifecycle stays valid: at most one initial state, at least one final
  state, no rule pointing at a state that does not exist, no duplicate edge;
* a state that is still referenced by a rule cannot be deleted.
"""

from __future__ import annotations

import re
import uuid
from typing import Dict, List, Optional, Tuple

from backend.database.transition_repository import (
    TaskStateDefinitionRepository,
    TransitionHistoryRepository,
    TransitionRuleRepository,
)
from backend.tasks.manager import TaskStateManager
from backend.tasks.models import STAGE_LABELS, TaskState
from backend.transitions.conditions import evaluate_conditions, first_failure
from backend.transitions.models import (
    DEFAULT_STATE_NAMES,
    DEFAULT_TRANSITIONS,
    AvailableTransition,
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
from backend.utils.errors import AppError, NotFoundError
from backend.utils.logging_config import get_logger

logger = get_logger(__name__)

#: How many history entries are returned by default.
DEFAULT_HISTORY_LIMIT = 50


class InvalidRuleError(AppError):
    """Raised when a rule would make the lifecycle invalid."""

    status_code = 422
    code = "invalid_rule"
    default_message = "Некорректное правило перехода."


class DuplicateRuleError(AppError):
    """Raised when the same edge is configured twice."""

    status_code = 409
    code = "duplicate_rule"
    default_message = "Правило для этого перехода уже существует."


class StateInUseError(AppError):
    """Raised when a state is still referenced by a rule."""

    status_code = 409
    code = "state_in_use"
    default_message = (
        "Состояние используется правилами переходов. Сначала удалите или "
        "измените эти правила."
    )


class TransitionRejectedError(AppError):
    """Raised when an explicit transition is not allowed."""

    status_code = 409
    code = "transition_rejected"
    default_message = "Переход отклонён правилами жизненного цикла."


def _slugify(value: str) -> str:
    """Turn a state name into a stable, url-safe id."""
    translit = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
        "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
        "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
        "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    }
    lowered = (value or "").strip().lower()
    converted = "".join(translit.get(char, char) for char in lowered)
    slug = re.sub(r"[^a-z0-9]+", "_", converted).strip("_")
    return slug or "state"


class TransitionManager:
    """Reads and writes the lifecycle, and validates every move."""

    def __init__(
        self,
        *,
        states: Optional[TaskStateDefinitionRepository] = None,
        rules: Optional[TransitionRuleRepository] = None,
        history: Optional[TransitionHistoryRepository] = None,
        tasks: Optional[TaskStateManager] = None,
    ) -> None:
        self._states = states or TaskStateDefinitionRepository()
        self._rules = rules or TransitionRuleRepository()
        self._history = history or TransitionHistoryRepository()
        self._tasks = tasks or TaskStateManager()

    # ------------------------------------------------------------ bootstrap
    def ensure_initialized(self) -> None:
        """Seed the built-in lifecycle once, so the machine works out of the box.

        Called on every read, so a fresh database (or one where the user
        removed everything) self-heals. Existing configuration is never
        overwritten: the seed only runs when there is nothing at all.
        """
        if self._states.count() == 0:
            for index, name in enumerate(DEFAULT_STATE_NAMES):
                self._states.save(
                    TaskStateDefinition(
                        id=name,
                        name=name.capitalize(),
                        description="",
                        is_initial=index == 0,
                        is_final=index == len(DEFAULT_STATE_NAMES) - 1,
                        active=True,
                        position=index,
                    )
                )
            logger.info(
                "[TRANSITION] Создан жизненный цикл по умолчанию: %s",
                ", ".join(DEFAULT_STATE_NAMES),
            )

        if self._rules.count() == 0:
            for from_state, to_state, name, condition in DEFAULT_TRANSITIONS:
                if not self._states.exists(from_state) or not self._states.exists(
                    to_state
                ):
                    continue
                self._rules.save(
                    TransitionRule(
                        id=str(uuid.uuid4()),
                        from_state=from_state,
                        to_state=to_state,
                        name=name,
                        description="",
                        condition=condition,
                        conditions=[],
                        active=True,
                    )
                )
            logger.info("[TRANSITION] Созданы правила переходов по умолчанию")

    # --------------------------------------------------------------- states
    def list_states(self, *, active_only: bool = False) -> List[TaskStateDefinition]:
        self.ensure_initialized()
        states = self._states.list_all()
        if active_only:
            states = [state for state in states if state.active]
        return states

    def states_response(self) -> TaskStateDefinitionList:
        states = self.list_states()
        return TaskStateDefinitionList(
            states=states,
            initial_state=self.initial_state_id(),
            final_states=[state.id for state in states if state.is_final],
        )

    def get_state(self, state_id: str) -> TaskStateDefinition:
        self.ensure_initialized()
        state = self._states.get(state_id)
        if state is None:
            raise NotFoundError("Состояние не найдено.")
        return state

    def state_exists(self, state_id: str) -> bool:
        self.ensure_initialized()
        return self._states.exists(state_id)

    def initial_state_id(self) -> str:
        """The state a new task starts in."""
        states = self._states.list_all()
        for state in states:
            if state.is_initial:
                return state.id
        return states[0].id if states else ""

    def final_state_ids(self) -> List[str]:
        return [state.id for state in self._states.list_all() if state.is_final]

    def create_state(self, payload: TaskStateDefinitionCreate) -> TaskStateDefinition:
        """Create a state. The first state created becomes the initial one."""
        self.ensure_initialized()
        state_id = self._unique_state_id(payload.name)
        is_initial = payload.is_initial or self._states.count() == 0
        state = TaskStateDefinition(
            id=state_id,
            name=payload.name,
            description=payload.description,
            is_initial=is_initial,
            is_final=payload.is_final,
            active=payload.active,
            position=self._states.next_position(),
        )
        self._states.save(state)
        if is_initial:
            self._states.clear_initial(except_id=state_id)
        logger.info(
            "[TRANSITION] Создано состояние '%s' (%s)", state.name, state.id
        )
        return self.get_state(state_id)

    def update_state(
        self, state_id: str, payload: TaskStateDefinitionUpdate
    ) -> TaskStateDefinition:
        """Update a state. Renaming keeps the id, so rules stay valid."""
        current = self.get_state(state_id)

        if payload.name is not None:
            current.name = payload.name
        if payload.description is not None:
            current.description = payload.description
        if payload.active is not None:
            current.active = payload.active
        if payload.is_final is not None:
            current.is_final = payload.is_final
        if payload.is_initial is not None:
            current.is_initial = payload.is_initial

        self._states.save(current)
        if current.is_initial:
            # At most one state is initial.
            self._states.clear_initial(except_id=state_id)
        self._validate_lifecycle()
        logger.info("[TRANSITION] Состояние '%s' обновлено", state_id)
        return self.get_state(state_id)

    def delete_state(self, state_id: str) -> None:
        """Delete a state, refusing while rules still reference it."""
        self.get_state(state_id)
        used = self._rules.list_for_state(state_id)
        if used:
            edges = ", ".join(rule.describe() for rule in used[:5])
            raise StateInUseError(
                f"Состояние «{state_id}» используется правилами переходов: {edges}. "
                "Сначала удалите или измените эти правила."
            )
        if self._states.count() <= 1:
            raise StateInUseError("Должно остаться хотя бы одно состояние.")

        was_initial = self._states.get(state_id)
        self._states.delete(state_id)
        if was_initial is not None and was_initial.is_initial:
            remaining = self._states.list_all()
            if remaining:
                remaining[0].is_initial = True
                self._states.save(remaining[0])
        logger.info("[TRANSITION] Состояние '%s' удалено", state_id)

    def _unique_state_id(self, name: str) -> str:
        base = _slugify(name)
        candidate = base
        suffix = 2
        while self._states.exists(candidate):
            candidate = f"{base}_{suffix}"
            suffix += 1
        return candidate

    # ---------------------------------------------------------------- rules
    def list_rules(self, *, active_only: bool = False) -> List[TransitionRule]:
        self.ensure_initialized()
        return self._rules.list_active() if active_only else self._rules.list_all()

    def get_rule(self, rule_id: str) -> TransitionRule:
        self.ensure_initialized()
        rule = self._rules.get(rule_id)
        if rule is None:
            raise NotFoundError("Правило перехода не найдено.")
        return rule

    def create_rule(self, payload: TransitionRuleCreate) -> TransitionRule:
        """Create a rule, validating the edge and the conditions."""
        self.ensure_initialized()
        self._validate_edge(payload.from_state, payload.to_state)
        self._validate_conditions(payload.conditions)

        existing = self._rules.find(payload.from_state, payload.to_state)
        if existing:
            raise DuplicateRuleError(
                f"Правило «{payload.from_state} → {payload.to_state}» уже "
                "существует. Измените его вместо создания нового."
            )

        rule = TransitionRule(
            id=str(uuid.uuid4()),
            from_state=payload.from_state,
            to_state=payload.to_state,
            name=payload.name,
            description=payload.description,
            condition=payload.condition,
            conditions=payload.conditions,
            active=payload.active,
        )
        self._rules.save(rule)
        self._validate_lifecycle()
        logger.info("[TRANSITION] Создано правило: %s", rule.describe())
        return self.get_rule(rule.id)

    def update_rule(
        self, rule_id: str, payload: TransitionRuleUpdate
    ) -> TransitionRule:
        """Update a rule. The change applies to the next transition."""
        current = self.get_rule(rule_id)

        from_state = payload.from_state or current.from_state
        to_state = payload.to_state or current.to_state
        self._validate_edge(from_state, to_state)

        if (from_state, to_state) != (current.from_state, current.to_state):
            clash = [
                rule
                for rule in self._rules.find(from_state, to_state)
                if rule.id != rule_id
            ]
            if clash:
                raise DuplicateRuleError(
                    f"Правило «{from_state} → {to_state}» уже существует."
                )

        if payload.conditions is not None:
            self._validate_conditions(payload.conditions)
            current.conditions = payload.conditions

        current.from_state = from_state
        current.to_state = to_state
        if payload.name is not None:
            current.name = payload.name
        if payload.description is not None:
            current.description = payload.description
        if payload.condition is not None:
            current.condition = payload.condition
        if payload.active is not None:
            current.active = payload.active

        self._rules.save(current)
        self._validate_lifecycle()
        logger.info("[TRANSITION] Правило '%s' обновлено: %s", rule_id, current.describe())
        return self.get_rule(rule_id)

    def delete_rule(self, rule_id: str) -> None:
        self.get_rule(rule_id)
        self._rules.delete(rule_id)
        logger.info("[TRANSITION] Правило '%s' удалено", rule_id)

    def activate_rule(self, rule_id: str) -> TransitionRule:
        current = self.get_rule(rule_id)
        if current.active:
            return current
        current.active = True
        self._rules.save(current)
        logger.info("[TRANSITION] Правило '%s' активировано", rule_id)
        return self.get_rule(rule_id)

    def deactivate_rule(self, rule_id: str) -> TransitionRule:
        current = self.get_rule(rule_id)
        if not current.active:
            return current
        current.active = False
        self._rules.save(current)
        logger.info("[TRANSITION] Правило '%s' деактивировано", rule_id)
        return self.get_rule(rule_id)

    def check_rule(self, rule_id: str, facts: Optional[Dict[str, str]] = None) -> dict:
        """Evaluate a rule against the given facts (or an empty set).

        The result also reports the fields the rule reads but the supplied
        facts do not carry: a condition on such a field can never hold, which
        is worth knowing before the rule blocks a real request.
        """
        rule = self.get_rule(rule_id)
        resolved = facts or {}
        checks = evaluate_conditions(rule.conditions, resolved)
        failure = first_failure(checks)
        fields = self._condition_fields_for_rule(rule)
        missing = [name for name in fields if name not in resolved]
        return {
            "rule_id": rule.id,
            "from_state": rule.from_state,
            "to_state": rule.to_state,
            "active": rule.active,
            "condition": rule.condition_text(),
            "satisfied": failure is None,
            "reason": failure.reason if failure else "",
            "actual": failure.actual if failure else "",
            "required_fields": fields,
            "missing_fields": missing,
            "checks": [
                {
                    "condition": check.condition.describe(),
                    "satisfied": check.satisfied,
                    "actual": check.actual,
                    "reason": check.reason,
                }
                for check in checks
            ],
        }

    def _condition_fields_for_rule(self, rule: TransitionRule) -> List[str]:
        """Every fact a rule reads, in order, without duplicates."""
        fields: List[str] = []
        for condition in rule.conditions:
            for name in self._condition_fields(condition):
                if name and name not in fields:
                    fields.append(name)
        return fields

    # ----------------------------------------------------------- validation
    def _validate_edge(self, from_state: str, to_state: str) -> None:
        """Both ends of a rule must be real states, and not the same one."""
        if not self._states.exists(from_state):
            raise InvalidRuleError(
                f"Состояние «{from_state}» не существует. Создайте его сначала."
            )
        if not self._states.exists(to_state):
            raise InvalidRuleError(
                f"Состояние «{to_state}» не существует. Создайте его сначала."
            )
        if from_state == to_state:
            raise InvalidRuleError(
                "Переход в то же самое состояние не имеет смысла."
            )

    @staticmethod
    def _validate_conditions(conditions: List) -> None:
        """Reject conditions that could never be evaluated."""
        for condition in conditions:
            if condition.is_group():
                if not condition.conditions:
                    raise InvalidRuleError(
                        "Групповое условие должно содержать вложенные условия."
                    )
                TransitionManager._validate_conditions(condition.conditions)
                continue
            if not condition.field:
                raise InvalidRuleError(
                    f"Условие «{condition.type}» требует указать поле."
                )
            if condition.type in ("field_equals", "field_not_equals") and not (
                condition.value
            ):
                raise InvalidRuleError(
                    f"Условие «{condition.type}» требует указать значение."
                )

    def _validate_lifecycle(self) -> None:
        """The lifecycle must stay usable after every change."""
        states = self._states.list_all()
        if not states:
            return

        initial = [state for state in states if state.is_initial]
        if len(initial) > 1:
            raise InvalidRuleError("Начальным может быть только одно состояние.")

        if not any(state.is_final for state in states):
            raise InvalidRuleError(
                "В жизненном цикле должно быть хотя бы одно финальное состояние."
            )

        for rule in self._rules.list_all():
            if not self._states.exists(rule.from_state):
                raise InvalidRuleError(
                    f"Правило ссылается на несуществующее состояние "
                    f"«{rule.from_state}»."
                )
            if not self._states.exists(rule.to_state):
                raise InvalidRuleError(
                    f"Правило ссылается на несуществующее состояние "
                    f"«{rule.to_state}»."
                )

    # ------------------------------------------------------------ transitions
    def facts_for(self, task_id: str) -> Dict[str, str]:
        """The values conditions are checked against.

        The task's own metadata comes first, so a task can carry its own
        ``plan_status``; the machine position is added on top, which makes
        conditions like ``stage == planning`` possible as well.
        """
        data = self._tasks.get_data(task_id)
        facts: Dict[str, str] = {}
        for key, value in (data.metadata or {}).items():
            name = str(key)
            if name == self.EXTRACTED_KEY:
                continue
            facts[name] = str(value)
        facts.setdefault("stage", data.stage)
        facts.setdefault("status", data.status)
        facts.setdefault("current_step", data.current_step)
        facts.setdefault("expected_action", data.expected_action)
        return facts

    def required_fields(self) -> List[str]:
        """Every fact the active rules read, in a stable order."""
        fields: List[str] = []
        for rule in self._rules.list_active():
            for condition in rule.conditions:
                for name in self._condition_fields(condition):
                    if name and name not in fields:
                        fields.append(name)
        return fields

    @staticmethod
    def _condition_fields(condition) -> List[str]:
        """The fact names a condition reads, including nested groups."""
        if condition.is_group():
            names: List[str] = []
            for item in condition.conditions:
                for name in TransitionManager._condition_fields(item):
                    if name not in names:
                        names.append(name)
            return names
        return [condition.field] if condition.field else []

    def facts_response(self, task_id: str) -> TaskFacts:
        """The facts of a task, plus the fields the rules still need.

        ``missing`` is what makes an unsatisfiable rule visible: a condition on
        a field the task does not carry can never hold, and the user has to be
        told which field to set.
        """
        self.ensure_initialized()
        facts = self.facts_for(task_id)
        data = self._tasks.get_data(task_id)
        metadata = data.metadata or {}
        editable = sorted(
            str(key) for key in metadata if str(key) != self.EXTRACTED_KEY
        )
        missing = [
            name
            for name in self.required_fields()
            if name not in facts or not facts.get(name)
        ]
        extracted = [
            str(name)
            for name in (metadata.get(self.EXTRACTED_KEY) or [])
            if str(name) in facts
        ]
        return TaskFacts(
            task_id=task_id,
            facts=facts,
            missing=missing,
            editable=editable,
            extracted=extracted,
        )

    #: Fact names that belong to the machine position. They are derived, so a
    #: caller must never be able to set them through the facts path.
    RESERVED_FACTS: tuple = (
        "stage",
        "status",
        "current_step",
        "expected_action",
    )

    #: Metadata key holding the names of the facts that were read out of the
    #: dialogue, so the UI can show where a value came from.
    EXTRACTED_KEY = "_extracted_facts"

    def set_facts(
        self,
        task_id: str,
        facts: Dict[str, str],
        *,
        only_required: bool = False,
        extracted: bool = False,
    ) -> TaskFacts:
        """Set the task's own facts (its metadata).

        Only the task's metadata is written: the machine position (``stage``,
        ``status``, …) is derived and must not be forged through this path.

        ``only_required=True`` accepts values only for the fields the active
        rules actually read. That is what automatic extraction uses, so a model
        cannot add facts of its own to the task.
        """
        self.ensure_initialized()
        state = self._tasks.get_or_create(task_id)
        metadata = dict(state.data.metadata or {})
        allowed = set(self.required_fields()) if only_required else None

        applied: Dict[str, str] = {}
        for key, value in (facts or {}).items():
            name = str(key).strip()
            if not name or name in self.RESERVED_FACTS:
                continue
            if allowed is not None and name not in allowed:
                logger.debug(
                    "[TRANSITION] Факт '%s' отброшен: правила его не читают",
                    name,
                )
                continue
            text_value = str(value if value is not None else "").strip()
            if text_value:
                metadata[name] = text_value
                applied[name] = text_value
            else:
                # An empty value clears the fact, so a condition on it fails
                # again instead of silently keeping a stale value.
                metadata.pop(name, None)

        # Remember which values came from the dialogue, so the UI can say so.
        if applied:
            known = list(metadata.get(self.EXTRACTED_KEY) or [])
            for name in applied:
                if extracted and name not in known:
                    known.append(name)
                elif not extracted and name in known:
                    known.remove(name)
            if known:
                metadata[self.EXTRACTED_KEY] = known
            else:
                metadata.pop(self.EXTRACTED_KEY, None)

        # The whole map is written, so clearing a fact actually removes it.
        self._tasks.update_step(task_id, metadata=metadata, replace_metadata=True)
        if applied:
            logger.info(
                "[TRANSITION] Факты задачи '%s' обновлены: %s",
                task_id,
                ", ".join(f"{k}={v}" for k, v in sorted(applied.items())),
            )
        return self.facts_response(task_id)

    def _rule_for(
        self, from_state: str, to_state: str
    ) -> Optional[TransitionRule]:
        """The active rule for one edge, if there is one."""
        for rule in self._rules.find(from_state, to_state):
            if rule.active:
                return rule
        return None

    def get_available_transitions(self, task_id: str) -> AvailableTransitions:
        """Every move configured from the current stage, with its verdict."""
        self.ensure_initialized()
        state = self._tasks.get_or_create(task_id)
        data = state.data
        facts = self.facts_for(task_id)

        transitions: List[AvailableTransition] = []
        for rule in self._rules.list_active():
            if rule.from_state != data.stage:
                continue
            checks = evaluate_conditions(rule.conditions, facts)
            failure = first_failure(checks)
            transitions.append(
                AvailableTransition(
                    from_state=rule.from_state,
                    to_state=rule.to_state,
                    rule_id=rule.id,
                    name=rule.name,
                    condition=rule.condition_text(),
                    allowed=failure is None,
                    reason=failure.reason if failure else "",
                    actual=failure.actual if failure else "",
                )
            )

        return AvailableTransitions(
            task_id=task_id,
            stage=data.stage,
            status=data.status,
            transitions=transitions,
        )

    def can_transition(self, task_id: str, target_stage: str) -> bool:
        """Whether the move is allowed right now (rule exists and holds)."""
        return self.validate_transition(task_id, target_stage).allowed

    def validate_transition(self, task_id: str, target_stage: str) -> TransitionOutcome:
        """Check a move without performing it."""
        self.ensure_initialized()
        state = self._tasks.get_or_create(task_id)
        current = state.data.stage

        if target_stage == current:
            return TransitionOutcome(
                task_id=task_id,
                from_state=current,
                to_state=target_stage,
                allowed=True,
                result="success",
                reason="Задача уже на этом этапе.",
            )

        if not self._states.exists(target_stage):
            return TransitionOutcome(
                task_id=task_id,
                from_state=current,
                to_state=target_stage,
                allowed=False,
                reason=f"Состояние «{target_stage}» не существует.",
            )

        rule = self._rule_for(current, target_stage)
        if rule is None:
            available = [
                item.to_state
                for item in self.get_available_transitions(task_id).transitions
            ]
            allowed_text = ", ".join(available) or "нет"
            return TransitionOutcome(
                task_id=task_id,
                from_state=current,
                to_state=target_stage,
                allowed=False,
                reason=(
                    f"Нет активного правила для перехода "
                    f"«{self._label(current)} → {self._label(target_stage)}». "
                    f"Из этапа «{self._label(current)}» допустимо: {allowed_text}."
                ),
            )

        facts = self.facts_for(task_id)
        checks = evaluate_conditions(rule.conditions, facts)
        failure = first_failure(checks)
        if failure is not None:
            field = failure.condition.field
            # A condition on a fact the task does not carry can never be
            # satisfied, so the reason says so instead of showing an empty
            # "current value" the user cannot act on.
            is_set = bool(field) and field in facts
            if field and not is_set:
                reason = (
                    f"Условие перехода не выполнено: "
                    f"{failure.condition.describe()}. "
                    f"Факт «{field}» у задачи не задан — его нужно указать в "
                    f"состоянии задачи."
                )
            else:
                reason = (
                    f"Условие перехода не выполнено: "
                    f"{failure.condition.describe()}."
                )
            return TransitionOutcome(
                task_id=task_id,
                from_state=current,
                to_state=target_stage,
                allowed=False,
                reason=reason,
                required_condition=failure.condition.describe(),
                actual=failure.actual,
                required_field=field,
                field_is_set=is_set,
                rule_id=rule.id,
            )

        return TransitionOutcome(
            task_id=task_id,
            from_state=current,
            to_state=target_stage,
            allowed=True,
            result="success",
            reason=rule.name or rule.condition_text(),
            rule_id=rule.id,
        )

    def transition(
        self,
        task_id: str,
        target_stage: str,
        *,
        reason: str = "",
        trigger: str = "manual",
        current_step: Optional[str] = None,
        expected_action: Optional[str] = None,
    ) -> TransitionOutcome:
        """Move a task, or refuse and explain why.

        A refusal is a normal outcome: the stage is left untouched and the
        attempt is recorded in the history with ``result = rejected``.
        """
        outcome = self.validate_transition(task_id, target_stage)
        outcome.trigger = trigger
        if reason:
            outcome.reason = reason if outcome.allowed else outcome.reason

        if not outcome.allowed:
            self._history.record(
                task_id=task_id,
                from_stage=outcome.from_state,
                to_stage=target_stage,
                trigger=trigger,
                reason=outcome.reason,
                result="rejected",
            )
            logger.info(
                "[TRANSITION] Отклонён '%s': %s → %s (%s)",
                task_id,
                outcome.from_state,
                target_stage,
                outcome.reason,
            )
            outcome.state = self._tasks.get_state(task_id).model_dump(mode="json")
            return outcome

        state = self._tasks.transition(
            task_id,
            target_stage,
            current_step=current_step,
            expected_action=expected_action,
            reason=reason or outcome.reason,
            # The move was already checked against the configured rules, which
            # are the authority here; the built-in edge list must not veto it.
            validated=True,
        )
        self._history.record(
            task_id=task_id,
            from_stage=outcome.from_state,
            to_stage=target_stage,
            trigger=trigger,
            reason=reason or outcome.reason,
            result="success",
        )
        logger.info(
            "[TRANSITION] Выполнен '%s': %s → %s (%s)",
            task_id,
            outcome.from_state,
            target_stage,
            trigger,
        )
        outcome.state = state.model_dump(mode="json")
        return outcome

    def apply_suggestion(
        self, task_id: str, suggestion: TransitionSuggestion
    ) -> Optional[TransitionOutcome]:
        """Apply a transition the model proposed.

        The proposal is only a *request*: it goes through exactly the same
        validation as a manual one, so the model cannot bypass a rule.
        """
        if suggestion.is_empty() or not suggestion.to_state:
            return None
        return self.transition(
            task_id,
            suggestion.to_state,
            reason=suggestion.reason,
            trigger="ai_detected",
        )

    # -------------------------------------------------------------- history
    def history(
        self, task_id: str, *, limit: int = DEFAULT_HISTORY_LIMIT
    ) -> List[TransitionHistoryEntry]:
        return self._history.list_for_task(task_id, limit=limit)

    def on_task_deleted(self, task_id: str) -> int:
        removed = self._history.delete_for_task(task_id)
        if removed:
            logger.info(
                "[TRANSITION] Удалена история переходов задачи %s: %s",
                task_id,
                removed,
            )
        return removed

    # ---------------------------------------------------------- prompt block
    def build_prompt_block(self, task_id: str) -> str:
        """The lifecycle section of the prompt (empty when nothing is set up)."""
        self.ensure_initialized()
        state = self._tasks.get_state(task_id)
        if not state.exists:
            return ""

        available = self.get_available_transitions(task_id)
        if not available.transitions:
            return ""

        lines = ["## TASK STATE RULES", ""]
        lines.append(f"Current state: {self._label(available.stage)}")
        lines.append("Allowed transitions:")
        for item in available.transitions:
            condition = item.condition or "нет дополнительных условий"
            marker = "" if item.allowed else "  [condition not met]"
            lines.append(
                f"- {self._label(item.from_state)} → {self._label(item.to_state)}"
                f" | condition: {condition}{marker}"
            )
        lines.append("")
        lines.append(
            "TRANSITION RULES:\n"
            "1. You may decide that the task should move to another state and "
            "request the transition.\n"
            "2. A transition is applied only if an active rule exists for that "
            "exact edge and its condition holds.\n"
            "3. Never claim that the state changed unless the transition was "
            "accepted.\n"
            "4. If a transition is rejected, explain the required condition and "
            "continue the work without changing the state.\n"
            "5. Before a request is carried out, the transition it would cause "
            "is checked. If that transition is not allowed, the request is not "
            "executed: explain the required condition instead of doing the work."
        )
        return "\n".join(lines)

    @staticmethod
    def _label(state_id: str) -> str:
        return STAGE_LABELS.get(state_id, state_id)

    def describe(self) -> str:
        """One-line summary for logs."""
        states = self._states.list_all()
        rules = self._rules.list_all()
        active = [rule for rule in rules if rule.active]
        return (
            f"состояний={len(states)}, правил={len(rules)}, "
            f"активных={len(active)}"
        )

    # ------------------------------------------------------------- helpers
    def state_labels(self) -> Dict[str, str]:
        """``{state_id: label}`` for the UI and the prompt."""
        return {state.id: state.label for state in self._states.list_all()}

    def task_state(self, task_id: str) -> TaskState:
        return self._tasks.get_state(task_id)

    def ensure_task(self, task_id: str) -> TaskState:
        """Create a task in the configured initial state when it is missing."""
        self.ensure_initialized()
        if self._tasks.get_state(task_id).exists:
            return self._tasks.get_state(task_id)
        initial = self.initial_state_id()
        return self._tasks.create_state(
            task_id,
            payload=None,
            stage=initial or None,
        )

    def edges(self) -> List[Tuple[str, str]]:
        """Every configured edge, for the graph in the UI."""
        return [(rule.from_state, rule.to_state) for rule in self._rules.list_all()]
