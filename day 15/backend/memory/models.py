"""Pydantic schemas for the three memory layers.

The layers are deliberately different shapes, because they answer different
questions:

* short-term  — "what was said in this conversation?"
* working     — "what is the state of the task we are doing right now?"
* long-term   — "what is durably true about the user across all chats?"
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

MemoryCategory = Literal["preference", "decision", "fact", "constraint"]

#: Categories that may be stored in long-term memory. Anything else is rejected.
ALLOWED_CATEGORIES: tuple = ("preference", "decision", "fact", "constraint")


# --------------------------------------------------------------- short-term
class ShortTermEntry(BaseModel):
    """One message of the current conversation."""

    id: str
    chat_id: str
    role: Literal["system", "user", "assistant"]
    content: str
    created_at: datetime


class ShortTermMemory(BaseModel):
    """The current dialogue, trimmed to the context window."""

    chat_id: str
    entries: List[ShortTermEntry] = Field(default_factory=list)
    total_messages: int = 0
    truncated: bool = False
    max_messages: int = 0


# ------------------------------------------------------------------ working
class WorkingMemoryData(BaseModel):
    """Structured state of the task the agent is currently working on."""

    task: str = ""
    goal: str = ""
    stack: List[str] = Field(default_factory=list)
    current_step: str = ""
    completed: List[str] = Field(default_factory=list)
    constraints: List[str] = Field(default_factory=list)
    decisions: List[str] = Field(default_factory=list)

    @field_validator("stack", "completed", "constraints", "decisions")
    @classmethod
    def _clean_list(cls, value: List[str]) -> List[str]:
        cleaned: List[str] = []
        for item in value:
            text = str(item).strip()
            if text and text not in cleaned:
                cleaned.append(text)
        return cleaned

    def is_empty(self) -> bool:
        return not any(
            (
                self.task,
                self.goal,
                self.stack,
                self.current_step,
                self.completed,
                self.constraints,
                self.decisions,
            )
        )


class WorkingMemory(BaseModel):
    """Working memory as returned by the API."""

    chat_id: str
    data: WorkingMemoryData = Field(default_factory=WorkingMemoryData)
    updated_at: Optional[datetime] = None
    exists: bool = False


class WorkingMemoryUpdate(BaseModel):
    """Payload for a manual working-memory edit."""

    data: WorkingMemoryData


# ---------------------------------------------------------------- long-term
class LongTermEntry(BaseModel):
    """A single durable fact about the user."""

    id: str
    category: MemoryCategory
    key: str
    value: str
    source: str = "manual"
    confidence: float = 1.0
    created_at: datetime
    updated_at: datetime


class LongTermMemory(BaseModel):
    entries: List[LongTermEntry] = Field(default_factory=list)


class LongTermCreate(BaseModel):
    category: MemoryCategory = "fact"
    key: str = Field(..., min_length=1, max_length=120)
    value: str = Field(..., min_length=1, max_length=500)
    source: str = "manual"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    @field_validator("key", "value")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class LongTermUpdate(BaseModel):
    category: Optional[MemoryCategory] = None
    key: Optional[str] = Field(default=None, min_length=1, max_length=120)
    value: Optional[str] = Field(default=None, min_length=1, max_length=500)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    @field_validator("key", "value")
    @classmethod
    def _strip(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if value is not None else None


# ------------------------------------------------------- extraction results
class LongTermCandidate(BaseModel):
    """A fact the extractor *proposes* for long-term memory.

    The extractor never writes to the database; :class:`MemoryManager` decides
    whether a candidate is accepted.
    """

    category: MemoryCategory = "fact"
    key: str
    value: str
    confidence: float = 0.0
    reason: str = ""


class WorkingMemoryPatch(BaseModel):
    """A proposed change to working memory (only non-empty fields apply)."""

    task: Optional[str] = None
    goal: Optional[str] = None
    stack: List[str] = Field(default_factory=list)
    current_step: Optional[str] = None
    completed: List[str] = Field(default_factory=list)
    constraints: List[str] = Field(default_factory=list)
    decisions: List[str] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not any(
            (
                self.task,
                self.goal,
                self.stack,
                self.current_step,
                self.completed,
                self.constraints,
                self.decisions,
            )
        )


class MemoryExtractionResult(BaseModel):
    """Structured output of :class:`MemoryExtractor`."""

    short_term: bool = True
    working_memory: Optional[WorkingMemoryPatch] = None
    long_term_candidates: List[LongTermCandidate] = Field(default_factory=list)
    summary: str = ""
    source: str = "llm"


class MemoryAnalysisReport(BaseModel):
    """What actually happened after the manager applied an extraction."""

    chat_id: str
    short_term_saved: bool = False
    working_memory_updated: bool = False
    working_memory_changes: List[str] = Field(default_factory=list)
    long_term_accepted: List[LongTermEntry] = Field(default_factory=list)
    long_term_rejected: List[LongTermCandidate] = Field(default_factory=list)
    summary: str = ""
    source: str = "llm"


class MemoryOverview(BaseModel):
    """Everything the UI needs to render the memory screen."""

    chat_id: Optional[str] = None
    short_term: Optional[ShortTermMemory] = None
    working: Optional[WorkingMemory] = None
    long_term: LongTermMemory = Field(default_factory=LongTermMemory)
    prompt_preview: str = ""