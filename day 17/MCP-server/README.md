# MCP Gateway

Локальный **MCP Gateway / MCP Server**: единая точка входа, через которую локальный AI-агент
обращается к внешним API (Weather, GitHub и любым другим) по протоколу [MCP](https://modelcontextprotocol.io).

```
AI Agent
   |
   | MCP (Streamable HTTP / stdio)
   v
MCP Gateway  (Fastify + MCP SDK)
   |
   +---- ProviderRegistry
            |
            +---- Weather Provider (Open-Meteo, без API key)
            |
            +---- GitHub Provider (Personal Access Token, опционально)
            |
            +---- Gismeteo Provider (требуется API token)
            |
            +---- Ваши провайдеры (docs/creating-provider.md)
```

Каждый API — это отдельный **плагин/провайдер**, реализующий общий интерфейс `ApiProvider`.
Ядро не знает деталей конкретных API: всё (схема конфигурации, tools, credentials, валидация,
HTTP-запросы, преобразование ответов, health check) живёт внутри провайдера.

## Возможности

- **MCP endpoint** `http://127.0.0.1:3000/mcp` (Streamable HTTP) + **stdio**-транспорт для Claude Desktop.
- **Без авторизации** по умолчанию, слушает только `127.0.0.1`; архитектура готова к добавлению auth middleware.
- **Административный Web UI** (React): Dashboard, провайдеры, лог-журнал, настройки.
- **Динамические MCP tools**: собираются из подключённых провайдеров; отдельные tools можно
  отключать — отключённые не объявляются MCP-клиенту и не вызываются.
- **Конфигурация в JSON** (`config/`), редактируется только через backend REST API; секреты маскируются.
- **Полный журнал запросов** AI → MCP → API (`data/logs/YYYY-MM-DD.jsonl`) с редaкцией credentials.
- **Hot reload**: изменения конфигурации применяются без перезапуска сервера.
- **Tests**, **CLI validate-config**, **Docker**.

Провайдеры из коробки: Open-Meteo (без ключа), GitHub (PAT опционально), Gismeteo (токен обязателен).

## Быстрый старт

```bash
npm install

# разработка (backend + Web UI c HMR)
npm run dev
#  Web UI:  http://127.0.0.1:5173  (проксирует /api и /mcp на :3000)

# production
npm run build
npm start
#  Web UI + MCP endpoint: http://127.0.0.1:3000
```

После запуска откройте Web UI, введите GitHub token на странице `/providers/github` →
**Credentials**, нажмите **Test connection**, затем подключите MCP-клиент.

## MCP-клиенты

### Claude Desktop (stdio)

Добавьте в `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "mcp-gateway": {
      "command": "node",
      "args": ["/АБСОЛЮТНЫЙ/ПУТЬ/к/mcp-gateway/dist/src/server/mcp-stdio.js"]
    }
  }
}
```

(или режим разработки: `args: ["/путь/node_modules/.bin/tsx", "/путь/src/server/mcp-stdio.ts"]`)

### Claude Code (HTTP или stdio)

```bash
claude mcp add --transport http gateway http://127.0.0.1:3000/mcp
# или stdio:
claude mcp add gateway -- node "$(pwd)/dist/src/server/mcp-stdio.js"
```

### Cline / Continue / другие HTTP-клиенты

Укажите URL MCP-сервера: `http://127.0.0.1:3000/mcp` (Streamable HTTP, без авторизации).

### MCP Inspector

```bash
npx @modelcontextprotocol/inspector --url http://127.0.0.1:3000/mcp
```

Проверить вручную:

```bash
npm run mcp-stdio   # stdio: ждёт JSON-RPC на stdin
```

## Web UI

| Страница | Описание |
|---|---|
| `/` | Dashboard: статус сервера, MCP endpoint, статистика запросов, последние вызовы |
| `/providers` | Список API: статус, health, tools, Test connection, Enable/Disable |
| `/providers/:id` | General / Credentials / Tools: настройки, секреты (маска + password input), включение/выключение tools |
| `/logs` | Журнал запросов: поиск, фильтры, пагинация, детали, Clear logs |
| `/settings` | Настройки сервера (host/port — после перезапуска) |

## Конфигурация

Всё хранится в локальных JSON-файлах; **backend — единственный компонент, который их читает и пишет**.

```text
config/
  server.json              # настройки сервера
  credentials.json         # СЕКРЕТЫ (не попадает в git!): {"github":{"token":"..."}}
  credentials.example.json # шаблон структуры секретов (безопасно коммитить)
  providers/
    weather.json
    github.json
    gismeteo.json          # показывает здоровье API только после ввода token
data/
  logs/                    # YYYY-MM-DD.jsonl — журнал запросов
```

```jsonc
// config/providers/github.json
{
  "id": "github",
  "enabled": true,
  "name": "GitHub",
  "baseUrl": "https://api.github.com",
  "credentials": { "token": "" },     // Personal Access Token
  "settings": { "timeout": 10000 },
  "tools": {
    "github_create_issue": { "enabled": false },   // отключённый tool
    "github_search_repositories": { "enabled": true }
  }
}
```

> ⚠️ **Секреты хранятся отдельно**: все API-keys/tokens живут в `config/credentials.json`
> (формат: `{ "<providerId>": { "<key>": "<value>" } }`), а не в файлах провайдеров.
> Этот файл добавлен в `.gitignore` и **не попадает в git**; при старте сервер автоматически
> переносит секреты из старых конфигов провайдеров в `credentials.json` и очищает их.
> Шаблон структуры — `config/credentials.example.json`. Права файла: 0600 (чтение только владельцем).
>
> Web UI маскирует секреты и никогда не возвращает их через API.

### Environment variables (переопределяют JSON)

```bash
MCP_HOST=127.0.0.1
MCP_PORT=3000
MCP_LOG_LEVEL=info
MCP_LOG_RETENTION_DAYS=7
MCP_MAX_RESPONSE_LOG_SIZE=65536
MCP_REQUEST_TIMEOUT_MS=15000
MCP_DEFAULT_RETRY_COUNT=2
MCP_DEBUG=false
MCP_CONFIG_DIR=./config   # переопределить расположение
MCP_DATA_DIR=./data
```

Credentials можно задать через env — значение из env имеет приоритет и помечается в UI
как «from env» (редактирование через UI недоступно):

```bash
GITHUB_TOKEN=ghp_...   # для GitHub provider
GISMETEO_TOKEN=...     # для Gismeteo provider (обязателен)
```

## Безопасность и секреты

- Сервер слушает **только `127.0.0.1`** по умолчанию.
- Секреты **никогда не логируются**: `Authorization`, cookies, API keys, токены в query и телах
  заменяются на `[REDACTED]` до записи в файл; размеры тел ограничены `maxResponseLogSize` (64 КБ по умолчанию).
- REST API возвращает только **маску** секрета (`ghp_****...abcd`).
- Валидируются JSON-конфигурация и входные данные tools; ограничен размер тела запроса (1 MiB);
  защита от path traversal в id провайдеров; security headers; CORS настраивается в `/settings`
  (по умолчанию разрешены только локальные dev-ориджины).
- В MCP-ответ AI-агенту не попадают stack trace: разделяются категории ошибок
  (invalid input, external API, auth, rate limit, timeout, internal).

## Rate limits

`429` (и `403` с `X-RateLimit-Remaining: 0`) преобразуются в ошибку категории `rate_limit`
с заголовком `Retry-After`, попадают в лог и возвращаются MCP-клиенту понятным текстом
(«Retry after 60s»). Архитектура (`HttpClient`) готова к добавлению автоматического rate limiting.

## Проверка конфигурации и тесты

```bash
npm run validate-config   # проверка config/ без запуска сервера
npm run test              # vitest: registry, weather, github, redaction/logging, mcp
```

## Docker

```bash
docker compose up -d --build
# конфигурация: ./config:/app/config, данные: ./data:/app/data
# порт проброшен ТОЛЬКО на 127.0.0.1:3000
```

## Добавление нового API

См. [docs/creating-provider.md](docs/creating-provider.md) — полный пример.
Коротко: создайте `providers/my_api/{provider.ts,tools.ts,schema.ts}`, зарегистрируйте класс
в `providers/index.ts`. Registry сам создаст дефолтный конфиг, покажет провайдера в UI
и зарегистрирует tools в MCP — ядро не переписывается.

## Структура проекта

```text
src/
  core/
    config/       # ConfigManager, validation (zod), защита путей
    logging/      # Logger, RequestLogger (JSONL), retention, redaction
    http/         # HttpClient: timeout, retries, backoff, ошибки, логирование
    providers/    # ApiProvider, BaseProvider, ConfigSchema
    registry/     # ProviderRegistry: загрузка, init, tools, маршрутизация
    util/         # redact/mask/safeStringify
  server/         # Fastify: REST API, /mcp, статика Web UI, CLI
  cli/            # validate-config
providers/
  weather/        # Open-Meteo (без API key)
  github/         # GitHub REST API (PAT)
  gismeteo/       # Gismeteo Weather API v2 (требуется token)
web/              # React + Vite Web UI (workspace-пакет)
config/           # JSON-конфигурация по умолчанию
data/logs/        # JSONL-логи запросов
tests/            # vitest
docs/
  creating-provider.md
```

Выбрана простая структура «single TypeScript program» с логическим разделением
(`core` / `providers` / `web` / `config` / `data`) вместо monorepo: для локального инструмента это
даёт сборку и запуск одной командой без координации версий пакетов, сохраняя плагинную
архитектуру (добавление провайдера = новый модуль + строка в реестре).

## Технологии

TypeScript, Node.js 20+, Fastify, официальный MCP SDK (`@modelcontextprotocol/sdk`), zod,
React 19 + Vite, vitest. Без базы данных — конфигурация в JSON, логи в JSONL-файлах.

## Ограничения / планы

- Внешние plugins (npm-пакеты slack/notion/jira) не устанавливаются динамически в v1,
  но интерфейс `ProviderRegistry.registerProviderClass()` и контракт `ApiProvider` это позволяют.
- Authentication middleware не включена (только локальный запуск); точка интеграции —
  `onRequest`-хук в `src/server/app.ts` (см. комментарий «auth»).
- Автоматическое rate limiting — future work поверх `HttpClient`.