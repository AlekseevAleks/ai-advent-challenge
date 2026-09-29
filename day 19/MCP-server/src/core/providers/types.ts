import type { ProviderConfig, ProviderToolConfig } from '../types.js';

/** Описание одного поля конфигурации провайдера (для генерации форм в Web UI). */
export interface ConfigField {
  key: string;
  label: string;
  type: 'string' | 'number' | 'boolean';
  description?: string;
  default?: string | number | boolean;
  required?: boolean;
  /** Секрет: не показывается после сохранения, только маска. */
  secret?: boolean;
  /** Имя env-переменной, которая может переопределить значение. */
  env?: string;
  unit?: string;
  placeholder?: string;
}

/** Схема конфигурации провайдера: что показывает UI на вкладках General / Credentials. */
export interface ConfigSchema {
  /** Поля верхнего уровня (name, baseUrl, ...). */
  fields: ConfigField[];
  /** Поля, живущие внутри settings. */
  settingsFields: ConfigField[];
  /** Поля, живущие внутри credentials (все секретные). */
  credentialFields: ConfigField[];
}

/** JSON Schema 2020-12 для входных данных MCP tool. */
export interface ToolInputSchema {
  type: 'object';
  properties?: Record<string, Record<string, unknown>>;
  required?: string[];
  additionalProperties?: boolean;
}

/** Декларация MCP tool от провайдера. */
export interface ToolDefinition {
  name: string;
  description: string;
  inputSchema: ToolInputSchema;
}

/** Tool с учётом конфигурации (enabled/settings). */
export interface ResolvedTool {
  tool: ToolDefinition;
  providerId: string;
  enabled: boolean;
  settings: Record<string, unknown>;
}

export interface ProviderHealth {
  status: 'ok' | 'error' | 'unknown';
  message?: string;
  checkedAt?: string;
  durationMs?: number;
  statusCode?: number;
}

/** Tool в runtime-состоянии для REST API / Web UI. */
export interface ProviderRuntimeTool extends ToolDefinition {
  enabled: boolean;
  settings: Record<string, unknown>;
}

export interface CredentialState {
  /** Маскированное значение (никогда не полное). */
  value: string;
  set: boolean;
  /** Значение пришло из env-переменной и не редактируется в UI. */
  overridden: boolean;
  env?: string;
}

/** Полное состояние провайдера для REST API / Web UI. */
export interface ProviderRuntimeState {
  id: string;
  name: string;
  description: string;
  version: string;
  enabled: boolean;
  baseUrl?: string;
  configSchema: ConfigSchema;
  settings: Record<string, unknown>;
  credentials: Record<string, CredentialState>;
  health: ProviderHealth;
  tools: ProviderRuntimeTool[];
  toolsCount: number;
  enabledToolsCount: number;
}

/**
 * Общий интерфейс провайдера. Ядро MCP Gateway ничего не знает о конкретных API:
 * провайдер сам описывает конфигурацию, tools, credentials, валидацию входных данных,
 * HTTP-запросы (через общий HttpClient) и преобразование ответов.
 */
export interface ApiProvider {
  readonly id: string;
  readonly name: string;
  readonly description: string;
  readonly version: string;

  /** Схема конфигурации для генерации форм в Web UI. */
  getConfigSchema(): ConfigSchema;

  /** Конфигурация по умолчанию (создаётся при первом запуске). */
  getDefaultConfig(): ProviderConfig;

  /** Декларации MCP tools этого провайдера (независимо от enabled-флагов). */
  getTools(): ToolDefinition[];

  /** Маппинг ключа credential → env-переменная, которая может переопределять значение. */
  getCredentialEnv(): Record<string, string>;

  /** Инициализация с конфигурацией из config/providers/<id>.json. */
  initialize(config: ProviderConfig): Promise<void>;

  /** Освобождение ресурсов при отключении/перезагрузке. */
  dispose(): Promise<void>;

  /** Реальная проверка соединения с внешним API (Test Connection). */
  healthCheck(): Promise<ProviderHealth>;

  /** Выполнение MCP tool с валидацией входных данных. */
  executeTool(toolName: string, input: unknown, toolConfig: ProviderToolConfig): Promise<unknown>;

  getBaseUrl(): string | undefined;
}