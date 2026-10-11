"""API чата: беседы, история, Task Memory и оценка сценариев."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from ..schemas.rag import QUERY_MAX_LENGTH
from ..services.chat import chat_evaluation, chat_repo
from ..services.chat.chat_service import chat_service
from ..utils.errors import NotFoundError
from ..utils.ids import new_id

router = APIRouter(prefix="/api", tags=["Chat"])


class ChatRequest(BaseModel):
    conversation_id: Optional[str] = None
    message: str = ""
    collection_id: Optional[str] = None
    strategy: Optional[str] = None


class ChatEvalRequest(BaseModel):
    scenario: str = "1"
    collection_id: Optional[str] = None
    strategy: Optional[str] = None


@router.post("/chat", summary="Отправить сообщение в чат (полный RAG pipeline)")
def chat_message(req: ChatRequest) -> dict:
    return chat_service.answer(
        conversation_id=req.conversation_id,
        message=req.message,
        collection_id=req.collection_id,
        strategy=req.strategy,
    )


@router.post("/chat/new", summary="Создать новую беседу (без унаследованной истории и state)")
def chat_new() -> dict:
    conv = repo_create()
    return {"conversation_id": conv["id"]}


def repo_create() -> dict:
    # чистая новая беседа (без истории и Task Memory)
    return chat_repo.get_or_create_conversation(None)


@router.get("/chat", summary="Список бесед")
def chat_list(limit: int = Query(default=100, ge=1, le=500)) -> List[dict]:
    return chat_repo.list_conversations(limit)


@router.get("/chat/{conversation_id}", summary="История и Task Memory беседы")
def chat_conversation(conversation_id: str) -> dict:
    if not _exists(conversation_id):
        raise NotFoundError("Беседа не найдена", code="conversation_not_found")
    return chat_repo.conversation_out(conversation_id)


@router.get("/chat/{conversation_id}/state", summary="Task Memory беседы")
def chat_state(conversation_id: str) -> dict:
    if not _exists(conversation_id):
        raise NotFoundError("Беседа не найдена", code="conversation_not_found")
    state = chat_repo.get_task_state(conversation_id)
    return state.to_dict()


def _exists(conversation_id: str) -> bool:
    return any(c["id"] == conversation_id for c in chat_repo.list_conversations(500))


@router.post("/chat/evaluation/run", summary="Прогнать сценарий длинного диалога")
def chat_eval_run(req: ChatEvalRequest) -> dict:
    scenario = chat_evaluation.SCENARIOS.get(req.scenario)
    if scenario is None:
        from ..utils.errors import ValidationError2

        raise ValidationError2("Неизвестный сценарий", code="scenario_unknown")
    return chat_evaluation.run_chat_scenario(
        scenario, collection_id=req.collection_id, strategy=req.strategy,
    )
