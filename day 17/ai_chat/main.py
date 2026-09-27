"""FastAPI-приложение сервиса ИИ-чата.

Предоставляет REST-эндпоинты для управления настройками, моделями и чатами,
а также SSE-эндпоинт для потоковой отправки сообщений. При запуске
автоматически открывает браузер на локальном адресе.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
import webbrowser
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.requests import Request

import api_client
import chats_manager
import config_manager
import memory_layers
import request_logger
from app.mcp import settings as mcp_settings
from app.mcp.client import MCPClient
from app.mcp.models import MCPTool
from app.mcp.openai_format import find_tool, to_openai_tools, validate_arguments

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HOST = "127.0.0.1"
PORT = 8000

# Идентификатор пользователя для долговременной памяти (локальный сервис).
DEFAULT_USER_ID = "local-user"

# Максимум раундов «модель -> инструменты -> модель» в одном сообщении чата.
MAX_TOOL_ROUNDS = 5

app = FastAPI(title="AI Chat", description="Локальный сервис ИИ-чата", version="1.0.0")

app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


class ConfigPayload(BaseModel):
    """Тело запроса на сохранение настроек."""

    api_url: str = Field(default="")
    api_key: str = Field(default="")
    default_model: str = Field(default="")


class ChatPayload(BaseModel):
    """Тело запроса на создание чата."""

    model: str = Field(default="")
    title: str = Field(default="Новый чат")


class MessagePayload(BaseModel):
    """Тело запроса на отправку сообщения."""

    content: str = Field(default="")
    user_id: str = Field(default=DEFAULT_USER_ID)
    # Ablation: какие слои памяти включены (по умолчанию — все).
    memory_layers: Optional[List[str]] = Field(default=None)


class MemoryTogglesPayload(BaseModel):
    """Тело запроса на переключение слоёв памяти (ablation)."""

    layers: List[str] = Field(default_factory=list)


class MCPAddressPayload(BaseModel):
    """Тело запроса на проверку подключения к MCP-серверу."""

    address: str = Field(default="")


class CollapsePayload(BaseModel):
    """Тело запроса на «схлопывание» рабочей памяти в long-term."""

    session_id: str = Field(default="")
    user_id: str = Field(default=DEFAULT_USER_ID)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Отдаёт основной интерфейс приложения."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/dashboard/memory", response_class=HTMLResponse)
async def memory_dashboard(request: Request) -> HTMLResponse:
    """Отдаёт экран мониторинга трёх слоёв памяти агента."""
    return templates.TemplateResponse("memory_dashboard.html", {"request": request})
@app.get("/api/config")
async def get_config() -> Dict[str, Any]:
    """Возвращает текущий конфиг с маскированным ключом."""
    return config_manager.public_config()


@app.post("/api/config")
async def post_config(payload: ConfigPayload) -> Dict[str, Any]:
    """Сохраняет настройки подключения к API."""
    try:
        api_client.validate_url(payload.api_url)
    except api_client.ApiError as exc:
        raise HTTPException(status_code=400, detail=exc.message)
    config_manager.save_config(payload.api_url, payload.api_key, payload.default_model)
    return config_manager.public_config()


@app.post("/api/config/test")
async def test_config(payload: ConfigPayload) -> Dict[str, Any]:
    """Проверяет подключение к внешнему API по переданным или сохранённым данным."""
    saved = config_manager.load_config()
    api_url = payload.api_url.strip() or saved.get("api_url", "")
    api_key = payload.api_key.strip() or saved.get("api_key", "")
    try:
        result = await api_client.test_connection(api_url, api_key)
    except api_client.ApiError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    return result


# ---------------------------------------------------------------------------
# Эндпоинты страницы «Подключение к MCP» (/api/mcp/*)
# ---------------------------------------------------------------------------


def _mcp_address(payload: MCPAddressPayload) -> str:
    """Извлекает и валидирует адрес MCP-сервера из тела запроса."""
    address = (payload.address or "").strip()
    if not address:
        raise HTTPException(status_code=400, detail="Укажите адрес MCP-сервера.")
    if not (address.startswith("http://") or address.startswith("https://")):
        raise HTTPException(
            status_code=400,
            detail="Адрес MCP-сервера должен начинаться с http:// или https://.",
        )
    return address


def _mcp_error(exc: BaseException) -> str:
    """Возвращает короткое безопасное сообщение об ошибке MCP-подключения.

    - ``ExceptionGroup`` раскрывается до первопричины;
    - ``CancelledError`` означает, что SDK отменил запрос — обычно потому,
      что сервер недоступен или оборвал соединение.
    """
    if isinstance(exc, asyncio.CancelledError):
        return "соединение прервано (MCP-сервер недоступен или закрыл соединение)"
    message = str(exc) or exc.__class__.__name__
    while getattr(exc, "exceptions", None):
        exc = exc.exceptions[0]
        message = str(exc) or exc.__class__.__name__
    return message[:300]


@app.get("/api/mcp/config")
async def get_mcp_config() -> Dict[str, Any]:
    """Возвращает сохранённый адрес MCP-сервера."""
    return {"address": mcp_settings.load_address()}


@app.post("/api/mcp/check")
async def post_mcp_check(payload: MCPAddressPayload) -> Dict[str, Any]:
    """Проверяет подключение к MCP-серверу по адресу (без авторизации).

    Выполняет connect + initialize, затем всегда корректно закрывает
    соединение (try/finally).
    """
    address = _mcp_address(payload)
    client = MCPClient.for_url(address)
    try:
        await client.connect()
        result = await client.initialize()
        mcp_settings.save_address(address)
        return {
            "ok": True,
            "address": address,
            "server_info": result.get("serverInfo") or result,
        }
    except asyncio.CancelledError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"MCP connection failed: {_mcp_error(exc)}",
        ) from exc
    except Exception as exc:  # noqa: BLE001 - пользователю нужен читаемый текст ошибки
        raise HTTPException(
            status_code=400,
            detail=f"MCP connection failed: {_mcp_error(exc)}",
        ) from exc
    finally:
        await client.disconnect()


@app.post("/api/mcp/tools")
async def post_mcp_tools(payload: MCPAddressPayload) -> Dict[str, Any]:
    """Запрашивает список инструментов MCP-сервера по адресу.

    Выполняет connect + initialize + list_tools, затем всегда корректно
    закрывает соединение (try/finally).
    """
    address = _mcp_address(payload)
    client = MCPClient.for_url(address)
    try:
        await client.connect()
        await client.initialize()
        tools = await client.list_tools()
        mcp_settings.save_address(address)
        return {
            "address": address,
            "tools": [tool.to_dict() for tool in tools],
        }
    except asyncio.CancelledError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to retrieve MCP tools: {_mcp_error(exc)}",
        ) from exc
    except Exception as exc:  # noqa: BLE001 - пользователю нужен читаемый текст ошибки
        raise HTTPException(
            status_code=400,
            detail=f"Failed to retrieve MCP tools: {_mcp_error(exc)}",
        ) from exc
    finally:
        await client.disconnect()


@app.get("/api/models")
async def get_models() -> Dict[str, Any]:
    """Возвращает список моделей из внешнего API."""
    config = config_manager.load_config()
    try:
        models = await api_client.list_models(config.get("api_url", ""), config.get("api_key", ""))
    except api_client.ApiError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    return {"models": models}


@app.get("/api/chats")
async def get_chats() -> Dict[str, Any]:
    """Возвращает список сохранённых чатов."""
    return {"chats": chats_manager.list_chats()}


@app.post("/api/chats")
async def post_chat(payload: ChatPayload) -> Dict[str, Any]:
    """Создаёт новый чат с указанной моделью."""
    config = config_manager.load_config()
    model = payload.model.strip() or config.get("default_model", "")
    if not model:
        raise HTTPException(status_code=400, detail="Не выбрана модель для нового чата.")
    chat = chats_manager.create_chat(model, payload.title or "Новый чат")
    return chat


@app.get("/api/chats/{chat_id}")
async def get_chat(chat_id: str) -> Dict[str, Any]:
    """Возвращает чат вместе с историей сообщений и статистикой токенов."""
    chat = chats_manager.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Чат не найден.")
    result = dict(chat)
    result["usage"] = chats_manager.chat_usage(chat)
    return result


@app.delete("/api/chats/{chat_id}")
async def delete_chat(chat_id: str) -> Dict[str, Any]:
    """Удаляет чат по идентификатору."""
    if not chats_manager.delete_chat(chat_id):
        raise HTTPException(status_code=404, detail="Чат не найден.")
    return {"ok": True}


@app.post("/api/chats/{chat_id}/clear")
async def clear_chat(chat_id: str) -> Dict[str, Any]:
    """Очищает историю сообщений чата."""
    if not chats_manager.clear_messages(chat_id):
        raise HTTPException(status_code=404, detail="Чат не найден.")
    return {"ok": True}


@app.get("/api/chats/{chat_id}/export")
async def export_chat(chat_id: str) -> Dict[str, Any]:
    """Экспортирует чат в формате Markdown."""
    chat = chats_manager.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Чат не найден.")
    lines: List[str] = [f"# {chat.get('title', 'Чат')}", "", f"Модель: `{chat.get('model', '')}`", ""]
    for message in chat.get("messages", []):
        role = "Пользователь" if message.get("role") == "user" else "Ассистент"
        lines.append(f"## {role}")
        lines.append("")
        lines.append(message.get("content", ""))
        lines.append("")
    return {"markdown": "\n".join(lines)}


@app.get("/api/requests/{request_id}")
async def get_request_log(request_id: str) -> Dict[str, Any]:
    """Возвращает JSON-лог запроса к внешнему API по его идентификатору."""
    if not request_logger.is_valid_request_id(request_id):
        raise HTTPException(status_code=400, detail="Недопустимый идентификатор запроса.")
    log = request_logger.load_request_log(request_id)
    if log is None:
        raise HTTPException(status_code=404, detail="Лог запроса не найден.")
    return log


@app.get("/api/logs")
async def get_logs(limit: int = 100) -> Dict[str, Any]:
    """Возвращает список логов запросов к внешнему API (свежие сверху).

    Из каждого файла берутся только метаданные — тело лога отдаётся
    отдельным эндпоинтом ``/api/requests/{request_id}``.
    """
    limit = max(1, min(limit, 500))
    files = sorted(
        request_logger.LOGS_DIR.glob("*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )[:limit]
    items: List[Dict[str, Any]] = []
    for path in files:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        response_part = data.get("response") or {}
        items.append(
            {
                "request_id": data.get("request_id") or path.stem,
                "timestamp": data.get("timestamp"),
                "chat_id": data.get("chat_id"),
                "model": data.get("model"),
                "api_url": data.get("api_url"),
                "status_code": response_part.get("status_code") if isinstance(response_part, dict) else None,
                "duration_ms": data.get("duration_ms"),
                "error": data.get("error"),
            }
        )
    return {"logs": items, "count": len(items)}


@app.get("/api/memory/{chat_id}")
async def get_memory(chat_id: str, user_id: str = DEFAULT_USER_ID) -> Dict[str, Any]:
    """Возвращает снимок всех слоёв памяти для чата (session_id = chat_id)."""
    if chats_manager.get_chat(chat_id) is None:
        raise HTTPException(status_code=404, detail="Чат не найден.")
    return memory_layers.memory_manager.snapshot(chat_id, user_id)


@app.delete("/api/memory/{chat_id}")
async def clear_memory(chat_id: str, user_id: str = DEFAULT_USER_ID) -> Dict[str, Any]:
    """Очищает краткосрочную и рабочую память чата (long-term не трогает)."""
    memory_layers.memory_manager.short_term.clear(chat_id)
    memory_layers.memory_manager.working.clear(chat_id)
    return {"ok": True, "long_term": memory_layers.memory_manager.read_long_term(user_id)}


# ---------------------------------------------------------------------------
# Эндпоинты дашборда памяти (/memory/*)
# ---------------------------------------------------------------------------


def _short_term_payload(session_id: str) -> Dict[str, Any]:
    """Формирует ответ по краткосрочной памяти: записи, счётчик, токены."""
    items = memory_layers.memory_manager.read_short_term(session_id)
    tokens = sum(memory_layers.estimate_tokens(item.get("content", "")) for item in items)
    return {"items": items, "count": len(items), "tokens": tokens}


def _working_payload(session_id: str) -> Dict[str, Any]:
    """Формирует ответ по рабочей памяти: данные задачи и число полей."""
    data = memory_layers.memory_manager.read_working(session_id)
    filled = [key for key, value in data.items() if value and key != "updated_at"]
    return {"data": data, "count": len(filled)}


def _long_term_payload(user_id: str) -> Dict[str, Any]:
    """Формирует ответ по долговременной памяти: факты и их количество."""
    items = memory_layers.memory_manager.read_long_term(user_id)
    return {"items": items, "count": len(items)}


@app.get("/memory/short-term")
async def memory_short_term(session_id: str) -> Dict[str, Any]:
    """Возвращает содержимое краткосрочной памяти сессии."""
    return _short_term_payload(session_id)


@app.get("/memory/working")
async def memory_working(session_id: str) -> Dict[str, Any]:
    """Возвращает содержимое рабочей памяти сессии."""
    return _working_payload(session_id)


@app.get("/memory/long-term")
async def memory_long_term(user_id: str = DEFAULT_USER_ID) -> Dict[str, Any]:
    """Возвращает содержимое долговременной памяти пользователя."""
    return _long_term_payload(user_id)


@app.get("/memory/snapshot")
async def memory_snapshot(
    session_id: str, user_id: str = DEFAULT_USER_ID
) -> Dict[str, Any]:
    """Возвращает все три слоя одним ответом (для одного запроса с фронта)."""
    manager = memory_layers.memory_manager
    return {
        "short_term": _short_term_payload(session_id),
        "working": _working_payload(session_id),
        "long_term": _long_term_payload(user_id),
        "enabled_layers": sorted(manager.enabled_layers),
        "last_update": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/memory/prompt-preview")
async def memory_prompt_preview(
    session_id: str, user_id: str = DEFAULT_USER_ID, message: str = ""
) -> Dict[str, Any]:
    """Возвращает собранный промт с пометкой источника каждого блока."""
    return memory_layers.memory_manager.prompt_preview(session_id, user_id, message)


@app.get("/memory/events")
async def memory_events(limit: int = 50) -> Dict[str, Any]:
    """Возвращает журнал маршрутизации записи по слоям."""
    events = memory_layers.memory_manager.events.read(limit=limit)
    return {"events": events, "count": len(events)}


@app.delete("/memory/events")
async def memory_events_clear() -> Dict[str, Any]:
    """Очищает журнал маршрутизации."""
    memory_layers.memory_manager.events.clear()
    return {"ok": True}

@app.post("/memory/working/collapse")
async def memory_collapse(payload: CollapsePayload) -> Dict[str, Any]:
    """«Схлопывает» рабочую память сессии в long-term и очищает её."""
    if not payload.session_id:
        raise HTTPException(status_code=400, detail="Не указан session_id.")
    saved = memory_layers.memory_manager.collapse_working(payload.session_id, payload.user_id)
    return {"ok": True, "saved": saved}


@app.delete("/memory/long-term/{fact_id}")
async def memory_delete_fact(fact_id: str) -> Dict[str, Any]:
    """Удаляет факт из долговременной памяти."""
    if not memory_layers.memory_manager.delete_long_term(fact_id):
        raise HTTPException(status_code=404, detail="Факт не найден.")
    return {"ok": True, "fact_id": fact_id}


@app.patch("/memory/toggles")
async def memory_toggles(payload: MemoryTogglesPayload) -> Dict[str, Any]:
    """Включает/выключает слои памяти для ablation-эксперимента."""
    memory_layers.memory_manager.set_enabled_layers(payload.layers)
    return {"enabled_layers": sorted(memory_layers.memory_manager.enabled_layers)}

def _sse(event: str, data: Dict[str, Any]) -> str:
    """Формирует SSE-сообщение с указанным типом события."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# ---------------------------------------------------------------------------
# MCP-инструменты в чате (function calling)
# ---------------------------------------------------------------------------


async def _load_mcp_tools() -> Tuple[Optional[MCPClient], List[MCPTool], List[Dict[str, Any]]]:
    """Подключается к MCP-серверу из настроек и возвращает инструменты.

    Мягкая деградация: если адрес не задан или сервер недоступен —
    возвращает ``(None, [], [])``, чат работает без инструментов.
    """
    address = mcp_settings.load_address()
    if not address:
        return None, [], []
    client = MCPClient.for_url(address)
    try:
        await client.connect()
        await client.initialize()
        tools = await client.list_tools()
        return client, tools, to_openai_tools(tools)
    except Exception:  # noqa: BLE001 - мягкая деградация
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass
        return None, [], []


def _tool_message(tool_call_id: str, content: str) -> Dict[str, Any]:
    """Формирует ``role: "tool"``-сообщение для модели."""
    return {"role": "tool", "tool_call_id": tool_call_id, "content": content}


async def _execute_tool_calls(
    client: MCPClient,
    tools: List[MCPTool],
    tool_calls: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Выполняет все tool_calls параллельно и возвращает role:"tool"-сообщения.

    Невозможные вызовы (неизвестный инструмент, невалидные аргументы,
    ошибка MCP) НЕ роняют чат: их результат передаётся модели как ошибка.
    """

    async def run_one(tool_call: Dict[str, Any]) -> Dict[str, Any]:
        tool_call_id = tool_call.get("id") or ""
        function = tool_call.get("function") or {}
        name = function.get("name") or ""
        raw_arguments = function.get("arguments") or "{}"
        try:
            arguments = (
                json.loads(raw_arguments)
                if isinstance(raw_arguments, str)
                else raw_arguments
            )
        except ValueError:
            arguments = {}

        tool = find_tool(tools, name)
        if tool is None:
            return _tool_message(tool_call_id, f"Unknown tool: {name}")

        ok, error = validate_arguments(tool, arguments)
        if not ok:
            return _tool_message(
                tool_call_id,
                json.dumps(
                    {"error": "invalid_arguments", "message": error},
                    ensure_ascii=False,
                ),
            )

        try:
            result = await client.call_tool(name, arguments)
        except (Exception, asyncio.CancelledError) as exc:  # noqa: BLE001
            return _tool_message(
                tool_call_id,
                json.dumps(
                    {"error": "mcp_call_failed", "message": str(exc)},
                    ensure_ascii=False,
                ),
            )

        if result.get("structured_content") is not None:
            content = json.dumps(result["structured_content"], ensure_ascii=False)
        else:
            content = result.get("content", "")
        if result.get("is_error") and not content:
            content = json.dumps(
                {"error": "mcp_tool_error", "message": "Инструмент вернул ошибку без содержимого"},
                ensure_ascii=False,
            )
        return _tool_message(tool_call_id, content)

    # Инструменты одного ответа модели выполняются параллельно;
    # порядок сообщений сохраняется порядком исходного списка tool_calls.
    return list(await asyncio.gather(*(run_one(tc) for tc in tool_calls)))


@app.post("/api/chats/{chat_id}/messages")
async def post_message(chat_id: str, payload: MessagePayload) -> StreamingResponse:
    """Принимает сообщение пользователя и стримит ответ ассистента через SSE."""
    chat = chats_manager.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Чат не найден.")

    content = (payload.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="Сообщение не может быть пустым.")

    config = config_manager.load_config()
    api_url = config.get("api_url", "")
    api_key = config.get("api_key", "")
    model = chat.get("model") or config.get("default_model", "")

    is_first_message = len(chat.get("messages", [])) == 0
    user_index = len(chat.get("messages", []))
    request_id = request_logger.generate_request_id()
    chats_manager.add_message(chat_id, "user", content, request_id=request_id)
    if is_first_message:
        chats_manager.set_title(chat_id, chats_manager.auto_title(content))

    # --- Память агента -------------------------------------------------
    user_id = payload.user_id or DEFAULT_USER_ID
    manager = memory_layers.memory_manager
    if payload.memory_layers is not None:
        manager.set_enabled_layers(payload.memory_layers)
    else:
        manager.set_enabled_layers(list(memory_layers.LAYERS))

    # 1. Роутер решает, куда писать реплику пользователя.
    decision = manager.route_and_store(chat_id, user_id, content)
    # 2. Реплика пользователя всегда попадает в short-term (история диалога).
    manager.add_short_term(chat_id, {"role": "user", "content": content})
    # 3. Завершение задачи «схлопывается» в long-term.
    collapsed: Optional[Dict[str, Any]] = None
    if memory_layers.is_task_completed(content):
        collapsed = manager.collapse_working(chat_id, user_id)

    # 4. Сборка промта: system + long-term + working + short-term + текущий вопрос.
    messages = manager.build_prompt_messages(chat_id, user_id, content)
    memory_snapshot = manager.snapshot(chat_id, user_id)

    # --- MCP-инструменты (function calling) ------------------------------
    # Подключаемся к MCP-серверу из настроек страницы «Подключение к MCP».
    # Если сервер недоступен — чат работает без инструментов (мягкая деградация).
    mcp_client, mcp_tools, openai_tools = await _load_mcp_tools()

    request_body = api_client.build_request_body(model, messages, openai_tools or None)
    started_at = time.time()

    def write_log(
        status_code: Optional[int],
        response_body: Optional[Dict[str, Any]],
        error: Optional[str],
    ) -> None:
        """Сохраняет лог запроса к внешнему API в отдельный JSON-файл."""
        log_data = {
            "request_id": request_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "chat_id": chat_id,
            "model": model,
            "api_url": api_url,
            "request": {
                "method": "POST",
                "endpoint": "/chat/completions",
                "headers": api_client.masked_headers(api_key),
                "body": request_body,
            },
            "response": (
                {"status_code": status_code, "body": response_body}
                if status_code is not None
                else None
            ),
            "duration_ms": int((time.time() - started_at) * 1000),
            "error": error,
        }
        try:
            request_logger.save_request_log(request_id, log_data)
        except (OSError, ValueError):
            pass

    async def event_stream():
        """Генерирует SSE-события: start, memory, delta, usage, done или error."""
        yield _sse("start", {"model": model, "request_id": request_id})
        yield _sse(
            "memory",
            {
                "decision": decision.to_dict(),
                "collapsed": collapsed,
                "snapshot": memory_snapshot,
            },
        )
        collected = ""
        usage: Dict[str, Any] = {}
        status_code: Optional[int] = None
        response_body: Optional[Dict[str, Any]] = None
        try:
            # Цикл function calling: пока модель просит инструменты —
            # выполняем их через MCP-сервер и возвращаем результаты.
            for tool_round in range(1, MAX_TOOL_ROUNDS + 1):
                round_meta: Dict[str, Any] = {}
                async for chunk in api_client.stream_chat(
                    api_url, api_key, model, messages, openai_tools
                ):
                    chunk_type = chunk.get("type")
                    if chunk_type == "usage":
                        usage = chunk.get("usage") or {}
                        yield _sse("usage", {"usage": usage})
                        continue
                    if chunk_type == "meta":
                        status_code = chunk.get("status_code")
                        response_body = chunk.get("body")
                        round_meta = chunk
                        continue
                    content = chunk.get("content") or ""
                    if not content:
                        continue
                    collected += content
                    yield _sse("delta", {"content": content})

                finish_reason = round_meta.get("finish_reason")
                tool_calls = round_meta.get("tool_calls") or []
                if (
                    finish_reason == "tool_calls"
                    and tool_calls
                    and mcp_client is not None
                ):
                    names = [
                        (tc.get("function") or {}).get("name", "?") for tc in tool_calls
                    ]
                    yield _sse(
                        "tools",
                        {"round": tool_round, "tools": names, "count": len(names)},
                    )
                    messages.append(
                        {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": tool_calls,
                        }
                    )
                    tool_messages = await _execute_tool_calls(
                        mcp_client, mcp_tools, tool_calls
                    )
                    messages.extend(tool_messages)
                    continue
                break
        except api_client.ApiError as exc:
            if collected:
                chats_manager.add_message(
                    chat_id, "assistant", collected, usage or None, request_id
                )
            if usage:
                chats_manager.set_message_usage(chat_id, user_index, usage)
            write_log(exc.status_code, None, exc.message)
            yield _sse("error", {"message": exc.message, "request_id": request_id})
            return
        except Exception as exc:  # noqa: BLE001 - защита от неожиданных сбоев
            if collected:
                chats_manager.add_message(
                    chat_id, "assistant", collected, usage or None, request_id
                )
            if usage:
                chats_manager.set_message_usage(chat_id, user_index, usage)
            write_log(None, None, f"Непредвиденная ошибка: {exc}")
            yield _sse("error", {"message": f"Непредвиденная ошибка: {exc}", "request_id": request_id})
            return
        finally:
            if mcp_client is not None:
                try:
                    await mcp_client.disconnect()
                except Exception:  # noqa: BLE001
                    pass

        if collected:
            chats_manager.add_message(
                chat_id, "assistant", collected, usage or None, request_id
            )
            # Ответ ассистента тоже попадает в краткосрочную память.
            manager.add_short_term(chat_id, {"role": "assistant", "content": collected})
        if usage:
            chats_manager.set_message_usage(chat_id, user_index, usage)
        write_log(status_code, response_body, None)
        chat_after = chats_manager.get_chat(chat_id) or {}
        yield _sse(
            "done",
            {
                "content": collected,
                "usage": usage,
                "chat_usage": chats_manager.chat_usage(chat_after),
                "request_id": request_id,
                "memory": manager.snapshot(chat_id, user_id),
            },
        )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _open_browser() -> None:
    """Открывает браузер на локальном адресе приложения."""
    webbrowser.open(f"http://{HOST}:{PORT}")


if __name__ == "__main__":
    import uvicorn

    threading.Timer(1.5, _open_browser).start()
    uvicorn.run("main:app", host=HOST, port=PORT, reload=False)
