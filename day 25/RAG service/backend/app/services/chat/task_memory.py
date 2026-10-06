"""Task Memory: структурированная память задачи.

Хранит цель, ограничения, определения, решения, открытые вопросы и текущий фокус.
Отличается от истории: история — «что было сказано», Task Memory — «что сейчас
важно для задачи».

Решения версионируются: при изменении старого решения прежнее помечается
`superseded`, активным становится новое. В последующих ответах используется
только активное решение.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class DecisionItem:
    key: str
    value: str
    status: str = "active"          # active | superseded
    source: str = "user_message"    # user_message | retrieved_from_rag | inferred
    message_id: Optional[str] = None
    confidence: float = 1.0


@dataclass
class TaskState:
    goal: str = ""
    constraints: List[str] = field(default_factory=list)
    defined_terms: List[Dict[str, str]] = field(default_factory=list)  # {term, definition}
    decisions: List[DecisionItem] = field(default_factory=list)
    open_questions: List[str] = field(default_factory=list)
    current_focus: str = ""
    version: int = 1

    # ------------------------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal": self.goal,
            "constraints": list(self.constraints),
            "defined_terms": list(self.defined_terms),
            "decisions": [asdict(d) for d in self.decisions],
            "open_questions": list(self.open_questions),
            "current_focus": self.current_focus,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "TaskState":
        if not data:
            return cls()
        decisions = [
            DecisionItem(
                key=d.get("key", ""), value=d.get("value", ""),
                status=d.get("status", "active"), source=d.get("source", "user_message"),
                message_id=d.get("message_id"), confidence=float(d.get("confidence", 1.0)),
            )
            for d in data.get("decisions", []) if isinstance(d, dict)
        ]
        return cls(
            goal=data.get("goal", "") or "",
            constraints=[str(c) for c in data.get("constraints", [])],
            defined_terms=[dict(t) for t in data.get("defined_terms", []) if isinstance(t, dict)],
            decisions=decisions,
            open_questions=[str(q) for q in data.get("open_questions", [])],
            current_focus=data.get("current_focus", "") or "",
            version=int(data.get("version", 1) or 1),
        )

    # ------------------------------------------------------------------
    def set_goal(self, goal: str) -> None:
        goal = (goal or "").strip()
        if goal and not self.goal:
            self.goal = goal
            self._bump()

    def add_constraint(self, constraint: str) -> bool:
        constraint = (constraint or "").strip()
        if constraint and constraint.lower() not in [c.lower() for c in self.constraints]:
            self.constraints.append(constraint)
            self._bump()
            return True
        return False

    def remove_constraint(self, phrase: str) -> bool:
        phrase = (phrase or "").strip().lower()
        removed = [c for c in self.constraints if phrase in c.lower()]
        if removed:
            self.constraints = [c for c in self.constraints if phrase not in c.lower()]
            self._bump()
            return True
        return False

    def add_decision(self, key: str, value: str, source: str = "user_message",
                     message_id: Optional[str] = None, confidence: float = 1.0) -> None:
        key = key.strip(); value = (value or "").strip()
        if not key or not value:
            return
        # если та же пара уже активна — не дублируем
        for d in self.decisions:
            if d.status == "active" and d.key == key and d.value.lower() == value.lower():
                return
        # прежние активные решения по этому ключу — superseded
        for d in self.decisions:
            if d.status == "active" and d.key == key:
                d.status = "superseded"
        self.decisions.append(
            DecisionItem(key=key, value=value, status="active", source=source,
                         message_id=message_id, confidence=confidence)
        )
        self._bump()

    def active_decision(self, key: str) -> Optional[DecisionItem]:
        for d in self.decisions:
            if d.status == "active" and d.key == key:
                return d
        return None

    def set_focus(self, focus: str) -> None:
        focus = (focus or "").strip()
        if focus:
            self.current_focus = focus
            self._bump()

    def add_open_question(self, q: str) -> None:
        q = (q or "").strip()
        if q and q not in self.open_questions:
            self.open_questions.append(q)

    # ------------------------------------------------------------------
    def _bump(self) -> None:
        self.version += 1
