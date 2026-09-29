# Pipelines

Pipeline — это **композиция MCP tools**: output каждого шага передаётся следующему шагу
через шаблоны. Pipeline выполняются через тот же ProviderRegistry/core tools, что и обычные
MCP-вызовы (без собственных HTTP-клиентов), могут запускаться вручную, через Scheduler
и через MCP tool `run_pipeline`.

## Пример: github-summary

```json
{
  "id": "github-summary",
  "name": "GitHub Issues Summary",
  "description": "github_list_issues → summarize → saveToFile",
  "steps": [
    { "id": "getIssues", "tool": "github_list_issues",
      "input": { "owner": "{{input.owner}}", "repo": "{{input.repo}}" } },
    { "id": "summary", "tool": "summarize",
      "input": { "data": "{{steps.getIssues.output}}" } },
    { "id": "save", "tool": "saveToFile",
      "input": { "filename": "{{input.repo}}-summary.txt",
                 "content": "{{steps.summary.output.summary}}" } }
  ]
}
```

Запуск через MCP:

```
run_pipeline { "pipeline": "github-summary", "input": { "owner": "octocat", "repo": "hello-world" } }
```

или через REST: `POST /api/pipelines/github-summary/run` с `{"input": {...}}`.

## Шаблоны (TemplateResolver)

- `{{input.owner}}` — входные данные pipeline;
- `{{steps.<id>.output}}` — выход предыдущего шага (object/array передаются как есть, не как "[object Object]");
- `{{steps.<id>.output.path}}`, `{{steps.<id>.output.items[0].title}}` — вложенные пути и индексы;
- встроенные шаблоны в строках рендерятся текстом (объекты — как JSON).

Запрещено: `eval`/`Function`/произвольный код. Ссылки валидируются заранее
(шаг должен существовать и быть объявлен **раньше**).

## Безопасность `saveToFile`

Запись разрешена только в `data/output/`; запрещены `../`, абсолютные пути,
побег из каталога; максимум 1 МиБ (`src/core/files/output-file.ts`).

## REST API Pipelines

```text
GET    /api/pipelines                     список
POST   /api/pipelines                     создать
POST   /api/pipelines/demo                создать демо (github-summary, weather-snapshot)
GET    /api/pipelines/:id
PUT    /api/pipelines/:id
DELETE /api/pipelines/:id
POST   /api/pipelines/:id/run             запустить с {"input": {...}}
GET    /api/pipelines/:id/history         история выполнений
GET    /api/pipeline-executions/:executionId
```

История хранит только статусы шагов + безопасную ошибку (без output'ов и сырых входов).

## Scheduler + Pipelines

Scheduled task может иметь `action.type = "pipeline"`:

```json
{
  "name": "Hourly GitHub summary",
  "schedule": { "type": "cron", "cron": "0 * * * *", "timezone": "UTC" },
  "action": { "type": "pipeline", "pipeline": "github-summary",
              "input": { "owner": "octocat", "repo": "hello-world" } }
}
```

Задачу можно создать в Web UI (Scheduled Tasks → Create task → Action type = Pipeline)
или через API/MCP. Используется **существующий Scheduler**: никакого отдельного планировщика нет.

## Ошибки

- LLM не настроен → шаг `summarize` падает с `LLM is not configured...`, остальные шаги получают
  статус `skipped`, выполнение — `failed` с `failedStep`; периодическая задача остаётся active.
- Неизвестный tool/ссылка отсекаются валидатором до запуска.