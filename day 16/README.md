# MCP Server

Демонстрационный MCP-сервер (Model Context Protocol) проекта AI Chat.
Служит для проверки минимального MCP-клиента: запускается как локальный
subprocess и общается с клиентом через **stdio** transport.

> Это учебный проверочный компонент. Он не интегрирован с AI-чатом,
> памятью или другими механизмами приложения.

## Требования

- Python **3.10+** (MCP SDK не поддерживает более старые версии)
- Пакет `mcp` — установлен в локальном окружении `mcp_server/.venv`
  (создаётся через `python -m venv .venv && .venv/bin/pip install "mcp>=1.0.0"`)

Виртуальное окружение `mcp_server/.venv` исключено из системы контроля версий
(см. `.gitignore`).

## Инструменты

| Имя               | Параметры       | Описание                                    |
|-------------------|-----------------|---------------------------------------------|
| `echo`            | `message: str`  | Возвращает переданное сообщение без изменений |
| `add`             | `a: number`, `b: number` | Возвращает сумму двух чисел         |
| `get_current_time`| —               | Возвращает текущее время UTC в формате ISO 8601 |

Инструменты используются только для проверки `list_tools()` — их вызов
клиентом на этом этапе не реализован.

## Запуск

Сервер рассчитан на запуск MCP-клиентом как subprocess (stdio). Полный
сценарий проверки (start → connect → initialize → list_tools → disconnect)
выполняется из каталога `mcp_server`:

```bash
cd mcp_server
.venv/bin/python test_mcp_connection.py
```

Либо с активацией окружения:

```bash
cd mcp_server
source .venv/bin/activate   # Windows: .venv\Scripts\activate
python test_mcp_connection.py
```

Тест использует MCP-клиент из проекта `ai_chat` (`ai_chat/app/mcp`) — его
каталог подключается автоматически через `sys.path`.

Ожидаемый результат: соединение установлено, `initialize` успешен,
`list_tools()` возвращает 3 инструмента, соединение корректно закрыто.

Прямой запуск сервера (он будет ожидать JSON-RPC сообщения в stdin):

```bash
cd mcp_server
.venv/bin/python mcp_server.py
```

Либо с активацией окружения:

```bash
cd mcp_server
source .venv/bin/activate   # Windows: .venv\Scripts\activate
python mcp_server.py
```

## Быстрая проверка сервера

Подать серверу один JSON-RPC запрос `initialize` через stdin:

```bash
printf '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"probe","version":"0.1"}}}\n' \
  | python mcp_server.py
```

В ответ сервер должен вернуть `serverInfo`, `protocolVersion` и список
capabilities.

## Интеграция с клиентом

Клиент (`ai_chat/app/mcp/client.py`) запускает этот скрипт командами
`sys.executable mcp_server.py` (интерпретатором своего окружения
`ai_chat/.venv`) и подключается к нему через `stdio_client` +
`ClientSession` из официального MCP SDK. Локальное окружение
`mcp_server/.venv` предназначено для автономного запуска сервера.