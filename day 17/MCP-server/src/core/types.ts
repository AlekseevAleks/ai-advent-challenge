/** Общие типы предметной области MCP Gateway. */

export type LogLevel = 'silent' | 'debug' | 'info' | 'warn' | 'error';

/** Категории ошибок, разделяющие пользовательские и внутренние проблемы. */
export type AppErrorKind =
  | 'user' // неверный ввод от MCP-клиента / UI
  | 'internal' // внутренняя ошибка сервера
  | 'external' // ошибка внешнего API
  | 'config' // ошибка конфигурации
  | 'auth' // ошибка аутентификации/авторизации
  | 'rate_limit' // превышен rate limit
  | 'timeout'; // таймаут запроса

/** Настройки самого сервера (config/server.json + env-переопределения). */
export interface ServerSettings {
  host: string;
  port: number;
  logLevel: LogLevel;
  logRetentionDays: number;
  maxResponseLogSize: number; // байты, для хранения тел ответов в логах
  requestTimeoutMs: number;
  defaultRetryCount: number;
  retryBackoffMs: number;
  corsEnabled: boolean;
  corsOrigins: string[];
  debug: boolean;
}

/** Конфигурация одного tool в конфигурационном файле провайдера. */
export interface ProviderToolConfig {
  enabled?: boolean;
  settings?: Record<string, unknown>;
}

/** Конфигурация провайдера (config/providers/<id>.json). */
export interface ProviderConfig {
  id: string;
  enabled: boolean;
  name?: string;
  baseUrl?: string;
  credentials?: Record<string, string>;
  settings?: Record<string, unknown>;
  tools?: Record<string, ProviderToolConfig>;
}