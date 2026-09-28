import { z } from 'zod';
import { parseDateMs, validateCron, validateTimezone } from './schedule-utils.js';

export type TaskScheduleType = 'once' | 'cron';
export type TaskStatus = 'active' | 'paused' | 'completed' | 'error';
export type ExecutionStatus = 'running' | 'success' | 'error';

/** Расписание задачи. */
export interface TaskSchedule {
  type: TaskScheduleType;
  /** Для once: ISO-строка времени запуска (в timezone, если задана, иначе машинная). */
  executeAt?: string;
  /** Для cron: 5-польное выражение, например "0 * * * *". */
  cron?: string;
  /** IANA-таймзона, например Europe/Berlin, UTC. */
  timezone?: string;
}

/** Действие задачи — всегда вызов существующего provider tool. */
export interface TaskAction {
  type: 'provider_tool';
  provider: string;
  tool: string;
  input: unknown;
}

export interface TaskAggregation {
  enabled?: boolean;
  strategy?: string;
  window?: string;
}

/** Scheduled Task (доменная модель, как отдаётся в REST/MCP/UI). */
export interface ScheduledTask {
  id: string;
  name: string;
  description?: string;
  enabled: boolean;
  schedule: TaskSchedule;
  action: TaskAction;
  aggregation?: TaskAggregation;
  createdAt: string;
  updatedAt: string;
  lastRunAt?: string;
  nextRunAt?: string;
  status: TaskStatus;
  running: boolean;
  version: number;
}

/** История выполнения одной задачи. */
export interface TaskExecution {
  id: string;
  taskId: string;
  startedAt: string;
  finishedAt?: string;
  status: ExecutionStatus;
  durationMs?: number;
  result?: unknown;
  error?: string;
}

export interface TaskExecutionHistoryPage {
  items: TaskExecution[];
  total: number;
  offset: number;
  limit: number;
}

// ------------------------------------------------------------- входные схемы

const timezoneSchema = z.string().refine(validateTimezone, { message: 'unknown IANA timezone' });
const cronSchema = z.string().refine(validateCron, { message: 'invalid cron expression' });

const scheduleSchema = z.discriminatedUnion('type', [
  z.object({
    type: z.literal('once'),
    executeAt: z.string().min(1, 'executeAt is required for once tasks'),
    timezone: timezoneSchema.optional(),
  }),
  z.object({
    type: z.literal('cron'),
    cron: cronSchema,
    timezone: timezoneSchema.default('UTC'),
  }),
]);

const actionSchema = z.object({
  type: z.literal('provider_tool').default('provider_tool'),
  provider: z.string().min(1).max(64),
  tool: z.string().min(1).max(200),
  input: z.unknown().optional(),
});

const aggregationSchema = z
  .object({
    enabled: z.boolean().optional(),
    strategy: z.string().max(50).optional(),
    window: z.string().max(50).optional(),
  })
  .optional();

/** Чек, общий для create и update: schedule должен быть валиден. */
const scheduleRefinement = (val: { schedule?: TaskSchedule }, ctx: z.RefinementCtx, now: () => number = Date.now): void => {
  const schedule = val.schedule;
  if (!schedule) return;
  if (schedule.type === 'once') {
    const at = parseDateMs(schedule.executeAt ?? '');
    if (at === null) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ['schedule', 'executeAt'], message: 'executeAt must be a valid date' });
      return;
    }
    if (at <= now()) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ['schedule', 'executeAt'],
        message: 'executeAt must be in the future',
      });
    }
  } else {
    if (!schedule.cron || !validateCron(schedule.cron)) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ['schedule', 'cron'], message: 'invalid cron expression' });
    }
    if (schedule.timezone && !validateTimezone(schedule.timezone)) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ['schedule', 'timezone'], message: 'unknown IANA timezone' });
    }
  }
};

/** Создание задачи: все поля обязательные (кроме id/description/enabled/aggregation). */
export const taskInputSchema = z
  .object({
    id: z.string().regex(/^[a-zA-Z0-9_-]{1,64}$/, 'id must match [a-zA-Z0-9_-]{1,64}').optional(),
    name: z.string().min(1).max(120),
    description: z.string().max(500).optional(),
    enabled: z.boolean().optional(),
    schedule: scheduleSchema,
    action: actionSchema,
    aggregation: aggregationSchema,
  })
  .superRefine((val, ctx) => scheduleRefinement(val, ctx));

/** Обновление задачи: частичный набор полей. */
export const taskUpdateSchema = z
  .object({
    name: z.string().min(1).max(120).optional(),
    description: z.string().max(500).optional(),
    enabled: z.boolean().optional(),
    schedule: scheduleSchema.optional(),
    action: actionSchema.optional(),
    aggregation: aggregationSchema,
  })
  .superRefine((val, ctx) => scheduleRefinement(val, ctx));

export type TaskInput = z.infer<typeof taskInputSchema>;
export type TaskUpdate = z.infer<typeof taskUpdateSchema>;

// ------------------------------------------------------------- summary

export type SummaryWindow = '1h' | '24h' | '7d' | '30d' | 'all';
export type SummaryStrategy = 'auto' | 'count' | 'min' | 'max' | 'average' | 'latest' | 'sum';

export interface AggregationOptions {
  window?: SummaryWindow | 'custom';
  from?: string;
  to?: string;
  strategy?: SummaryStrategy;
}

export interface NumericStats {
  count: number;
  min?: number;
  max?: number;
  avg?: number;
  sum?: number;
  latest?: number;
  first?: number;
}

export interface CategoryCounts {
  total: number;
  values: Record<string, number>;
}

export interface TaskSummary {
  taskId: string;
  window: { label: string; from?: string; to?: string };
  executions: { total: number; success: number; error: number };
  numericSeries: Record<string, NumericStats>;
  categories: Record<string, CategoryCounts>;
  summaryText: string;
}