"""Chat and message endpoints, including SSE streaming."""

from __future__ import annotations

import json
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from backend.api.dependencies import get_chat_service, get_settings
from backend.models.chat import Chat, ChatCreate, ChatList, ChatUpdate
from backend.models.message import Message, MessageCreate, MessageExchange, MessageList
from backend.services.chat_service import ChatService
from backend.services.settings_service import SettingsService
from backend.utils.errors import AppError, SettingsNotConfiguredError
from backend.utils.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/chats", tags=["chats"])


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("", response_model=ChatList)
async def list_chats(service: ChatService = Depends(get_chat_service)) -> ChatList:
    return ChatList(chats=service.list_chats())


@router.post("", response_model=Chat, status_code=201)
async def create_chat(
    payload: ChatCreate,
    service: ChatService = Depends(get_chat_service),
) -> Chat:
    return service.create_chat(model=payload.model, title=payload.title)


@router.get("/{chat_id}", response_model=Chat)
async def get_chat(
    chat_id: str,
    service: ChatService = Depends(get_chat_service),
) -> Chat:
    return service.get_chat(chat_id)


@router.patch("/{chat_id}", response_model=Chat)
async def update_chat(
    chat_id: str,
    payload: ChatUpdate,
    service: ChatService = Depends(get_chat_service),
) -> Chat:
    return service.update_chat(chat_id, title=payload.title, model=payload.model)


@router.delete("/{chat_id}", status_code=204)
async def delete_chat(
    chat_id: str,
    service: ChatService = Depends(get_chat_service),
) -> None:
    service.delete_chat(chat_id)


@router.get("/{chat_id}/messages", response_model=MessageList)
async def list_messages(
    chat_id: str,
    service: ChatService = Depends(get_chat_service),
) -> MessageList:
    return MessageList(messages=service.list_messages(chat_id))


@router.post("/{chat_id}/messages", response_model=MessageExchange)
async def send_message(
    chat_id: str,
    payload: MessageCreate,
    service: ChatService = Depends(get_chat_service),
    settings: SettingsService = Depends(get_settings),
) -> MessageExchange:
    """Non-streaming message exchange."""
    if not settings.get_api_base_url():
        raise SettingsNotConfiguredError()
    return await service.send_message(chat_id, payload.content)


@router.post("/{chat_id}/messages/stream")
async def stream_message(
    chat_id: str,
    payload: MessageCreate,
    service: ChatService = Depends(get_chat_service),
    settings: SettingsService = Depends(get_settings),
) -> StreamingResponse:
    """Stream the assistant reply as Server-Sent Events."""
    if not settings.get_api_base_url():
        raise SettingsNotConfiguredError()

    async def event_source() -> AsyncIterator[str]:
        try:
            async for event, data in service.stream_message(chat_id, payload.content):
                if event == "user_message":
                    yield _sse("user_message", data.model_dump(mode="json"))
                elif event == "delta":
                    yield _sse("delta", {"content": data})
                elif event == "done":
                    yield _sse("done", data.model_dump(mode="json"))
                elif event == "error":
                    error = data if isinstance(data, AppError) else None
                    yield _sse(
                        "error",
                        {
                            "code": error.code if error else "api_error",
                            "message": error.message
                            if error
                            else "Не удалось получить ответ от API.",
                        },
                    )
        except AppError as exc:
            yield _sse("error", {"code": exc.code, "message": exc.message})
        except Exception:  # noqa: BLE001 - keep the stream alive for the client
            logger.exception("Необработанная ошибка в streaming-ответе")
            yield _sse(
                "error",
                {
                    "code": "internal_error",
                    "message": "Внутренняя ошибка при генерации ответа.",
                },
            )
        finally:
            yield _sse("end", {})

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{chat_id}/regenerate", response_model=MessageExchange)
async def regenerate(
    chat_id: str,
    service: ChatService = Depends(get_chat_service),
    settings: SettingsService = Depends(get_settings),
) -> MessageExchange:
    """Regenerate the last assistant reply (non-streaming)."""
    if not settings.get_api_base_url():
        raise SettingsNotConfiguredError()
    return await service.regenerate(chat_id)


@router.post("/{chat_id}/regenerate/stream")
async def regenerate_stream(
    chat_id: str,
    service: ChatService = Depends(get_chat_service),
    settings: SettingsService = Depends(get_settings),
) -> StreamingResponse:
    """Regenerate the last assistant reply with streaming."""
    if not settings.get_api_base_url():
        raise SettingsNotConfiguredError()

    async def event_source() -> AsyncIterator[str]:
        try:
            async for event, data in service.regenerate_stream(chat_id):
                if event == "delta":
                    yield _sse("delta", {"content": data})
                elif event == "done":
                    yield _sse("done", data.model_dump(mode="json"))
                elif event == "error":
                    error = data if isinstance(data, AppError) else None
                    yield _sse(
                        "error",
                        {
                            "code": error.code if error else "api_error",
                            "message": error.message
                            if error
                            else "Не удалось получить ответ от API.",
                        },
                    )
        except AppError as exc:
            yield _sse("error", {"code": exc.code, "message": exc.message})
        except Exception:  # noqa: BLE001
            logger.exception("Необработанная ошибка в streaming-регенерации")
            yield _sse(
                "error",
                {
                    "code": "internal_error",
                    "message": "Внутренняя ошибка при генерации ответа.",
                },
            )
        finally:
            yield _sse("end", {})

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )