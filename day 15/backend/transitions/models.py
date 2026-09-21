"""Pydantic schemas for the configurable task lifecycle.

This layer answers a different question than the ones around it:

* profile     — *how* should the assistant answer?
* memory      — what is known?
* task state  — where is the task right now?
* invariants  — which solutions are *not allowed*?
* **transitions** — *which moves between states are allowed, and when?*

The vocabulary of states and the rules between them live in the database, not
in code: the user edits them on the *Task State Rules* page and the change
applies to the next transition without a restart.

Conditions are structured, not free text. A rule carries a list of condition
objects that are evaluated against the task's *facts* (a flat string map):

```json
{"type": "field_equals", "field": "plan_status", "value": "approved"}
```

The supported types are deliberately a small, safe set — there is no
expression language to escape from.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

#: The four stages the built-in lifecycle is seeded with. They are only the
#: *default* vocabulary: the user may add, rename or remove states.
DEFAULT_STATE_NAMES: tuple = ("planning", "execution", "validation", "done")

#: The built-in edges, seeded once so the machine works out of the box.
#: They carry no conditions: the default lifecycle must keep working exactly as
#: before, and the user adds conditions on the *Task State Rules* page when the
#: project needs them.
DEFAULT_TRANSITIONS: tuple = (
    ("planning", "execution", "Start implementation", ""),
    ("execution", "validation", "Start validation", ""),
    ("validation", "done", "Finish task", ""),
)

#: Condition types the evaluator understands. Anything else is rejected when a
#: rule is created, so a rule can never be silently unenforceable.
CONDITION_TYPES: tuple = (
    "field_equals",
    "field_not_equals",
    "field_not_empty",
    "field_empty",
    "boolean_true",
    "boolean_false",
    "all_conditions",
    "any_condition",
)

#: Human-readable labels for the UI.
CONDITION_LABELS = {
    "field_equals": "field_equals — поле равно значению",
    "field_not_equals": "field_not_equals — поле не равно значению",
    "field_not_empty": "field_not_empty — поле заполнено",
    "field_empty": "field_empty — поле пустое",
    "boolean_true": "boolean_true — флаг включён",
    "boolean_false": "boolean_false — флаг выключен",
    "all_conditions": "all_conditions — все вложенные условия",
    "any_condition": "any_condition — любое из вложенных условий",
}

#: Values that count as "true" for the boolean condition types.
TRUE_VALUES = ("true", "1", "yes", "y", "on", "да", "истина")
FALSE_VALUES = ("false", "0", "no", "n", "off", "нет", "ложь")

#: Where a transition attempt came from.
Trigger = Literal["ai_detected", "user", "manual", "system", "pause", "resume"]

#: Outcome of a transition attempt.
TransitionResult = Literal["success", "rejected"]


class Condition(BaseModel):
    """One structured condition of a transition rule.

    ``all_conditions`` / ``any_condition`` nest further conditions in
    ``conditions``; every other type reads one field of the task facts.
    """

    type: str = "field_equals"
    field: str = ""
    value: str = ""
    conditions: List["Condition"] = Field(default_factory=list)

    @field_validator("type")
    @classmethod
    def _known_type(cls, value: str) -> str:
        resolved = (value or "").strip()
        if resolved not in CONDITION_TYPES:
            raise ValueError(
                f"Неизвестный тип условия: «{resolved}». "
                f"Допустимо: {', '.join(CONDITION_TYPES)}."
            )
        return resolved

    @field_validator("field", "value")
    @classmethod
    def _strip(cls, value: str) -> str:
        return (value or "").strip()

    def is_group(self) -> bool:
        return self.type in ("all_conditions", "any_condition")

    def describe(self) -> str:
        """Render the condition as a short human-readable line."""
        if self.type == "all_conditions":
            inner = " И ".join(item.describe() for item in self.conditions)
            return f"({inner})" if inner else "все условия"
        if self.type == "any_condition":
            inner = " ИЛИ ".join(item.describe() for item in self.conditions)
            return f"({inner})" if inner else "любое условие"
        if self.type == "field_equals":
            return f"{self.field} == {self.value}"
        if self.type == "field_not_equals":
            return f"{self.field} != {self.value}"
        if self.type == "field_not_empty":
            return f"{self.field} заполнено"
        if self.type == "field_empty":
            return f"{self.field} пусто"
        if self.type == "boolean_true":
            return f"{self.field} == true"
        if self.type == "boolean_false":
            return f"{self.field} == false"
        return self.type


Condition.model_rebuild()


class ConditionCheck(BaseModel):
    """The outcome of evaluating one condition."""

    condition: Condition
    satisfied: bool
    #: What the facts actually held, so a rejection can explain itself.
    actual: str = ""
    reason: str = ""

    def describe(self) -> str:
        return self.condition.describe()


class TaskStateDefinition(BaseModel):
    """One state of the lifecycle, as configured by the user."""

    id: str
    name: str = ""
    description: str = ""
    is_initial: bool = False
    is_final: bool = False
    active: bool = True
    position: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    exists: bool = False

    @property
    def label(self) -> str:
        return self.name or self.id


class TaskStateDefinitionCreate(BaseModel):
    """Payload for creating a state."""

    name: str = Field(..., min_length=1, max_length=60)
    description: str = Field(default="", max_length=500)
    is_initial: bool = False
    is_final: bool = False
    active: bool = True

    @field_validator("name", "description")
    @classmethod
    def _strip(cls, value: str) -> str:
        return (value or "").strip()


class TaskStateDefinitionUpdate(BaseModel):
    """Payload for updating a state (all fields optional)."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=60)
    description: Optional[str] = Field(default=None, max_length=500)
    is_initial: Optional[bool] = None
    is_final: Optional[bool] = None
    active: Optional[bool] = None

    @field_validator("name", "description")
    @classmethod
    def _strip(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if value is not None else None


class TaskStateDefinitionList(BaseModel):
    states: List[TaskStateDefinition] = Field(default_factory=list)
    initial_state: str = ""
    final_states: List[str] = Field(default_factory=list)


class TransitionRule(BaseModel):
    """One allowed move between two states, with its conditions."""

    id: str
    from_state: str
    to_state: str
    name: str = ""
    description: str = ""
    #: Free-text condition, kept for the UI and the prompt.
    condition: str = ""
    #: Structured conditions actually evaluated by the manager.
    conditions: List[Condition] = Field(default_factory=list)
    active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    exists: bool = False

    def describe(self) -> str:
        """``Planning → Execution`` with the condition, for logs and the UI."""
        text = f"{self.from_state} → {self.to_state}"
        if self.condition:
            text = f"{text} ({self.condition})"
        return text

    def condition_text(self) -> str:
        """The condition as text: the structured one wins over the free text."""
        if self.conditions:
            return " И ".join(item.describe() for item in self.conditions)
        return self.condition


class TransitionRuleCreate(BaseModel):
    """Payload for creating a transition rule."""

    from_state: str = Field(..., min_length=1, max_length=60)
    to_state: str = Field(..., min_length=1, max_length=60)
    name: str = Field(default="", max_length=120)
    description: str = Field(default="", max_length=500)
    condition: str = Field(default="", max_length=500)
    conditions: List[Condition] = Field(default_factory=list)
    active: bool = True

    @field_validator("from_state", "to_state", "name", "description", "condition")
    @classmethod
    def _strip(cls, value: str) -> str:
        return (value or "").strip()


class TransitionRuleUpdate(BaseModel):
    """Payload for updating a rule (all fields optional)."""

    from_state: Optional[str] = Field(default=None, min_length=1, max_length=60)
    to_state: Optional[str] = Field(default=None, min_length=1, max_length=60)
    name: Optional[str] = Field(default=None, max_length=120)
    description: Optional[str] = Field(default=None, max_length=500)
    condition: Optional[str] = Field(default=None, max_length=500)
    conditions: Optional[List[Condition]] = None
    active: Optional[bool] = None

    @field_validator("from_state", "to_state", "name", "description", "condition")
    @classmethod
    def _strip(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if value is not None else None


class TransitionRuleList(BaseModel):
    rules: List[TransitionRule] = Field(default_factory=list)


class TransitionHistoryEntry(BaseModel):
    """One recorded transition attempt."""

    id: str
    task_id: str
    from_stage: str
    to_stage: str
    trigger: str = "manual"
    reason: str = ""
    result: str = "success"
    created_at: Optional[datetime] = None


class TransitionHistoryList(BaseModel):
    task_id: str
    entries: List[TransitionHistoryEntry] = Field(default_factory=list)


class AvailableTransition(BaseModel):
    """A move the task could make right now, and whether it is allowed."""

    from_state: str
    to_state: str
    rule_id: str = ""
    name: str = ""
    condition: str = ""
    #: True when the rule exists, is active and its conditions hold.
    allowed: bool = False
    #: Why it is not allowed, in the user's words.
    reason: str = ""
    #: What the facts held, for the failing condition.
    actual: str = ""


class AvailableTransitions(BaseModel):
    task_id: str
    stage: str = ""
    status: str = ""
    transitions: List[AvailableTransition] = Field(default_factory=list)


class TaskFacts(BaseModel):
    """The values transition conditions are checked against.

    Facts come from the task's own metadata plus its machine position. A rule
    may reference a fact the task does not carry yet; such a condition can
    never hold, so the missing fields are reported explicitly.
    """

    task_id: str
    facts: Dict[str, str] = Field(default_factory=dict)
    #: Fields referenced by the active rules but absent from the facts.
    missing: List[str] = Field(default_factory=list)
    #: Fields the task itself carries (its metadata), which the user may edit.
    editable: List[str] = Field(default_factory=list)
    #: Fields that were read out of the user's own messages rather than typed
    #: by hand, so the UI can show where a value came from.
    extracted: List[str] = Field(default_factory=list)


class TaskFactsUpdate(BaseModel):
    """Payload for setting the task's own facts."""

    facts: Dict[str, str] = Field(default_factory=dict)

    @field_validator("facts")
    @classmethod
    def _clean(cls, value: Dict[str, str]) -> Dict[str, str]:
        cleaned: Dict[str, str] = {}
        for key, item in (value or {}).items():
            name = str(key).strip()
            if not name:
                continue
            cleaned[name] = str(item if item is not None else "").strip()
        return cleaned


class TransitionRequest(BaseModel):
    """Payload for an explicit transition of a task.

    ``stage`` is accepted as an alias of ``to_state`` so the older payload
    shape keeps working; the move is validated the same way either way.
    """

    to_state: str = Field(default="", max_length=60)
    stage: str = Field(default="", max_length=60)
    reason: str = Field(default="", max_length=500)
    trigger: Trigger = "user"
    current_step: Optional[str] = None
    expected_action: Optional[str] = None

    @field_validator("to_state", "stage", "reason", "current_step", "expected_action")
    @classmethod
    def _strip(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if value is not None else None

    @model_validator(mode="after")
    def _resolve_target(self) -> "TransitionRequest":
        if not self.to_state:
            self.to_state = self.stage
        if not self.to_state:
            raise ValueError("Укажите целевое состояние в поле 'to_state'.")
        return self


class TransitionOutcome(BaseModel):
    """The result of asking the manager to move a task.

    A rejected transition is a normal outcome, not an error: the stage simply
    does not change and the reason is reported to the caller.
    """

    task_id: str
    from_state: str = ""
    to_state: str = ""
    allowed: bool = False
    result: TransitionResult = "rejected"
    reason: str = ""
    #: The condition that blocked the move, when one did.
    required_condition: str = ""
    actual: str = ""
    #: The fact the condition reads, and whether the task carries it at all.
    #: A condition on a fact that was never set can never be satisfied, which
    #: is a different problem from a fact that holds the wrong value.
    required_field: str = ""
    field_is_set: bool = True
    rule_id: str = ""
    trigger: str = "manual"
    #: The task state after the attempt (unchanged when rejected).
    state: Optional[Dict[str, Any]] = None

    def summary(self) -> str:
        if self.allowed:
            return f"{self.from_state} → {self.to_state}: разрешён"
        return f"{self.from_state} → {self.to_state}: отклонён ({self.reason})"


class TransitionSuggestion(BaseModel):
    """A transition the model *proposes* after reading the dialogue.

    Like the other extractors this is side-effect free: the detector proposes,
    :class:`~backend.transitions.manager.TransitionManager` disposes.
    """

    to_state: Optional[str] = None
    reason: str = ""
    confidence: float = 0.0
    source: str = "llm"

    def is_empty(self) -> bool:
        return not self.to_state
