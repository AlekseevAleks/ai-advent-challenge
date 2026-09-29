# Создание нового provider (плагина)

Добавление нового API сводится к созданию модуля в `providers/` и регистрации класса
в `providers/index.ts`. **Ядро MCP Gateway переписывать не нужно.**

```
providers/
  slack/            ← ваш новый API
    provider.ts     — класс провайдера (extends BaseProvider)
    tools.ts        — декларации MCP tools
    schema.ts       — zod-схемы входных данных + ConfigSchema + JSON Schema
    README.md       — документация провайдера (опционально)
```

## Шаг 1. Класс провайдера

Минимальный рабочий пример (по образцу `providers/weather` и `providers/github`):

```typescript
// providers/example/provider.ts
import type { ProviderConfig, ProviderToolConfig } from '../../src/core/types.js';
import type { ProviderHealth, ToolDefinition } from '../../src/core/providers/types.js';
import { BaseProvider } from '../../src/core/providers/base-provider.js';
import { userError } from '../../src/core/errors.js';
import { EXAMPLE_TOOLS, EXAMPLE_CONFIG_SCHEMA } from './schema.js';
import { exampleInputSchema } from './schema.js';

export class ExampleProvider extends BaseProvider {
  constructor(http: ConstructorParameters<typeof BaseProvider>[0]['http']) {
    super({
      id: 'example',
      name: 'Example API',
      description: 'Описание вашего API (видно в MCP и Web UI).',
      version: '1.0.0',
      http,
      defaultBaseUrl: 'https://api.example.com',
    });
  }

  override getConfigSchema() {
    return EXAMPLE_CONFIG_SCHEMA;      // поля форм в Web UI (General/Credentials)
  }

  override getDefaultConfig(): ProviderConfig {
    return {
      id: this.id,
      enabled: true,
      name: this.name,
      baseUrl: 'https://api.example.com',
      credentials: { apiKey: '' },         // секрет, маскируется в UI
      settings: { timeout: 10000 },
    };
  }

  override getCredentialEnv(): Record<string, string> {
    return { apiKey: 'EXAMPLE_API_KEY' };  // env-переопределение секрета
  }

  getTools(): ToolDefinition[] {
    return EXAMPLE_TOOLS;
  }

  async healthCheck(): Promise<ProviderHealth> {
    try {
      const res = await this.http.get<{ status: string }>(this.url('/health'), {
        timeoutMs: this.getTimeoutMs(),
        log: { provider: this.id, providerName: this.name, direction: 'health' },
      });
      return this.health('ok', `Connected (HTTP ${res.status})`, res.status);
    } catch (err) {
      return this.health('error', err instanceof Error ? err.message : String(err));
    }
  }

  async executeTool(toolName: string, input: unknown, _toolConfig: ProviderToolConfig): Promise<unknown> {
    switch (toolName) {
      case 'example_get_thing':
        return this.getThing(input);
      default:
        throw userError(`Unknown tool: ${toolName}`, 'UNKNOWN_TOOL');
    }
  }

  private async getThing(input: unknown): Promise<Record<string, unknown>> {
    const args = exampleInputSchema.parse(input); // zod-валидация; кидайте userError сами,
                                                  // если нужно своё сообщение
    const res = await this.http.get<Record<string, unknown>>(this.url('/things'), {
      query: { q: args.query },
      headers: { 'x-api-key': this.config.credentials?.apiKey ?? '' }, // секрет уходит только в запрос
      timeoutMs: this.getTimeoutMs(),
      log: { provider: this.id, providerName: this.name, tool: 'example_get_thing', direction: 'mcp' },
    });
    return { count: res.data.length ?? 0, items: res.data }; // понятный результат для AI
  }
}
```

Важно:

- **Не вызывайте `fetch()` напрямую.** Пользуйтесь `this.http.get/post/put/patch/delete` —
  это даёт таймаут, ретраи, обработку 429/Retry-After, ошибки и автоматическое логирование
  с редaкцией секретов.
- Передавайте `log:` во все запросы — иначе вызов не попадёт в страницу Logs.
- `errorMessageExtractor` опционален (пример — в GitHub provider).
- Не возвращайте в результат секреты — провайдер преобразует ответ API в безопасный результат.

## Шаг 2. Описание схем

`providers/example/schema.ts`:

```typescript
import { z } from 'zod';
import type { ConfigSchema, ToolInputSchema } from '../../src/core/providers/types.js';

export const EXAMPLE_CONFIG_SCHEMA: ConfigSchema = {
  fields: [
    { key: 'baseUrl', label: 'Base URL', type: 'string', required: true, description: 'Базовый URL API.' },
  ],
  settingsFields: [
    { key: 'timeout', label: 'Timeout', type: 'number', unit: 'ms', default: 10000 },
  ],
  credentialFields: [
    { key: 'apiKey', label: 'API Key', type: 'string', secret: true, env: 'EXAMPLE_API_KEY' },
  ],
};

export const exampleInputSchema = z.object({
  query: z.string().min(1).max(100),
  limit: z.number().int().min(1).max(100).optional(),
});

export const EXAMPLE_TOOLS: ToolDefinition[] = [
  {
    name: 'example_get_thing',
    description: 'Ищет thing по запросу.',
    inputSchema: {
      type: 'object',
      properties: {
        query: { type: 'string', description: 'Поисковый запрос' },
        limit: { type: 'number', description: 'Максимум результатов' },
      },
      required: ['query'],
      additionalProperties: false,
    },
  },
];
```

## Шаг 3. Регистрация

```typescript
// providers/index.ts
import { ExampleProvider } from './example/provider.js';

export const BUILTIN_PROVIDERS = [WeatherProvider, GitHubProvider, ExampleProvider] as const;
```

После этого:

1. `npm run dev` — Registry создаст `config/providers/example.json` с дефолтными настройками.
2. Провайдер появляется в Web UI (`/providers/example`): General, Credentials, Tools, Test connection.
3. Его tools автоматически объявляются MCP-клиенту (если provider enabled и tool enabled).

## Внешние plugins (future)

Интерфейс тот же: любой модуль может экспортировать класс `ApiProvider`
(`implements ApiProvider` или `extends BaseProvider`) и зарегистрировать его в рантайме:

```typescript
import { registry } from './src/core/registry/...'; // по месту использования
registry.registerProviderClass(MyProvider);
```

Это закладывает основу для установки npm-плагинов (slack, notion, jira, ...) без изменений ядра.

## Чек-лист

- [ ] HTTP только через `this.http.*` с `log:`-контекстом
- [ ] zod-валидация входных данных, понятные user-ошибки (`Invalid input: ...`)
- [ ] Секреты: только в `credentials`, не в логах/результатах
- [ ] `healthCheck()` выполняет реальный запрос
- [ ] `getDefaultConfig()`, `getCredentialEnv()`, `getConfigSchema()`
- [ ] Класс добавлен в `providers/index.ts`
- [ ] `npm run typecheck`, `npm run test` проходят