import { z } from 'zod';

/** PUT /api/providers/:id — частичное обновление конфигурации провайдера. */
export const providerUpdateSchema = z
  .object({
    enabled: z.boolean().optional(),
    name: z.string().min(1).max(100).optional(),
    baseUrl: z.union([z.string().url(), z.literal('')]).optional(),
    settings: z.record(z.string(), z.unknown()).optional(),
    credentials: z.record(z.string(), z.string()).optional(),
    tools: z.record(z.string(), z.object({ enabled: z.boolean().optional(), settings: z.record(z.string(), z.unknown()).optional() })).optional(),
  })
  .strict();

/** PUT /api/providers/:id/tools/:toolId. */
export const toolUpdateSchema = z
  .object({
    enabled: z.boolean().optional(),
    settings: z.record(z.string(), z.unknown()).optional(),
  })
  .strict();

/** PUT /api/server/settings — частичное обновление настроек сервера. */
export const serverSettingsUpdateSchema = z
  .object({
    host: z.string().min(1).max(255).optional(),
    port: z.number().int().min(1).max(65535).optional(),
    logLevel: z.enum(['debug', 'info', 'warn', 'error', 'silent']).optional(),
    logRetentionDays: z.number().int().min(0).max(365).optional(),
    maxResponseLogSize: z.number().int().min(1024).max(10 * 1024 * 1024).optional(),
    requestTimeoutMs: z.number().int().min(100).max(120_000).optional(),
    defaultRetryCount: z.number().int().min(0).max(10).optional(),
    retryBackoffMs: z.number().int().min(0).max(60_000).optional(),
    corsEnabled: z.boolean().optional(),
    corsOrigins: z.array(z.string()).optional(),
    debug: z.boolean().optional(),
    scheduler: z
      .object({
        enabled: z.boolean().optional(),
        tickIntervalMs: z.number().int().min(100).max(3_600_000).optional(),
        maxStoredExecutionsPerTask: z.number().int().min(10).max(100_000).optional(),
        executionRetentionDays: z.number().int().min(0).max(3650).optional(),
        retry: z
          .object({
            enabled: z.boolean().optional(),
            maxAttempts: z.number().int().min(1).max(10).optional(),
            delayMs: z.number().int().min(0).max(3_600_000).optional(),
          })
          .optional(),
      })
      .optional(),
  })
  .strict();

/** DELETE /api/logs — обязательное подтверждение. */
export const clearLogsSchema = z.object({ confirm: z.literal(true) }).strict();

const isoDateLike = z.string().refine((v) => !Number.isNaN(Date.parse(v)), 'invalid date');

/** GET /api/logs — query-параметры. */
export const logsQuerySchema = z.object({
  search: z.string().max(200).optional(),
  provider: z.string().max(64).optional(),
  tool: z.string().max(200).optional(),
  status: z.coerce.number().int().min(100).max(599).optional(),
  result: z.enum(['success', 'error', 'all']).optional(),
  from: isoDateLike.optional(),
  to: isoDateLike.optional(),
  offset: z.coerce.number().int().min(0).default(0),
  limit: z.coerce.number().int().min(1).max(500).default(50),
});

export function formatZodMessage(err: z.ZodError): string {
  return err.issues.map((issue) => `${issue.path.join('.') || 'body'}: ${issue.message}`).join('; ');
}