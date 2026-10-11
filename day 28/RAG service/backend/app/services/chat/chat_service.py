"""Chat Service: единая оркестрация поверх существующего RAG-сервиса.

не переделывает retrieval/reranking/grounding — вызывает `RagAnswerService.answer`.

Pipeline: message → история → Task Memory → контекстный запрос → RAG →
(внутри RAG: embed → FAISS → rerank → relevance gate → LLM → grounding →
citations) → сохранение сообщений + Task Memory.

Каждое сообщение ОБЯЗАТЕЛЬНО проходит через RAG (rag_called=true всегда).
Task Memory и история помогают строить контекстный поисковый запрос и передаются
LLM в `prelude`, но не заменяют RAG-контекст.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ...schemas.rag import AnswerConfig
from ...utils.logging import get_logger
from .. import runtime
from ..rag.rag_service import RagAnswerService, answer_service
from . import chat_repo
from .contextual_query import build_contextual_query
from .task_memory import TaskState
from .task_state_extractor import apply_task_update, extract_task_update

logger = get_logger(__name__)


def _resolve_collection(collection_id: Optional[str]) -> Optional[str]:
    if collection_id:
        return collection_id
    from ...repositories import collections_repo

    cols = collections_repo.list_collections()
    for c in cols:
        if collections_repo.list_indexes(c["id"]):
            return c["id"]
    return None


def _resolve_strategy(strategy: Optional[str], collection_id: Optional[str]) -> Optional[str]:
    if strategy:
        return strategy
    from ...repositories import collections_repo

    if collection_id:
        recs = collections_repo.list_indexes(collection_id)
        if recs:
            return recs[0]["strategy"]
    return "structural"


def _prelude_for(task_state: TaskState, history: List[dict]) -> str:
    """Собрать TASK STATE + RECENT CONVERSATION для LLM (без фактов, только контекст)."""
    parts = ["=== TASK STATE ==="]
    if task_state.goal:
        parts.append(f"Goal: {task_state.goal}")
    if task_state.constraints:
        parts.append("Constraints:")
        parts.extend(f"- {c}" for c in task_state.constraints)
    if task_state.defined_terms:
        parts.append("Defined terms:")
        parts.extend(f"- {t.get('term', '')}: {t.get('definition', '')}" for t in task_state.defined_terms)
    active = [d for d in task_state.decisions if d.status == "active"]
    if active:
        parts.append("Decisions:")
        for d in active:
            parts.append(f"- {d.key}: {d.value}")
    if task_state.current_focus:
        parts.append(f"Current focus: {task_state.current_focus}")
    if history:
        parts.append("")
        parts.append("=== RECENT CONVERSATION ===")
        for m in history[-6:]:
            who = "User" if m["role"] == "user" else "Assistant"
            parts.append(f"{who}: {m['content'][:400]}")
    return "\n".join(parts)


class ChatService:
    """Оркестратор чата. DI: rag_service, defaults применяются из настроек."""

    def __init__(self, rag: Optional[RagAnswerService] = None, save: bool = True):
        self._rag = rag if rag is not None else answer_service
        self._save = save

    # ------------------------------------------------------------------
    def answer(
        self,
        conversation_id: Optional[str] = None,
        message: str = "",
        *,
        collection_id: Optional[str] = None,
        strategy: Optional[str] = None,
        config: Optional[AnswerConfig] = None,
    ) -> Dict[str, Any]:
        message = (message or "").strip()
        if not message:
            from ...utils.errors import ValidationError2

            raise ValidationError2("Пустое сообщение", code="empty_message")

        settings = runtime.effective_settings()
        conv = chat_repo.get_or_create_conversation(conversation_id)
        cid = conv["id"]

        # 1. сохраняем сообщение пользователя (даже если ответ неуспешен)
        if self._save:
            chat_repo.add_message(cid, "user", message, status="")

        # 2. Task Memory: загружаем, извлекаем обновление, применяем
        state = chat_repo.get_task_state(cid)
        update = extract_task_update(message, state)
        state = apply_task_update(state, update)

        # 3. решим целевую коллекцию/стратегию
        col = _resolve_collection(collection_id)
        strat = _resolve_strategy(strategy, col)
        cfg = config or _default_answer_config(settings)

        # 4. контекстный поисковый запрос
        history = chat_repo.recent_messages(cid, limit=settings.max_history_messages) if self._save else []
        history = [m for m in history if m["role"] == "user" or m["role"] == "assistant"]
        search_query = build_contextual_query(message, state, history)
        rt = {"original_query": message, "search_query": search_query}

        # 5. RAG (всегда). Внутри: relevance gate → LLM → grounding → citations
        prelude = _prelude_for(state, history)
        try:
            result = self._rag.answer(
                search_query, cfg, collection_id=col, strategy=strat,
                user_message=message, prelude=prelude,
            )
        except Exception:
            # сохраняем Task State, даже если RAG упал (сообщение уже сохранено)
            if self._save:
                chat_repo.save_task_state(cid, state)
            raise

        # 6. сохраняем ответ ассистента
        status = result.get("status", "failed")
        assistant_msg_id = None
        if self._save:
            am = chat_repo.add_message(
                cid, "assistant", result.get("answer", ""), status=status,
                search_query=search_query,
                sources=result.get("sources", []), citations=result.get("citations", []),
                retrieval=result.get("retrieval"),
            )
            assistant_msg_id = am["id"]
            chat_repo.save_task_state(cid, state)

        _log_chat(cid, rt, state, result, status)

        return {
            "conversation_id": cid,
            "message_id": assistant_msg_id,
            "status": status,
            "answer": result.get("answer", ""),
            "original_query": message,
            "search_query": search_query,
            "sources": result.get("sources", []),
            "citations": result.get("citations", []),
            "claims": result.get("claims", []),
            "grounding": result.get("grounding", {}),
            "retrieval": result.get("retrieval", {}),
            "config": result.get("config", {}),
            "latency": result.get("latency", {}),
            "task_state": state.to_dict(),
        }


def _default_answer_config(settings) -> AnswerConfig:
    return AnswerConfig(
        query_rewrite=False,
        initial_top_k=settings.default_initial_top_k,
        final_top_k=settings.default_final_top_k,
        enable_filter=True,
        similarity_threshold=settings.default_similarity_threshold,
        enable_reranker=True,
        reranker="heuristic",
        answer_relevance_threshold=settings.default_relevance_threshold,
        grounding_threshold=settings.default_grounding_threshold,
        min_supporting_chunks=settings.default_min_supporting_chunks,
    )


def _log_chat(cid: str, rt: dict, state: TaskState, result: dict, status: str) -> None:
    logger.info(
        "[CHAT] conversation=%s original_query=%s search_query=%s task_state_version=%d "
        "retrieval_top_k=%s reranked_top_k=%s relevance_score=%s grounding_score=%s "
        "sources=%d citations=%d status=%s",
        cid, rt["original_query"], rt["search_query"], state.version,
        result.get("retrieval", {}).get("initial_top_k"),
        result.get("retrieval", {}).get("final_top_k"),
        result.get("retrieval", {}).get("relevance_score"),
        result.get("grounding", {}).get("grounding_score"),
        len(result.get("sources", [])), len(result.get("citations", [])), status,
    )


chat_service = ChatService()
