"""InvariantManager — the only way to change invariants.

An invariant is a mandatory constraint: a rule the assistant must not violate
without an explicit change to the invariant itself. The manager owns:

* CRUD over invariants, with ``global`` and ``task`` scopes kept apart;
* activation and deactivation (an inactive rule is kept, not deleted);
* rendering the active rules into a compact prompt block;
* the conflict check that decides whether a request violates a rule.

Nothing else in the application writes invariants, so the rules can never be
changed as a side effect of an ordinary request.
"""

from __future__ import annotations

import uuid
from typing import List, Optional

from backend.database.invariant_repository import (
    GLOBAL_SCOPE_ID,
    InvariantRepository,
)
from backend.invariants.models import (
    CATEGORY_LABELS,
    PRIORITY_LABELS,
    PRIORITY_ORDER,
    ConflictCheckResult,
    Invariant,
    InvariantConflict,
    InvariantCreate,
    InvariantData,
    InvariantUpdate,
)
from backend.utils.errors import NotFoundError
from backend.utils.logging_config import get_logger

logger = get_logger(__name__)

#: How many rules are injected into the prompt at most.
MAX_INVARIANTS_IN_PROMPT = 40


class InvariantManager:
    """Reads, writes and renders invariants."""

    def __init__(self, repository: Optional[InvariantRepository] = None) -> None:
        self._repo = repository or InvariantRepository()

    # ------------------------------------------------------------- read API
    def get(self, invariant_id: str) -> Invariant:
        data = self._repo.get(invariant_id)
        if data is None:
            return Invariant(id=invariant_id, exists=False)
        created_at, updated_at = self._repo.get_timestamps(invariant_id)
        return Invariant(
            id=invariant_id,
            data=data,
            created_at=created_at,
            updated_at=updated_at,
            exists=True,
        )

    def get_or_raise(self, invariant_id: str) -> Invariant:
        invariant = self.get(invariant_id)
        if not invariant.exists:
            raise NotFoundError("Инвариант не найден.")
        return invariant

    def list_invariants(
        self,
        *,
        scope: Optional[str] = None,
        task_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Invariant]:
        """All invariants matching the filters, most binding first."""
        ids = self._repo.list_ids(scope=scope, task_id=task_id, status=status)
        invariants = [self.get(invariant_id) for invariant_id in ids]
        return self._sort(invariants)

    def list_active(self, task_id: Optional[str] = None) -> List[Invariant]:
        """Active rules that apply to a request.

        Global rules always apply. Task rules apply only to their own task, so
        one task's constraints never leak into another.
        """
        active = self.list_invariants(status="active")
        return [
            invariant
            for invariant in active
            if invariant.data.scope == "global"
            or (task_id is not None and invariant.data.task_id == task_id)
        ]

    @staticmethod
    def _sort(invariants: List[Invariant]) -> List[Invariant]:
        """Sort by priority (critical first), then by category."""
        def key(invariant: Invariant):
            priority = invariant.data.priority
            index = (
                PRIORITY_ORDER.index(priority)
                if priority in PRIORITY_ORDER
                else len(PRIORITY_ORDER)
            )
            return (index, invariant.data.category, invariant.data.rule.lower())

        return sorted(invariants, key=key)

    # ------------------------------------------------------------ write API
    def create_invariant(self, payload: InvariantCreate) -> Invariant:
        """Create a rule. Task-scoped rules require a task id."""
        data = InvariantData(
            scope=payload.scope,
            category=payload.category,
            rule=payload.rule,
            description=payload.description,
            status=payload.status,
            priority=payload.priority,
            task_id=payload.task_id,
        )
        if data.scope == "task" and not data.task_id:
            raise NotFoundError("Для task-инварианта нужно указать task_id.")

        invariant_id = str(uuid.uuid4())
        self._repo.save(invariant_id, data)
        logger.info(
            "[INVARIANT] Создан '%s': scope=%s category=%s priority=%s rule=%s",
            invariant_id,
            data.scope,
            data.category,
            data.priority,
            data.rule,
        )
        return self.get(invariant_id)

    def update_invariant(
        self, invariant_id: str, payload: InvariantUpdate
    ) -> Invariant:
        """Update a rule. Only the provided fields change."""
        current = self.get_or_raise(invariant_id)
        data = current.data

        if payload.scope is not None:
            data.scope = payload.scope
        if payload.category is not None:
            data.category = payload.category
        if payload.rule is not None:
            data.rule = payload.rule
        if payload.description is not None:
            data.description = payload.description
        if payload.priority is not None:
            data.priority = payload.priority
        if payload.status is not None:
            data.status = payload.status
        if payload.task_id is not None:
            data.task_id = payload.task_id

        if data.scope == "task" and not data.task_id:
            raise NotFoundError("Для task-инварианта нужно указать task_id.")

        self._repo.save(invariant_id, data)
        logger.info("[INVARIANT] Обновлён '%s': %s", invariant_id, data.rule)
        return self.get(invariant_id)

    def delete_invariant(self, invariant_id: str) -> None:
        self.get_or_raise(invariant_id)
        self._repo.delete(invariant_id)
        logger.info("[INVARIANT] Удалён '%s'", invariant_id)

    def activate_invariant(self, invariant_id: str) -> Invariant:
        """Make a rule binding again."""
        current = self.get_or_raise(invariant_id)
        if current.data.status == "active":
            return current
        current.data.status = "active"
        self._repo.save(invariant_id, current.data)
        logger.info("[INVARIANT] Активирован '%s': %s", invariant_id, current.data.rule)
        return self.get(invariant_id)

    def deactivate_invariant(self, invariant_id: str) -> Invariant:
        """Stop enforcing a rule without deleting it."""
        current = self.get_or_raise(invariant_id)
        if current.data.status == "inactive":
            return current
        current.data.status = "inactive"
        self._repo.save(invariant_id, current.data)
        logger.info(
            "[INVARIANT] Деактивирован '%s': %s", invariant_id, current.data.rule
        )
        return self.get(invariant_id)

    def replace_rule(
        self,
        *,
        old_invariant_id: str,
        new_rule: str,
        category: Optional[str] = None,
        priority: Optional[str] = None,
        description: str = "",
    ) -> Invariant:
        """Apply an explicit decision change: deactivate the old rule, add a new one.

        This is the only path that changes an accepted decision, and it is
        called only when the user explicitly asks for the change.
        """
        old = self.get_or_raise(old_invariant_id)
        self.deactivate_invariant(old_invariant_id)

        created = self.create_invariant(
            InvariantCreate(
                scope=old.data.scope,
                category=category or old.data.category,  # type: ignore[arg-type]
                rule=new_rule,
                description=description,
                priority=priority or old.data.priority,  # type: ignore[arg-type]
                status="active",
                task_id=old.data.task_id,
            )
        )
        logger.info(
            "[INVARIANT] Решение изменено: '%s' деактивирован, '%s' активирован",
            old.data.rule,
            new_rule,
        )
        return created

    # ------------------------------------------------------------- lifecycle
    def on_task_deleted(self, task_id: str) -> int:
        """Drop task-scoped rules of a deleted task. Global rules are kept."""
        removed = self._repo.delete_for_task(task_id)
        if removed:
            logger.info(
                "[INVARIANT] Удалено task-инвариантов для задачи %s: %s",
                task_id,
                removed,
            )
        return removed

    # ---------------------------------------------------------- prompt block
    @staticmethod
    def format_invariants(invariants: List[Invariant]) -> str:
        """Render active rules grouped by category, most binding first."""
        if not invariants:
            return ""

        by_category: dict = {}
        for invariant in invariants[:MAX_INVARIANTS_IN_PROMPT]:
            by_category.setdefault(invariant.data.category, []).append(invariant)

        lines: List[str] = []
        for category, items in by_category.items():
            lines.append(f"{CATEGORY_LABELS.get(category, category)}:")
            for invariant in items:
                marker = PRIORITY_LABELS.get(invariant.data.priority, "")
                suffix = f" [{marker}]" if marker == "CRITICAL" else ""
                lines.append(f"- {invariant.data.rule}{suffix}")
                if invariant.data.description:
                    lines.append(f"  ({invariant.data.description})")
        return "\n".join(lines)

    def build_prompt_block(self, task_id: Optional[str] = None) -> str:
        """The invariants section of the prompt (empty when there are none)."""
        active = self.list_active(task_id)
        if not active:
            return ""
        return f"## ACTIVE INVARIANTS\n\n{self.format_invariants(active)}"

    def describe(self, task_id: Optional[str] = None) -> str:
        """One-line summary for logs."""
        active = self.list_active(task_id)
        if not active:
            return "нет активных инвариантов"
        critical = sum(
            1 for invariant in active if invariant.data.priority == "critical"
        )
        return f"активных={len(active)}, critical={critical}"

    # -------------------------------------------------------- conflict check
    def check_conflict(
        self,
        request: str,
        *,
        task_id: Optional[str] = None,
        result: Optional[ConflictCheckResult] = None,
    ) -> ConflictCheckResult:
        """Validate a proposed conflict check against the active rules.

        The detector proposes; this method disposes. Conflicts that do not
        reference a real active invariant are dropped, so the model cannot
        invent a rule that does not exist.
        """
        active = self.list_active(task_id)
        if not active:
            return ConflictCheckResult(has_conflict=False, source="no-invariants")

        if result is None:
            return ConflictCheckResult(has_conflict=False, source="unavailable")

        by_id = {invariant.id: invariant for invariant in active}
        by_rule = {invariant.data.rule.strip().lower(): invariant for invariant in active}

        validated: List[InvariantConflict] = []
        for conflict in result.conflicts:
            invariant = by_id.get(conflict.invariant_id) or by_rule.get(
                (conflict.rule or "").strip().lower()
            )
            if invariant is None:
                # The model referenced a rule that is not active: ignore it.
                logger.debug(
                    "[INVARIANT] Конфликт с неизвестным правилом отброшен: %s",
                    conflict.rule,
                )
                continue
            validated.append(
                InvariantConflict(
                    invariant_id=invariant.id,
                    rule=invariant.data.rule,
                    category=invariant.data.category,
                    priority=invariant.data.priority,
                    requested=conflict.requested or request[:200],
                    reason=conflict.reason,
                )
            )

        if not validated:
            return ConflictCheckResult(
                has_conflict=False,
                explicit_change=result.explicit_change,
                change_targets=result.change_targets,
                source=result.source,
            )

        return ConflictCheckResult(
            has_conflict=True,
            conflicts=validated,
            alternative=result.alternative,
            explicit_change=result.explicit_change,
            change_targets=result.change_targets,
            source=result.source,
        )

    def resolve_change_targets(
        self, result: ConflictCheckResult, *, task_id: Optional[str] = None
    ) -> List[Invariant]:
        """Active invariants the user explicitly asked to change."""
        if not result.explicit_change:
            return []
        active = self.list_active(task_id)
        by_id = {invariant.id: invariant for invariant in active}
        by_rule = {invariant.data.rule.strip().lower(): invariant for invariant in active}

        targets: List[Invariant] = []
        for target in result.change_targets:
            invariant = by_id.get(target) or by_rule.get((target or "").strip().lower())
            if invariant is not None and invariant not in targets:
                targets.append(invariant)
        return targets
