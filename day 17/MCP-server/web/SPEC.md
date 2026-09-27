# Web UI — MCP Gateway (спецификация для реализации)

Реализуй **полноценную административную Web UI** для MCP Gateway (React 19 + TypeScript + Vite).
Все файлы создаются **только внутри `web/`**. Backend уже готов и соответствует контракту ниже.

Проверка готовности: `npm run build:web` (tsc --noEmit + vite build) должен проходить без ошибок.

---

## 1. Стек и ограничения

- React 19, react-router-dom v7 (BrowserRouter, Routes, Route, NavLink, Link, useNavigate, useParams, useSearchParams).
- Никаких UI-библиотек и иконок из npm — только свои компоненты и inline-SVG.
- Один файл стилей `web/src/styles.css` с CSS-переменными; темы dark/light через `data-theme` на `<html>` (в `index.html` уже стоит `data-theme="dark"`).
- Vite-прокси `/api` и `/mcp` на `127.0.0.1:3000` уже настроен в `web/vite.config.ts` — не трогай его.
- Типизация строгая (`strict` включён, noUnusedLocals).

Структура файлов (можно расширять мелкими утилитами):

```
web/src/
  main.tsx            — корень, BrowserRouter, <App/>
  App.tsx             — Layout + Routes
  api/client.ts       — fetch-обёртка: JSON, ошибки, toast на ошибки
  api/types.ts        — типы контракта (см. ниже)
  components/
    Layout.tsx        — sidebar + main; sidebar: логотип, пункты Dashboard/APIs/Logs/Settings, список провайдеров в APIS, переключатель темы
    ui.tsx            — Badge, Button, Card, Spinner, EmptyState, ErrorState, Toggle, Tabs, Modal, ConfirmDialog, CopyButton, JsonView, Stat, Toast (контекст/провайдер)
  pages/
    Dashboard.tsx
    Providers.tsx
    ProviderDetail.tsx
    Logs.tsx
    Settings.tsx
  styles.css
```

## 2. API-контракт (backend реализован, НЕ меняй сервер)

Базовый URL: `/api`. Ошибки: HTTP-статус + `{"error":{"code","kind?","message","retryAfter?"}}`.

```ts
// api/types.ts — скопируй эти определения
export interface ServerStatus {
  ok: boolean; name: string; version: string; running: boolean;
  host: string; port: number; mcpEndpoint: string; webUi: string; uptimeSeconds: number;
  providers: { total: number; enabled: number; disabled: number };
  tools: { total: number; enabled: number };
  requests: { today: number; errorsToday: number; avgLatencyMs: number };
  lastRequests: LogEntry[];
}
export interface ConfigField {
  key: string; label: string; type: 'string' | 'number' | 'boolean';
  description?: string; default?: string | number | boolean; required?: boolean;
  secret?: boolean; env?: string; unit?: string; placeholder?: string;
}
export interface ConfigSchema {
  fields: ConfigField[]; settingsFields: ConfigField[]; credentialFields: ConfigField[];
}
export interface CredentialState { value: string; set: boolean; overridden: boolean; env?: string }
export interface ProviderHealth {
  status: 'ok' | 'error' | 'unknown'; message?: string; checkedAt?: string;
  durationMs?: number; statusCode?: number;
}
export interface ProviderRuntimeTool {
  name: string; description: string;
  inputSchema: { type: 'object'; properties?: Record<string, unknown>; required?: string[]; additionalProperties?: boolean };
  enabled: boolean; settings: Record<string, unknown>;
}
export interface ProviderRuntimeState {
  id: string; name: string; description: string; version: string; enabled: boolean; baseUrl?: string;
  configSchema: ConfigSchema; settings: Record<string, unknown>;
  credentials: Record<string, CredentialState>;
  health: ProviderHealth; tools: ProviderRuntimeTool[]; toolsCount: number; enabledToolsCount: number;
}
export interface LogErrorInfo { kind: string; code: string; message: string; retryAfter?: number }
export interface LogEntry {
  id: string; timestamp: string; direction: 'mcp' | 'test' | 'health';
  provider: string; providerName?: string; tool?: string; method: string;
  url: string; status?: number; durationMs?: number; success: boolean;
  error?: LogErrorInfo;
  request?: { headers?: Record<string, string>; body?: string; bodyTruncated?: boolean };
  response?: { headers?: Record<string, string>; body?: string; bodyTruncated?: boolean };
  attempts?: number;
}
export interface LogQueryResult { items: LogEntry[]; total: number; offset: number; limit: number }
export interface ServerSettingsResponse {
  host: string; port: number; logLevel: 'debug' | 'info' | 'warn' | 'error' | 'silent';
  logRetentionDays: number; maxResponseLogSize: number; requestTimeoutMs: number;
  defaultRetryCount: number; retryBackoffMs: number; corsEnabled: boolean;
  corsOrigins: string[]; debug: boolean;
}
```

| Метод | Путь | Тело / query | Ответ |
|---|---|---|---|
| GET | `/api/server/status` | — | `ServerStatus` |
| GET | `/api/health` | — | `{ok:true,version,uptimeSeconds}` |
| GET | `/api/providers` | — | `ProviderRuntimeState[]` |
| GET | `/api/providers/:id` | — | `ProviderRuntimeState` (404 если нет) |
| PUT | `/api/providers/:id` | `{enabled?, name?, baseUrl?, settings?, credentials?, tools?}` | `ProviderRuntimeState` |
| POST | `/api/providers/:id/enable` | — | `ProviderRuntimeState` |
| POST | `/api/providers/:id/disable` | — | `ProviderRuntimeState` |
| POST | `/api/providers/:id/test` | — | `ProviderHealth & {ok:boolean}` |
| GET | `/api/providers/:id/tools` | — | `ProviderRuntimeTool[]` |
| PUT | `/api/providers/:id/tools/:toolId` | `{enabled?, settings?}` | `ProviderRuntimeTool` |
| GET | `/api/logs` | `search, provider, tool, status, result=success\|error\|all, from, to, offset, limit` | `LogQueryResult` |
| GET | `/api/logs/:id` | — | `LogEntry` |
| DELETE | `/api/logs` | `{"confirm": true}` | `{deleted:number}` |
| GET | `/api/server/settings` | — | `ServerSettingsResponse` |
| PUT | `/api/server/settings` | частичные поля | `ServerSettingsResponse & {restartRequired:string[]}` |

Кредициальные правила (важно):
- Backend **никогда не возвращает полный секрет** — только маску (`ghp_********abcd`), `overridden:true`, если значение пришло из env, и `env` — имя переменной.
- При сохранении: `credentials: { token: "<новое значение>" }`; пустая строка удаляет секрет. Маску НЕ отправляй обратно.
- Если `overridden === true` — поле read-only, показывай бейдж «from env GITHUB_TOKEN».

## 3. Страницы

### Dashboard `/`
- Карточка «Server»: зелёная точка + «Running», uptime, версия.
- «MCP endpoint»: `mcpEndpoint` + кнопка Copy.
- Статы: Providers (enabled/disabled), Tools (enabled), Requests today, Errors today, Average latency (из `status.requests`).
- Сетка карточек провайдеров: имя, бейдж Enabled/Disabled, бейдж health (ok зелёный / error красный / unknown серый), toolsCount, кнопка «Open».
- «Last requests»: таблица последних `lastRequests` (время, направление MCP → Provider, tool, метод, URL-путь, status, duration) — строка кликабельна → `/logs?id=<id>`.

### Providers `/providers` (в sidebar подпись «APIs»)
- Таблица: Name (связь на деталь), ID, Status (Enabled/Disabled), Health (● ок / ● error / — unknown + last check), Tools (X/Y), Base URL, Actions: [Settings] [Test connection] [Enable|Disable].
- Test connection: кнопка в loading; результат в toast + обновление health-бейджа.
- Enable/Disable: перезапрос списка. Disable — без confirm (обратимо), Enable — просто.
- Пустое состояние: «No providers».

### Provider detail `/providers/:id`
Хедер: имя, id, версия, описание, бейджи Enabled/Health, кнопки [Enable|Disable], [Test connection].
Табы (вкладки через `?tab=`): General | Credentials | Tools.

**General** — форма по `configSchema.fields` + `configSchema.settingsFields`:
- `fields`: name (string), baseUrl (string) — input.
- `settingsFields`: timeout (number, unit ms) и т.п. — input number.
- Поля рендерь по `field.type`; для number — `type=number` с суффиксом unit.
- Кнопка Save → PUT `/api/providers/:id` с `{name?, baseUrl?, settings?}` → toast.

**Credentials** — для каждого `configSchema.credentialFields`:
- label, текущая маска (`credentials[key].value`), бейдж «from env» при overridden, иначе input `type=password` с placeholder «Введите новый …» + кнопки [Show <-> Hide] (показывает/скрывает ВВОД, не значение) и [Save].
- Save → `credentials: { [key]: value }` (пустое поле игнорировать) → toast; после сохранения замени маску на новую (из ответа).

**Tools** — список `tools` карточками:
- Название, description, Toggle включается/выключается → PUT `tools/:toolId` `{enabled}` (переключатель с локальным pending-состоянием; возвращать предыдущее при ошибке).
- «Input schema»: компактный список `properties` (key: type, required-звёздочка), JSON Schema свернуть в `<details>`.
- Если выключен — карточка приглушена, бейдж «Disabled».

### Logs `/logs`
- Хедер: заголовок, кнопка «Clear logs» (ConfirmDialog «Удалить все логи?» → DELETE `/api/logs` {confirm:true}).
- Фильтры (панель): search (text), provider (select из `/api/providers`), tool (select из tools выбранного провайдера, можно text с datalist), status (number input 100–599), result (select success|error|all), from/to (datetime-local).
- Таблица: Time, Direction (MCP → Provider / TEST / HEALTH), Provider, Tool, Method, URL (path only), Status, Duration. Клик — детали.
- Детали: Modal (или drawer) с GET `/api/logs/:id`: Request (timestamp, provider, tool, method, полный URL, headers, body — `<pre>`; значения [REDACTED] подсвечены), Response (status, headers, body, bodyTruncated → заметка «[Response truncated]»), Error (kind/code/message/retryAfter), Duration, Attempts. Кнопка Close.
- Поддержка `/?id=<id>` в URL → сразу открыть детали.
- Пагинация: Prev/Next + «X–Y of total», pageSize 50.
- Авто-обновление: кнопка Refresh + авто-refresh каждые 10 с (с остановкой при открытом модале — не критично).
- Пустое состояние «No log entries yet — вызовите tool через MCP».

### Settings `/settings`
- Форма полей `ServerSettingsResponse` (host, port, logLevel select, logRetentionDays, maxResponseLogSize (показывать в КБ, конвертировать в байты при PUT), requestTimeoutMs, defaultRetryCount, retryBackoffMs, corsEnabled toggle, corsOrigins (textarea, одна строка на origin), debug).
- Save → PUT (частичные изменённые поля) → toast «Saved»; если `restartRequired` непустой → предупреждение «Применится после перезапуска: host, port».

## 4. UI/UX требования

- Темы: dark (default, `data-theme="dark"`) и light; переключатель в sidebar; сохранение в localStorage; CSS через переменные: `--bg, --surface, --surface-2, --border, --text, --text-muted, --accent, --accent-2, --ok, --error, --warn`.
- Бейджи статусов: ок → зелёный, error → красный, disabled → серый, enabled → синий/акцентный.
- Toast: контекст `ToastProvider` (сообщение + тип success/error), авто-скрытие 4 с, стек справа вверху.
- Loading: скелеты/спиннеры на запросах списков; кнопки в pending-состоянии.
- ErrorState с кнопкой Retry; EmptyState с пояснением.
- Responsive: sidebar сворачивается в drawer на ширине < 900px (бургер в топбаре).
- Все числа/относительные времена форматируй аккуратно (Intl).
- Не добавляй лишних зависимостей. Только react, react-dom, react-router-dom.

## 5. Чек-лист завершения

1. `npm run build:web` — без ошибок TS и Vite.
2. `npm run typecheck` в корне — не должен сломаться (backend не трогаешь).
3. Быстрая ручная проверка (опционально, если удобно): `npm run dev` и открыть UI; backend при этом стартует сам. Если не получается — пропусти, главное сборка.