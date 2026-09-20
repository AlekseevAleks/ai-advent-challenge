"""TaskStateManager — the only way to change a task's state.

The task state is a finite state machine:

```
planning ──► execution ──► validation ──► done
    │            │             │
    └────────────┴─────────────┴──► paused ──► (back to the same stage)
```

Rules enforced here:

* a stage may only move along :data:`ALLOWED_TRANSITIONS`
  (so ``planning → done`` is rejected);
* ``paused`` is a *status*, not a stage — pausing keeps the stage and the step;
* resuming restores the stage the task was paused at;
* every change goes through this manager, never through the repository directly.
"""

from __future__ import annotations

from typing import List, Optional

from backend.database.task_repository import TaskStateRepository
from backend.tasks.models import (
    ALLOWED_TRANSITIONS,
    STAGE_LABELS,
    STAGE_ORDER,
    STATUS_LABELS,
    TaskPauseRequest,
    TaskState,
    TaskStateCreate,
    TaskStateData,
    TaskStateUpdate,
    TaskStepSuggestion,
    TaskTransitionRequest,
)
from backend.utils.errors import AppError, NotFoundError
from backend.utils.logging_config import get_logger

logger = get_logger(__name__)


class InvalidTransitionError(AppError):
    """Raised when a stage change is not allowed by the state machine."""

    status_code = 409
    code = "invalid_transition"
    default_message = "Недопустимый переход состояния задачи."


class TaskStateManager:
    """Creates, reads and transitions task states."""

    def __init__(self, repository: Optional[TaskStateRepository] = None) -> None:
        self._repo = repository or TaskStateRepository()

    # ------------------------------------------------------------- read API
    def get_state(self, task_id: str) -> TaskState:
        """Return a task state; a missing one is reported as ``exists=False``."""
        data = self._repo.get(task_id)
        if data is None:
            return TaskState(task_id=task_id, chat_id=task_id, exists=False)
        meta = self._repo.get_meta(task_id)
        chat_id, created_at, updated_at = meta if meta else (
            task_id,
            None,
            None,
        )
        return TaskState(
            task_id=task_id,
            chat_id=chat_id,
            data=data,
            created_at=created_at,
            updated_at=updated_at,
            exists=True,
        )

    def get_or_create(self, task_id: str, chat_id: Optional[str] = None) -> TaskState:
        """Return the state, creating a fresh ``planning`` one if needed."""
        if not self._repo.exists(task_id):
            return self.create_state(task_id, chat_id=chat_id)
        return self.get_state(task_id)

    def get_data(self, task_id: str) -> TaskStateData:
        return self._repo.get(task_id) or TaskStateData()

    def list_for_chat(self, chat_id: str) -> List[TaskState]:
        return [self.get_state(task_id) for task_id in self._repo.list_for_chat(chat_id)]

    # ------------------------------------------------------------ write API
    def create_state(
        self,
        task_id: str,
        *,
        chat_id: Optional[str] = None,
        payload: Optional[TaskStateCreate] = None,
    ) -> TaskState:
        """Create a task state. Existing states are returned untouched."""
        if self._repo.exists(task_id):
            return self.get_state(task_id)

        data = TaskStateData(
            stage=payload.stage if payload else "planning",
            current_step=payload.current_step if payload else "",
            expected_action=payload.expected_action if payload else "",
            metadata=payload.metadata if payload else {},
        )
        self._repo.save(task_id, chat_id or task_id, data)
        logger.info(
            "[TASK] Создано состояние задачи '%s': stage=%s status=%s",
            task_id,
            data.stage,
            data.status,
        )
        return self.get_state(task_id)

    def update_step(
        self,
        task_id: str,
        *,
        current_step: Optional[str] = None,
        expected_action: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> TaskState:
        """Update the descriptive fields without changing stage or status."""
        state = self.get_or_create(task_id)
        data = state.data
        if current_step is not None:
            data.current_step = current_step
        if expected_action is not None:
            data.expected_action = expected_action
        if metadata is not None:
            data.metadata = {**data.metadata, **metadata}
        self._repo.save(task_id, state.chat_id, data)
        logger.info(
            "[TASK] Шаг обновлён '%s': step=%s expected=%s",
            task_id,
            data.current_step or "—",
            data.expected_action or "—",
        )
        return self.get_state(task_id)

    def apply_update(self, task_id: str, payload: TaskStateUpdate) -> TaskState:
        return self.update_step(
            task_id,
            current_step=payload.current_step,
            expected_action=payload.expected_action,
            metadata=payload.metadata,
        )

    def apply_step_suggestion(
        self, task_id: str, suggestion: TaskStepSuggestion
    ) -> Optional[TaskState]:
        """Store a suggestion produced by one extraction call.

        The suggestion carries the stage together with the step, but the stage
        is still applied through the state machine: only allowed edges are
        taken, and a jump such as ``planning → done`` is refused. The step and
        the expected action are descriptive and are stored as-is.
        """
        if suggestion.is_empty():
            logger.debug("[TASK] Пустое предложение состояния для '%s'", task_id)
            return None

        state = self.get_or_create(task_id)
        data = state.data
        changed = False

        # 1. The stage moves only along allowed edges.
        if suggestion.stage and suggestion.stage != data.stage:
            if suggestion.stage in self.allowed_transitions(data.stage):
                if data.current_step:
                    data.completed_steps = data.completed_steps + [data.current_step]
                data.previous_stage = data.stage  # type: ignore[assignment]
                data.stage = suggestion.stage
                data.status = "completed" if suggestion.stage == "done" else "active"
                data.pause_reason = ""
                changed = True
                logger.info(
                    "[TASK] Этап пересчитан '%s': %s → %s",
                    task_id,
                    data.previous_stage,
                    data.stage,
                )
            else:
                # The model proposed a jump the machine does not allow. Walk
                # the intermediate stages in order instead of refusing outright,
                # so a lagging state still catches up.
                logger.info(
                    "[TASK] Предложен переход %s → %s, иду по шагам",
                    data.stage,
                    suggestion.stage,
                )
                target_index = STAGE_ORDER.index(suggestion.stage)
                while STAGE_ORDER.index(data.stage) < target_index:
                    next_stage = self.allowed_transitions(data.stage)[0]
                    if data.current_step:
                        data.completed_steps = data.completed_steps + [
                            data.current_step
                        ]
                    data.previous_stage = data.stage  # type: ignore[assignment]
                    data.stage = next_stage  # type: ignore[assignment]
                    changed = True
                data.status = "completed" if data.stage == "done" else "active"
                data.pause_reason = ""

        # 2. The descriptive fields are stored as proposed.
        if suggestion.current_step and suggestion.current_step != data.current_step:
            data.current_step = suggestion.current_step
            changed = True
        if (
            suggestion.expected_action
            and suggestion.expected_action != data.expected_action
        ):
            data.expected_action = suggestion.expected_action
            changed = True

        if not changed:
            return state

        data.metadata = {
            **data.metadata,
            "state_source": suggestion.source,
            "state_confidence": suggestion.confidence,
        }
        self._repo.save(task_id, state.chat_id, data)
        logger.info(
            "[TASK] Состояние пересчитано '%s': stage=%s step=%s expected=%s"
            " (confidence %.2f)",
            task_id,
            data.stage,
            data.current_step or "—",
            data.expected_action or "—",
            suggestion.confidence,
        )
        return self.get_state(task_id)

    # ------------------------------------------------------------ transitions
    @staticmethod
    def allowed_transitions(stage: str) -> tuple:
        return ALLOWED_TRANSITIONS.get(stage, ())

    def can_transition(self, task_id: str, new_stage: str) -> bool:
        """Whether ``new_stage`` is reachable from the current stage."""
        current = self.get_data(task_id).stage
        return new_stage in self.allowed_transitions(current)

    def transition(
        self,
        task_id: str,
        new_stage: str,
        *,
        current_step: Optional[str] = None,
        expected_action: Optional[str] = None,
        reason: str = "",
    ) -> TaskState:
        """Move the task to ``new_stage``, validating the edge.

        A paused task is resumed implicitly by an explicit transition, because
        the caller is stating where the task should go next.
        """
        state = self.get_or_create(task_id)
        data = state.data
        current = data.stage

        if new_stage == current:
            # Idempotent: re-stating the current stage is not an error.
            if current_step is not None:
                data.current_step = current_step
            if expected_action is not None:
                data.expected_action = expected_action
            self._repo.save(task_id, state.chat_id, data)
            return self.get_state(task_id)

        if new_stage not in self.allowed_transitions(current):
            allowed = ", ".join(self.allowed_transitions(current)) or "нет"
            raise InvalidTransitionError(
                f"Переход «{STAGE_LABELS.get(current, current)} → "
                f"{STAGE_LABELS.get(new_stage, new_stage)}» не разрешён. "
                f"Из этапа «{STAGE_LABELS.get(current, current)}» "
                f"допустимо: {allowed}."
            )

        # Leaving a stage records the step that was just finished.
        if data.current_step:
            data.completed_steps = data.completed_steps + [data.current_step]

        data.stage = new_stage  # type: ignore[assignment]
        data.previous_stage = current  # type: ignore[assignment]
        data.status = "completed" if new_stage == "done" else "active"
        data.pause_reason = ""
        if current_step is not None:
            data.current_step = current_step
        if expected_action is not None:
            data.expected_action = expected_action

        self._repo.save(task_id, state.chat_id, data)
        logger.info(
            "[TASK] Переход '%s': %s → %s%s",
            task_id,
            current,
            new_stage,
            f" ({reason})" if reason else "",
        )
        return self.get_state(task_id)

    def apply_transition(
        self, task_id: str, payload: TaskTransitionRequest
    ) -> TaskState:
        return self.transition(
            task_id,
            payload.stage,
            current_step=payload.current_step,
            expected_action=payload.expected_action,
            reason=payload.reason,
        )

    # ------------------------------------------------------------ pause/resume
    def pause(
        self, task_id: str, payload: Optional[TaskPauseRequest] = None
    ) -> TaskState:
        """Pause the task, keeping its stage, step and expected action."""
        state = self.get_or_create(task_id)
        data = state.data

        if data.stage == "done":
            raise InvalidTransitionError(
                "Завершённую задачу нельзя поставить на паузу."
            )
        if data.status == "paused":
            return state  # already paused: idempotent

        data.previous_stage = data.stage  # type: ignore[assignment]
        data.status = "paused"
        data.pause_reason = payload.reason if payload else ""

        self._repo.save(task_id, state.chat_id, data)
        logger.info(
            "[TASK] Задача '%s' на паузе: stage=%s step=%s",
            task_id,
            data.stage,
            data.current_step or "—",
        )
        return self.get_state(task_id)

    def resume(self, task_id: str) -> TaskState:
        """Resume a paused task at the stage and step it was paused at."""
        state = self.get_or_create(task_id)
        data = state.data

        if data.status != "paused":
            return state  # nothing to resume: idempotent

        data.status = "active"
        data.pause_reason = ""
        # The stage is intentionally left as-is: pausing never changed it.
        self._repo.save(task_id, state.chat_id, data)
        logger.info(
            "[TASK] Задача '%s' возобновлена: stage=%s step=%s",
            task_id,
            data.stage,
            data.current_step or "—",
        )
        return self.get_state(task_id)

    def complete(self, task_id: str) -> TaskState:
        """Finish the task, moving it to ``done`` through the allowed edges.

        Intermediate stages are walked in order, so the state machine is never
        bypassed (``planning`` cannot jump straight to ``done``).
        """
        state = self.get_or_create(task_id)
        data = state.data

        if data.stage == "done":
            data.status = "completed"
            self._repo.save(task_id, state.chat_id, data)
            return self.get_state(task_id)

        if data.status == "paused":
            data.status = "active"

        # Walk the remaining stages in order.
        while data.stage != "done":
            next_stage = self.allowed_transitions(data.stage)[0]
            if data.current_step:
                data.completed_steps = data.completed_steps + [data.current_step]
            data.previous_stage = data.stage  # type: ignore[assignment]
            data.stage = next_stage  # type: ignore[assignment]

        data.status = "completed"
        data.pause_reason = ""
        self._repo.save(task_id, state.chat_id, data)
        logger.info("[TASK] Задача '%s' завершена", task_id)
        return self.get_state(task_id)

    # ------------------------------------------------------------- lifecycle
    def delete(self, task_id: str) -> bool:
        removed = self._repo.delete(task_id)
        if removed:
            logger.info("[TASK] Состояние задачи '%s' удалено", task_id)
        return removed

    def on_chat_deleted(self, chat_id: str) -> int:
        """Drop task states that belong to a deleted chat."""
        removed = self._repo.delete_for_chat(chat_id)
        if removed:
            logger.info(
                "[TASK] Удалено состояний задач для чата %s: %s", chat_id, removed
            )
        return removed

    # ---------------------------------------------------------- prompt block
    @staticmethod
    def format_state(data: TaskStateData) -> str:
        """Render the state as compact text for the system prompt."""
        lines = [
            f"Stage: {STAGE_LABELS.get(data.stage, data.stage)}",
            f"Current step: {data.current_step or '—'}",
            f"Expected action: {data.expected_action or '—'}",
            f"Status: {STATUS_LABELS.get(data.status, data.status)}",
        ]
        if data.status == "paused" and data.pause_reason:
            lines.append(f"Pause reason: {data.pause_reason}")
        if data.completed_steps:
            lines.append("Completed steps:")
            lines.extend(f"- {step}" for step in data.completed_steps[-10:])
        return "\n".join(lines)

    def build_prompt_block(self, task_id: str) -> str:
        """The task-state section of the prompt (empty when no task exists)."""
        if not self._repo.exists(task_id):
            return ""
        data = self._repo.get(task_id) or TaskStateData()
        return f"## TASK STATE\n\n{self.format_state(data)}"

    def describe(self, task_id: str) -> str:
        """One-line summary for logs."""
        data = self.get_data(task_id)
        return (
            f"stage={data.stage}, status={data.status}, "
            f"step={data.current_step or '—'}"
        )

    # ------------------------------------------------------------- helpers
    @staticmethod
    def stage_index(stage: str) -> int:
        return STAGE_ORDER.index(stage) if stage in STAGE_ORDER else -1