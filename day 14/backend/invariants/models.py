"""Pydantic schemas for invariants — mandatory constraints.

An invariant is a rule the assistant must not violate without an explicit
change to the invariant itself. It answers a different question than the other
layers:

* profile     — *how* should the assistant answer?
* memory      — what is known (dialogue, task context, user facts)?
* task state  — where is the task in its lifecycle?
* **invariant** — what solutions are *not allowed*?

Invariants are stored in their own table and only ever changed through
:class:`backend.invariants.manager.InvariantManager`.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

#: ``global`` applies to the whole project; ``task`` only to one task.
Scope = Literal["global", "task"]

#: What kind of rule this is.
Category = Literal[
    "architecture",
    "technology",
    "business",
    "security",
    "design",
    "technical_decision",
    "constraint",
    "other",
]

#: How strongly the rule binds. ``critical`` must never be traded away.
Priority = Literal["low", "medium", "high", "critical"]

Status = Literal["active", "inactive"]

#: Ordered priorities, used to sort and to render the prompt block.
PRIORITY_ORDER: tuple = ("critical", "high", "medium", "low")

CATEGORY_LABELS = {
    "architecture": "Architecture",
    "technology": "Technology",
    "business": "Business rules",
    "security": "Security",
    "design": "Design",
    "technical_decision": "Technical decisions",
    "constraint": "Constraints",
    "other": "Other",
}

PRIORITY_LABELS = {
    "critical": "CRITICAL",
    "high": "HIGH",
    "medium": "MEDIUM",
    "low": "LOW",
}

#: The scope id used for project-wide invariants.
GLOBAL_SCOPE_ID = "global"


class InvariantData(BaseModel):
    """The invariant itself."""

    scope: Scope = "global"
    category: Category = "other"
    rule: str = ""
    description: str = ""
    status: Status = "active"
    priority: Priority = "medium"
    #: For ``scope == "task"``: which task the rule belongs to.
    task_id: str = ""

    @field_validator("rule", "description", "task_id")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    def is_active(self) -> bool:
        return self.status == "active"


class Invariant(BaseModel):
    """A stored invariant, as returned by the API."""

    id: str
    data: InvariantData = Field(default_factory=InvariantData)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    exists: bool = False

    @property
    def rule(self) -> str:
        return self.data.rule

    @property
    def priority(self) -> str:
        return self.data.priority


class InvariantCreate(BaseModel):
    """Payload for creating an invariant."""

    scope: Scope = "global"
    category: Category = "other"
    rule: str = Field(..., min_length=1, max_length=500)
    description: str = Field(default="", max_length=1000)
    priority: Priority = "medium"
    status: Status = "active"
    task_id: str = ""

    @field_validator("rule", "description", "task_id")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class InvariantUpdate(BaseModel):
    """Payload for updating an invariant (all fields optional)."""

    scope: Optional[Scope] = None
    category: Optional[Category] = None
    rule: Optional[str] = Field(default=None, min_length=1, max_length=500)
    description: Optional[str] = Field(default=None, max_length=1000)
    priority: Optional[Priority] = None
    status: Optional[Status] = None
    task_id: Optional[str] = None

    @field_validator("rule", "description", "task_id")
    @classmethod
    def _strip(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if value is not None else None


class InvariantList(BaseModel):
    invariants: List[Invariant] = Field(default_factory=list)


# --------------------------------------------------------------- conflicts
class InvariantConflict(BaseModel):
    """One detected conflict between a request and an active invariant."""

    invariant_id: str
    rule: str
    category: Category = "other"
    priority: Priority = "medium"
    #: What exactly in the request violates the rule.
    requested: str = ""
    #: Why the model considers this a conflict.
    reason: str = ""


class ConflictCheckResult(BaseModel):
    """Outcome of checking a request against the active invariants."""

    has_conflict: bool = False
    conflicts: List[InvariantConflict] = Field(default_factory=list)
    #: A solution that satisfies every active invariant, when one exists.
    alternative: str = ""
    #: True when the user explicitly asked to change an invariant.
    explicit_change: bool = False
    #: Invariants the user explicitly asked to change.
    change_targets: List[str] = Field(default_factory=list)
    source: str = "llm"

    def summary(self) -> str:
        """One-line description, used in logs and the UI."""
        if not self.has_conflict:
            return "конфликтов нет"
        rules = "; ".join(conflict.rule for conflict in self.conflicts)
        return f"конфликт с: {rules}"
