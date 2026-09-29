import { z } from 'zod';

export const LOG_LEVELS = ['debug', 'info', 'warn', 'error'] as const;

/** Настройки Scheduler / Scheduled Tasks. */
export const schedulerSettingsSchema = z
  .object({
    enabled: z.boolean().default(true),
    tickIntervalMs: z.number().int().min(100).max(3_600_000).default(60_000),
    maxStoredExecutionsPerTask: z.number().int().min(10).max(100_000).default(1000),
    executionRetentionDays: z.number().int().min(0).max(3650).default(30),
    retry: z
      .object({
        enabled: z.boolean().default(true),
        maxAttempts: z.number().int().min(1).max(10).default(3),
        delayMs: z.number().int().min(0).max(3_600_000).default(5000),
      })
      .default({}),
  })
  .default({});

/** Схема config/server.json. Все значения имеют дефолты. */
export const serverConfigSchema = z.object({
  host: z.string().min(1).default('127.0.0.1'),
  port: z.number().int().min(1).max(65535).default(3000),
  logLevel: z.enum(LOG_LEVELS).default('info'),
  logRetentionDays: z.number().int().min(0).max(365).default(7),
  maxResponseLogSize: z.number().int().min(1024).max(10 * 1024 * 1024).default(64 * 1024),
  requestTimeoutMs: z.number().int().min(100).max(120_000).default(15_000),
  defaultRetryCount: z.number().int().min(0).max(10).default(2),
  retryBackoffMs: z.number().int().min(0).max(60_000).default(250),
  corsEnabled: z.boolean().default(true),
  corsOrigins: z.array(z.string()).default([]),
  debug: z.boolean().default(false),
  scheduler: schedulerSettingsSchema,
});

export type ServerConfig = z.infer<typeof serverConfigSchema>;

export const providerToolConfigSchema = z.object({
  enabled: z.boolean().optional(),
  settings: z.record(z.string(), z.unknown()).optional(),
});

/** Базовая схема config/providers/<id>.json. Специфичные для провайдера поля валидирует сам провайдер. */
export const providerConfigFileSchema = z.object({
  id: z.string().regex(/^[a-zA-Z0-9_-]{1,64}$/),
  enabled: z.boolean().default(true),
  name: z.string().min(1).max(100).optional(),
  baseUrl: z.union([z.string().url(), z.literal('')]).optional(),
  credentials: z.record(z.string(), z.string()).optional(),
  settings: z.record(z.string(), z.unknown()).optional(),
  tools: z.record(z.string(), providerToolConfigSchema).optional(),
});

export type ProviderConfigFile = z.infer<typeof providerConfigFileSchema>;

/** Допустимый идентификатор провайдера (защита от path traversal в именах файлов). */
export const PROVIDER_ID_RE = /^[a-zA-Z0-9_-]{1,64}$/;

/**
 * Схема отдельного файла секретов config/credentials.json:
 * { "github": { "token": "..." }, "gismeteo": { "token": "..." } }
 */
export const credentialsStoreSchema = z.record(z.string(), z.record(z.string(), z.string()));

/**
 * Схема config/scheduler-tools.json — включение/выключение scheduler tools для MCP:
 * { "create_scheduled_task": { "enabled": true }, ... }
 */
export const schedulerToolsConfigSchema = z.record(z.string(), z.object({ enabled: z.boolean().optional() }));

/**
 * Схема config/pipeline-tools.json — включение/выключение pipeline tools для MCP:
 * { "run_pipeline": { "enabled": true }, ... }
 */
export const pipelineToolsConfigSchema = z.record(z.string(), z.object({ enabled: z.boolean().optional() }));

export const LOG_QUERY_LIMIT_MAX = 500;