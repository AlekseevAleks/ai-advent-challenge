import { mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { vi } from 'vitest';
import { ConfigManager } from '../src/core/config/config-manager.js';
import { HttpClient } from '../src/core/http/http-client.js';
import { Logger } from '../src/core/logging/logger.js';
import { RequestLogger } from '../src/core/logging/request-logger.js';
import { ProviderRegistry } from '../src/core/registry/provider-registry.js';
import { BUILTIN_PROVIDERS } from '../providers/index.js';
import type { ApiProvider, ToolDefinition } from '../src/core/providers/types.js';
import type { ProviderConfig, ProviderToolConfig } from '../src/core/types.js';

type FetchHandler = (url: string, init?: RequestInit) => Response | Promise<Response>;

export function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(typeof body === 'string' ? body : JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json', ...headers },
  });
}

export interface Harness {
  tmpDir: string;
  configDir: string;
  dataDir: string;
  configManager: ConfigManager;
  registry: ProviderRegistry;
  requestLogger: RequestLogger;
  httpClient: HttpClient;
  fetchMock: ReturnType<typeof vi.fn>;
  cleanup: () => void;
}

export function createHarness(opts: {
  providerConfigs?: Record<string, unknown>;
  serverConfig?: Record<string, unknown>;
  providers?: Array<new (http: HttpClient) => ApiProvider>;
  onFetch?: FetchHandler;
} = {}): Harness {
  const tmpDir = mkdtempSync(path.join(os.tmpdir(), 'mcp-gw-test-'));
  const configDir = path.join(tmpDir, 'config');
  const providersDir = path.join(configDir, 'providers');
  const dataDir = path.join(tmpDir, 'data');
  mkdirSync(providersDir, { recursive: true });

  if (opts.serverConfig) writeFileSync(path.join(configDir, 'server.json'), JSON.stringify(opts.serverConfig, null, 2));
  for (const [id, cfg] of Object.entries(opts.providerConfigs ?? {})) {
    writeFileSync(path.join(providersDir, `${id}.json`), JSON.stringify(cfg, null, 2));
  }

  const onFetch = opts.onFetch ?? (() => jsonResponse(404, { message: 'not stubbed' }));
  const fetchMock = vi.fn(async (url: string | URL | Request, init?: RequestInit) =>
    onFetch(String(url), init),
  );

  const configManager = new ConfigManager({ configDir, dataDir });
  const requestLogger = new RequestLogger({ logsDir: path.join(dataDir, 'logs'), maxResponseLogSize: 64 * 1024 });
  const logger = new Logger({ level: 'silent' });
  const httpClient = new HttpClient({ fetchImpl: fetchMock as unknown as typeof fetch, requestLogger, logger });
  const registry = new ProviderRegistry({ configManager, httpClient, logger });

  for (const cls of opts.providers ?? BUILTIN_PROVIDERS) registry.registerProviderClass(cls);

  return {
    tmpDir,
    configDir,
    dataDir,
    configManager,
    registry,
    requestLogger,
    httpClient,
    fetchMock,
    cleanup: () => rmSync(tmpDir, { recursive: true, force: true }),
  };
}

/** Читать все записи JSONL-файла логов из data/logs. */
export function readLogLines(dataDir: string): string[] {
  const logsDir = path.join(dataDir, 'logs');
  const lines: string[] = [];
  for (const file of readdirSync(logsDir).filter((f) => f.endsWith('.jsonl'))) {
    lines.push(...readFileSync(path.join(logsDir, file), 'utf8').split('\n').filter(Boolean));
  }
  return lines;
}

// ---------------------------------------------------------------------------
// Минимальный тестовый провайдер, не выполняющий сетевых запросов.
// ---------------------------------------------------------------------------

export class FakeProvider implements ApiProvider {
  readonly id = 'fake';
  readonly name = 'Fake Provider';
  readonly description = 'Test provider';
  readonly version = '1.0.0';

  constructor(private readonly http: HttpClient) {}

  getConfigSchema() {
    return {
      fields: [],
      settingsFields: [],
      credentialFields: [{ key: 'api_key', label: 'API Key', type: 'string' as const, secret: true }],
    };
  }

  getDefaultConfig(): ProviderConfig {
    return { id: this.id, enabled: true, name: this.name, credentials: { api_key: '' } };
  }

  getCredentialEnv() {
    return { api_key: 'FAKE_API_KEY' };
  }

  getTools(): ToolDefinition[] {
    return [
      { name: 'fake_echo', description: 'Echoes input', inputSchema: { type: 'object', properties: { text: { type: 'string' } }, required: ['text'] } },
      { name: 'fake_other', description: 'Another tool', inputSchema: { type: 'object', properties: {} } },
    ];
  }

  async initialize(config: ProviderConfig): Promise<void> {
    if (config.settings?.timeout && (config.settings.timeout as number) <= 0) {
      throw new Error('timeout must be positive');
    }
    this.config = config;
  }

  async dispose(): Promise<void> {}

  async healthCheck() {
    return { status: 'ok' as const, message: 'healthy' };
  }

  async executeTool(toolName: string, input: unknown): Promise<unknown> {
    if (toolName === 'fake_echo') return { echoed: (input as { text?: string }).text };
    throw new Error(`unknown tool ${toolName}`);
  }

  getBaseUrl() {
    return this.config.baseUrl;
  }

  private config: ProviderConfig = { id: this.id, enabled: false };
}