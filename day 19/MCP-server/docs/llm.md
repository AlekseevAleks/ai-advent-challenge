# LLM configuration

MCP Gateway умеет использовать **OpenAI / OpenAI-compatible API** через абстракцию
`LLMProvider` → `OpenAIProvider` → `LLMService`. Настройки хранятся **только на backend**
в `data/llm.json` (файл с реальным API key добавлен в `.gitignore`; шаблон — `data/llm.example.json`).

## Как настроить

1. Откройте **LLM Settings** в Web UI (`/settings/llm`).
2. Введите **API URL** (по умолчанию `https://api.openai.com/v1`; для OpenAI-compatible
   серверов — их базовый URL, например `https://your-proxy.example/v1`).
3. Введите **API Key** (password input; после сохранения ключ никогда не отображается).
4. Нажмите **Проверить** — backend выполнит реальный `GET {apiUrl}/models` с `Authorization: Bearer <key>`.
5. После успешной проверки поле **Model** станет доступным: список моделей загружается
   через `GET {apiUrl}/models` (не хардкодится). Модель можно выбрать из списка **или ввести вручную**
   (работает даже если модели нет в `/models`).
6. Нажмите **Сохранить** — настройки запишутся в `data/llm.json`.

## REST API

```text
GET  /api/settings/llm          -> безопасные настройки {provider, apiUrl, model, configured} (без apiKey)
POST /api/settings/llm/check    -> реальная проверка ({apiUrl?, apiKey?, model?} -> {ok, status, message})
POST /api/settings/llm/models   -> список моделей из /models
PUT  /api/settings/llm          -> сохранить ({apiUrl?, apiKey?, model?}; apiKey='' означает "не менять")
```

После сохранения ответ `PUT` содержит только безопасное:
`{success, configured, provider, model}` — API key не возвращается.

## Использование: summarize

MCP tool `summarize` обращается к `LLMService` (не к OpenAI напрямую):

```json
{ "data": { "issues": [...] }, "instruction": "Перечисли главное кратко" }
```

Ответ: `{ "summary": "..." }`. Если LLM не настроен — понятная ошибка
`LLM is not configured. Configure OpenAI in Settings → LLM.`

Эту же настройку использует pipeline-шаг `summarize` (см. `docs/pipelines.md`).

## Безопасность

- API key не попадает в git (`.gitignore` → `data/llm.json`), в frontend bundle,
  в GET-ответы, в логи и в ошибки.
- Логи LLM содержат только `provider`/`model`/status/duration — не prompt и не ответ.
- LLM-запросы имеют таймаут (берётся из настроек сервера, минимум 30 с).