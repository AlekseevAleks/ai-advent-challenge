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
   |         |
   |         +---- Weather Provider (Open-Meteo, без API key)
   |         |
   |         +---- GitHub Provider (Personal Access Token, опционально)
   |         |
   |         +---- Gismeteo Provider (требуется API token)
   |         |
   |         +---- Ваши провайдеры (docs/creating-provider.md)
   |
   +---- Scheduler (Scheduled Tasks)
         |
         +---- TaskManager → TaskExecutor → ProviderRegistry
         |
         +---- SQLite (data/scheduler.db): задачи + история выполнений
```

Каждый API — это отдельный **плагин/провайдер**, реализующий общий интерфейс `ApiProvider`.
Ядро не знает деталей конкретных API: всё (схема конфигурации, tools, credentials, валидация,
HTTP-запросы, преобразование ответов, health check) живёт внутри провайдера.

Помимо запросов «здесь и сейчас» MCP Gateway умеет **выполнять задачи по расписанию**: AI-агент
создаёт задачу через MCP/Web UI, и сервер продолжает собирать данные сам (см. «Scheduled Tasks»).

## Возможности

- **MCP endpoint** `http://127.0.0.1:3000/mcp` (Streamable HTTP) + **stdio**-транспорт для Claude Desktop.
- **Без авторизации** по умолчанию, слушает только `127.0.0.1`; архитектура готова к добавлению auth middleware.
- **Административный Web UI** (React): Dashboard, провайдеры, лог-журнал, настройки.
- **Динамические MCP tools**: собираются из подключённых провайдеров; отдельные tools можно
  отключать — отключённые не объявляются MCP-клиенту и не вызываются.
- **Scheduled Tasks**: однократные и cron-задачи, которые выполняют существующие provider tools
  по расписанию (timezone-aware), сохраняют историю и агрегированные сводки в SQLite.
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

# другой порт (по умолчанию 3000, если параметр не указан):
npm start -- 4000
#  Web UI + MCP endpoint: http://127.0.0.1:4000
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
| `/scheduled-tasks` | Scheduled Tasks: список, создание/редактирование, демо-задачи |
| `/scheduled-tasks/:id` | Детали задачи: summary за период, история выполнений |
| `/scheduled-tasks-tools` | Scheduled Task Tools: включение/выключение MCP tools для работы с задачами |
| `/pipelines` | Pipelines: композиция tools, Run/Edit/Delete/History |
| `/settings/llm` | LLM Settings: OpenAI URL/key/model, проверка подключения, список моделей |
| `/logs` | Журнал запросов: поиск, фильтры, пагинация, детали, Clear logs |
| `/settings` | Настройки сервера (host/port — после перезапуска), Scheduler |

## Scheduled Tasks

Scheduler превращает MCP Gateway из «запрос-ответ» в сервер, который **работает по расписанию**: AI-агент
(или человек в Web UI) создаёт задачу один раз, и дальше сервер сам вызывает существующие **provider tools**
через ProviderRegistry — без отдельного HTTP-клиента и без участия агента.

```
AI: «Каждый день в 9:00 проверяй GitHub issues проекта torvalds/linux»
  → create_scheduled_task {
      name: "GitHub Linux Issues Daily",
      schedule: { type: "cron", cron: "0 9 * * *", timezone: "Europe/Berlin" },
      action: { provider: "github", tool: "github_list_issues",
                input: { owner: "torvalds", repo: "linux", state: "open", limit: 30 } }
    }
```

### Что умеет

- **Однократные задачи** (`once` + `executeAt`) и **cron-задачи** (`0 * * * *`, `*/30 * * * *`, `0 9 * * *`, ...)
  с IANA-таймзонами (`Europe/Berlin`, `Europe/Moscow`, `UTC`, ...).
- **Persistence в SQLite** `data/scheduler.db`: задачи и история переживают перезапуск сервера.
- **История выполнений** (TaskExecution): статус, длительность, результат, ошибка — с pagination.
- **Summary / агрегация**: по накопленным результатам считаются `count/min/max/avg/sum/latest`
  для каждого числового поля + категории + человекочитаемый текст (`get_task_summary`, вкладка Summary в UI).
- **Retry** упавших выполнений (настраиваемый, для `429` учитывается `Retry-After`).
- **Защита от двойного запуска**: атомарный `running`-флаг в БД; пропущенные cron-циклы «перескакиваются»,
  once-задача, просроченная на время простоя сервера, выполняется один раз при старте.

### Как создать задачу

**Через Web UI**: `/scheduled-tasks` → Create task → провайдер/tool (видно input-schema) → расписание → JSON-ввод → Save.
**Через MCP**: готовы 10 tools `create_scheduled_task`, `list_scheduled_tasks`, `get_scheduled_task`,
`update_scheduled_task`, `delete_scheduled_task`, `pause_scheduled_task`, `resume_scheduled_task`,
`run_scheduled_task_now`, `get_task_history`, `get_task_summary`.
**Настройка tools**: страница `/scheduled-tasks-tools` (или `GET/PUT /api/scheduler-tools`) —
можно включать/выключать отдельные scheduler tools для AI-агента; отключённые не объявляются
в MCP и не вызываются (настройка хранится в `config/scheduler-tools.json`).
**Демо**: кнопка «Create demo tasks» в Web UI или `npm run seed:scheduler` — создаёт
`demo-weather-berlin` (каждый час) и `demo-github-linux-issues` (каждые 30 минут).

```bash
npm run seed:scheduler      # один раз создаёт демо-задачи (идемпотентно)
```

### Как работает

```
Scheduler (таймер на ближайшую задачу + редкая страховочная проверка)
   ↓
TaskManager.executeDue → TaskExecutor
   ↓ (валидация provider/tool/enabled, retry)
ProviderRegistry.executeTool   ← тот же путь, что и MCP-вызовы
   ↓
Provider → HttpClient → внешний API
   ↓
результат → executions (история) → агрегация → get_task_summary
```

### REST API

```text
GET    /api/tasks
POST   /api/tasks
POST   /api/tasks/demo
GET    /api/tasks/:id
PUT    /api/tasks/:id
DELETE /api/tasks/:id
POST   /api/tasks/:id/pause
POST   /api/tasks/:id/resume
POST   /api/tasks/:id/run
GET    /api/tasks/:id/history
GET    /api/tasks/:id/summary?window=1h|24h|7d|30d|all
```

### Настройки (config/server.json → scheduler)

```jsonc
"scheduler": {
  "enabled": true,
  "tickIntervalMs": 60000,
  "maxStoredExecutionsPerTask": 1000,
  "executionRetentionDays": 30,
  "retry": { "enabled": true, "maxAttempts": 3, "delayMs": 5000 }
}
```

### Как добавить свой tool в расписание

Ничего специального делать не нужно: **любой существующий MCP tool провайдера автоматически доступен
для scheduled tasks**. Создаёте задачу с `provider`/`tool` — и она выполняется по расписанию.

### Безопасность

- Секреты из input/результатов задач не попадают в UI/history/summary: редaкция при отдаче через API.
- Логи выполнения содержат только taskId/taskName/provider/tool/status/duration.

## LLM configuration

MCP Gateway умеет использовать **OpenAI / OpenAI-compatible API** для `summarize` и pipeline-шага `summarize`.
Подробная инструкция — в `docs/llm.md`. Коротко:

1. Web UI → **LLM Settings** (`/settings/llm`);
2. введите **API URL** (по умолчанию `https://api.openai.com/v1`) и **API Key**;
3. нажмите **Проверить** — backend реально вызывает `GET {apiUrl}/models`;
4. после успешной проверки выберите модель из списка **или введите вручную** и нажмите **Сохранить**;
5. используйте MCP tool `summarize` (и `github-summary` pipeline).

Настройки хранятся только на backend в `data/llm.json` (в `.gitignore`; шаблон — `data/llm.example.json`).
API key никогда не возвращается через GET API, не логируется и не попадает в историю.
REST: `GET/PUT /api/settings/llm`, `POST /api/settings/llm/check`, `POST /api/settings/llm/models`.

## Pipelines

Pipelines — композиция MCP tools с передачей output между шагами (см. `docs/pipelines.md`):

```
github_list_issues → summarize → saveToFile
```

- MCP tool `run_pipeline` (`{pipeline, input}`); страница Web UI `/pipelines`;
- шаблоны `{{input.*}}` и `{{steps.<id>.output(.path)}}` (без eval);
- `saveToFile` пишет только в `data/output/` (защита от path traversal, лимит 1 МиБ);
- можно запускать по расписанию: в Scheduled Tasks выберите **Action type = Pipeline**;
- демо: `POST /api/pipelines/demo` или кнопка в UI (`github-summary`, `weather-snapshot`);
- история выполнений в SQLite `data/pipelines.db` (в `.gitignore`).

REST: `GET/POST /api/pipelines`, `PUT/DELETE /api/pipelines/:id`, `POST /api/pipelines/:id/run`,
`GET /api/pipelines/:id/history`, `GET /api/pipeline-executions/:executionId`.

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
npm run seed:scheduler    # создание демо-задач (один раз)
npm run test              # vitest: registry, weather, github, redaction/logging, mcp, scheduler
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
    scheduler/    # Scheduled Tasks: Scheduler, TaskManager, TaskExecutor, TaskStorage (SQLite),
                  # aggregation/ (GenericAggregator, human summary)
    util/         # redact/mask/safeStringify
  server/         # Fastify: REST API (в т.ч. /api/tasks), /mcp, статика Web UI, CLI
  cli/            # validate-config, seed-scheduler
providers/
  weather/        # Open-Meteo (без API key)
  github/         # GitHub REST API (PAT)
  gismeteo/       # Gismeteo Weather API v2 (требуется token)
web/              # React + Vite Web UI (workspace-пакет)
config/           # JSON-конфигурация по умолчанию
config/credentials.json   # секреты (не попадает в git)
data/logs/        # JSONL-логи запросов
data/scheduler.db # SQLite: scheduled tasks + история выполнений
tests/            # vitest (включая tests/scheduler/*)
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