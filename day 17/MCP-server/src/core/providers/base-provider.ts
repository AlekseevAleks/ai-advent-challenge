import type { HttpClient } from '../http/http-client.js';
import { configError } from '../errors.js';
import type { ProviderConfig, ProviderToolConfig } from '../types.js';
import type { ApiProvider, ConfigSchema, ProviderHealth, ToolDefinition } from './types.js';

export interface BaseProviderOptions {
  id: string;
  name: string;
  description: string;
  version: string;
  http: HttpClient;
  defaultBaseUrl?: string;
}

/** Таймаут по умолчанию, если не задан в settings.timeout. */
const DEFAULT_TIMEOUT_MS = 10_000;

/**
 * Базовая реализация ApiProvider: хранит конфигурацию, отдаёт схемы по умолчанию
 * и предоставляет общий HttpClient. Конкретные провайдеры расширяют этот класс.
 */
export abstract class BaseProvider implements ApiProvider {
  readonly id: string;
  readonly name: string;
  readonly description: string;
  readonly version: string;

  protected readonly http: HttpClient;
  protected config: ProviderConfig;
  protected healthCache: ProviderHealth = { status: 'unknown' };
  protected readonly defaultBaseUrl?: string;

  constructor(opts: BaseProviderOptions) {
    this.id = opts.id;
    this.name = opts.name;
    this.description = opts.description;
    this.version = opts.version;
    this.http = opts.http;
    this.defaultBaseUrl = opts.defaultBaseUrl;
    this.config = { id: this.id, enabled: false };
  }

  getConfigSchema(): ConfigSchema {
    return { fields: [], settingsFields: [], credentialFields: [] };
  }

  getDefaultConfig(): ProviderConfig {
    return { id: this.id, enabled: true, name: this.name };
  }

  getCredentialEnv(): Record<string, string> {
    return {};
  }

  abstract getTools(): ToolDefinition[];

  async initialize(config: ProviderConfig): Promise<void> {
    this.config = config;
    this.validateConfig();
    this.healthCache = { status: 'unknown' };
  }

  protected validateConfig(): void {
    if (this.config.baseUrl && !/^https?:\/\//i.test(this.config.baseUrl)) {
      throw configError(`Provider "${this.id}": baseUrl must be an http(s) URL`, 'INVALID_BASE_URL');
    }
    const timeout = this.settings.timeout;
    if (timeout !== undefined && (typeof timeout !== 'number' || !Number.isFinite(timeout) || timeout <= 0)) {
      throw configError(`Provider "${this.id}": settings.timeout must be a positive number`, 'INVALID_SETTINGS');
    }
  }

  async dispose(): Promise<void> {
    this.healthCache = { status: 'unknown' };
  }

  abstract healthCheck(): Promise<ProviderHealth>;

  abstract executeTool(toolName: string, input: unknown, toolConfig: ProviderToolConfig): Promise<unknown>;

  getBaseUrl(): string | undefined {
    return this.config.baseUrl || this.defaultBaseUrl;
  }

  get settings(): Record<string, unknown> {
    return this.config.settings ?? {};
  }

  protected getTimeoutMs(): number {
    const timeout = this.settings.timeout;
    return typeof timeout === 'number' && timeout > 0 ? timeout : DEFAULT_TIMEOUT_MS;
  }

  /** Склеить baseUrl и относительный путь. Использует дефолтный URL провайдера, если не задан в конфиге. */
  protected url(path: string): string {
    const base = (this.getBaseUrl() ?? '').replace(/\/+$/, '');
    if (!base) throw configError(`Provider "${this.id}": baseUrl is not configured`, 'MISSING_BASE_URL');
    return `${base}${path.startsWith('/') ? path : `/${path}`}`;
  }

  /** Стандартизировать результат health check в одном месте. */
  protected health(status: 'ok' | 'error', message: string, statusCode?: number): ProviderHealth {
    return { status, message, statusCode };
  }
}