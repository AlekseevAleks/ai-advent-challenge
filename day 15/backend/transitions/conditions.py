"""Evaluation of structured transition conditions.

A condition is checked against the *facts* of a task: a flat map of string
values (``plan_status = approved``, ``implementation_status = completed``, …).
The evaluator is deliberately small and total — every supported type has a
defined answer, and an unknown type is rejected when the rule is created, so a
rule can never be silently unenforceable.

The evaluator never writes anything: it returns which conditions held and what
the facts actually contained, so a rejection can explain itself to the user.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from backend.transitions.models import (
    FALSE_VALUES,
    TRUE_VALUES,
    Condition,
    ConditionCheck,
)

#: How deep nested ``all_conditions`` / ``any_condition`` may go.
MAX_DEPTH = 5


def _normalise(value: object) -> str:
    return str(value if value is not None else "").strip()


def _comparable(value: str) -> str:
    """Fold a value down to what a human would consider "the same word".

    Values are written by people in their own language, so the comparison has
    to tolerate the differences that carry no meaning: case, surrounding
    whitespace, and the Russian ``ё``/``е`` spelling (a user writes "план
    утвержден", the model may answer "утверждён"). Without this, a rule would
    silently never match because of one letter.
    """
    folded = _normalise(value).lower().replace("ё", "е")
    return " ".join(folded.split())


def _as_bool(value: str) -> Optional[bool]:
    """Interpret a fact as a boolean, or ``None`` when it is not one."""
    lowered = value.strip().lower()
    if lowered in TRUE_VALUES:
        return True
    if lowered in FALSE_VALUES:
        return False
    return None


def evaluate_condition(
    condition: Condition, facts: Dict[str, str], *, depth: int = 0
) -> ConditionCheck:
    """Check one condition against the facts."""
    if depth > MAX_DEPTH:
        return ConditionCheck(
            condition=condition,
            satisfied=False,
            reason="Слишком глубокая вложенность условий.",
        )

    if condition.is_group():
        return _evaluate_group(condition, facts, depth=depth)

    actual = _normalise(facts.get(condition.field, ""))
    expected = condition.value

    if condition.type == "field_equals":
        satisfied = _comparable(actual) == _comparable(expected)
        reason = "" if satisfied else f"Требуется {condition.field} == {expected}."
    elif condition.type == "field_not_equals":
        satisfied = _comparable(actual) != _comparable(expected)
        reason = "" if satisfied else f"Требуется {condition.field} != {expected}."
    elif condition.type == "field_not_empty":
        satisfied = bool(actual)
        reason = "" if satisfied else f"Поле {condition.field} не заполнено."
    elif condition.type == "field_empty":
        satisfied = not actual
        reason = "" if satisfied else f"Поле {condition.field} заполнено."
    elif condition.type == "boolean_true":
        flag = _as_bool(actual)
        satisfied = flag is True
        reason = "" if satisfied else f"Флаг {condition.field} не включён."
    elif condition.type == "boolean_false":
        flag = _as_bool(actual)
        satisfied = flag is False
        reason = "" if satisfied else f"Флаг {condition.field} не выключен."
    else:  # pragma: no cover - guarded by the model validator
        satisfied = False
        reason = f"Неизвестный тип условия: {condition.type}."

    return ConditionCheck(
        condition=condition,
        satisfied=satisfied,
        actual=actual,
        reason=reason,
    )


def _evaluate_group(
    condition: Condition, facts: Dict[str, str], *, depth: int
) -> ConditionCheck:
    """Check a nested group of conditions."""
    if not condition.conditions:
        # An empty group is vacuously true: it constrains nothing.
        return ConditionCheck(condition=condition, satisfied=True, actual="")

    checks = [
        evaluate_condition(item, facts, depth=depth + 1)
        for item in condition.conditions
    ]

    if condition.type == "all_conditions":
        satisfied = all(check.satisfied for check in checks)
    else:  # any_condition
        satisfied = any(check.satisfied for check in checks)

    if satisfied:
        return ConditionCheck(condition=condition, satisfied=True, actual="")

    failed = next((check for check in checks if not check.satisfied), checks[0])
    return ConditionCheck(
        condition=condition,
        satisfied=False,
        actual=failed.actual,
        reason=failed.reason or "Вложенное условие не выполнено.",
    )


def evaluate_conditions(
    conditions: List[Condition], facts: Dict[str, str]
) -> List[ConditionCheck]:
    """Check every condition of a rule, in order."""
    return [evaluate_condition(condition, facts) for condition in conditions]


def first_failure(checks: List[ConditionCheck]) -> Optional[ConditionCheck]:
    """The first condition that did not hold, if any."""
    for check in checks:
        if not check.satisfied:
            return check
    return None


def conditions_hold(conditions: List[Condition], facts: Dict[str, str]) -> bool:
    """Whether every condition of a rule holds. No conditions means allowed."""
    if not conditions:
        return True
    return all(check.satisfied for check in evaluate_conditions(conditions, facts))
