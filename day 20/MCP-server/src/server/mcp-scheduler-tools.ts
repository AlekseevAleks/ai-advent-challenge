import { z } from 'zod';
import type { ToolDefinition } from '../core/providers/types.js';
import type { TaskManager } from '../core/scheduler/task-manager.js';
import type { TaskInput, TaskUpdate } from '../core/scheduler/task-types.js';
import { userError } from '../core/errors.js';

const prop = (description: string, type: string, extra: Record<string, unknown> = {}): Record<string, unknown> => ({
  type,
  description,
  ...extra,
});

const inputProperty = prop('Произвольный JSON с аргументами tool (см. inputSchema у tool)', 'object');
const scheduleProperties = {
  type: prop('once — однократно, cron — по расписанию', 'string', { enum: ['once', 'cron'] }),
  executeAt: prop('Для once: ISO-время запуска, например 2026-09-28T10:00:00Z', 'string'),
  cron: prop('Для cron: 5-польное выражение, например "0 * * * *"', 'string'),
  timezone: prop('IANA-таймзона, например Europe/Berlin, UTC', 'string'),
};

export const SCHEDULER_TOOL_DEFINITIONS: ToolDefinition[] = [
  {
    name: 'create_scheduled_task',
    description:
      'Создаёт scheduled task: однократную или cron-задачу, которая будет выполнять существующий provider tool по расписанию. Пример: {name:"Berlin Weather", schedule:{type:"cron",cron:"0 * * * *",timezone:"Europe/Berlin"}, action:{provider:"weather",tool:"weather_current",input:{latitude:52.52,longitude:13.405}}}.',
    inputSchema: {
      type: 'object',
      properties: {
        id: prop('Опциональный slug id (a-z0-9_-, до 64 символов); по умолчанию генерируется', 'string'),
        name: prop('Название задачи', 'string'),
        description: prop('Описание задачи', 'string'),
        enabled: prop('Создать включённой (по умолчанию true)', 'boolean'),
        schedule: {
          type: 'object',
          description: 'Расписание: once → executeAt + timezone; cron → cron + timezone',
          properties: scheduleProperties,
          required: ['type'],
        },
        action: {
          type: 'object',
          description: 'Действие: вызов существующего provider tool',
          properties: {
            provider: prop('ID провайдера, например weather, github', 'string'),
            tool: prop('Имя tool, например weather_current, github_list_issues', 'string'),
            input: inputProperty,
          },
          required: ['provider', 'tool'],
        },
        aggregation: {
          type: 'object',
          description: 'Опциональные настройки агрегации',
          properties: {
            enabled: prop('Агрегировать результаты (по умолчанию true)', 'boolean'),
            strategy: prop('Стратегия: auto', 'string'),
            window: prop('Окно по умолчанию: 1h, 24h, 7d, 30d, all', 'string'),
          },
        },
      },
      required: ['name', 'schedule', 'action'],
      additionalProperties: false,
    },
  },
  {
    name: 'list_scheduled_tasks',
    description: 'Список всех scheduled tasks (без истории выполнений).',
    inputSchema: { type: 'object', properties: {}, additionalProperties: false },
  },
  {
    name: 'get_scheduled_task',
    description: 'Детальная информация об одной scheduled task.',
    inputSchema: {
      type: 'object',
      properties: { taskId: prop('ID задачи', 'string') },
      required: ['taskId'],
      additionalProperties: false,
    },
  },
  {
    name: 'update_scheduled_task',
    description: 'Изменяет расписание, действие или параметры задачи. Частичное обновление.',
    inputSchema: {
      type: 'object',
      properties: {
        taskId: prop('ID задачи', 'string'),
        patch: {
          type: 'object',
          description: 'Частичное обновление: {name?, description?, enabled?, schedule?, action?, aggregation?}',
          properties: {
            name: prop('Новое название', 'string'),
            description: prop('Новое описание', 'string'),
            enabled: prop('Включить/выключить', 'boolean'),
            schedule: { type: 'object', description: 'Новое расписание', properties: scheduleProperties },
            action: {
              type: 'object',
              description: 'Новое действие',
              properties: {
                provider: prop('ID провайдера', 'string'),
                tool: prop('Имя tool', 'string'),
                input: inputProperty,
              },
            },
            aggregation: { type: 'object', description: 'Настройки агрегации' },
          },
        },
      },
      required: ['taskId', 'patch'],
      additionalProperties: false,
    },
  },
  {
    name: 'delete_scheduled_task',
    description: 'Удаляет задачу вместе с её историей выполнений.',
    inputSchema: {
      type: 'object',
      properties: { taskId: prop('ID задачи', 'string') },
      required: ['taskId'],
      additionalProperties: false,
    },
  },
  {
    name: 'pause_scheduled_task',
    description: 'Приостанавливает задачу (не будет запускаться по расписанию).',
    inputSchema: {
      type: 'object',
      properties: { taskId: prop('ID задачи', 'string') },
      required: ['taskId'],
      additionalProperties: false,
    },
  },
  {
    name: 'resume_scheduled_task',
    description: 'Возобновляет приостановленную задачу.',
    inputSchema: {
      type: 'object',
      properties: { taskId: prop('ID задачи', 'string') },
      required: ['taskId'],
      additionalProperties: false,
    },
  },
  {
    name: 'run_scheduled_task_now',
    description: 'Немедленно выполняет задачу (вне зависимости от расписания). Возвращает запись выполнения.',
    inputSchema: {
      type: 'object',
      properties: { taskId: prop('ID задачи', 'string') },
      required: ['taskId'],
      additionalProperties: false,
    },
  },
  {
    name: 'get_task_history',
    description: 'История выполнений задачи (pagination).',
    inputSchema: {
      type: 'object',
      properties: {
        taskId: prop('ID задачи', 'string'),
        limit: prop('Максимум записей, 1–200 (по умолчанию 50)', 'number'),
        offset: prop('Смещение для пагинации', 'number'),
      },
      required: ['taskId'],
      additionalProperties: false,
    },
  },
  {
    name: 'get_task_summary',
    description:
      'Агрегированная сводка по выполненным результатам задачи: count/min/max/average/sum/latest по числовым полям + категории + человекочитаемый текст. Пример windows: 1h, 24h, 7d, 30d, all.',
    inputSchema: {
      type: 'object',
      properties: {
        taskId: prop('ID задачи', 'string'),
        window: prop('Окно: 1h, 24h, 7d, 30d, all (по умолчанию 24h)', 'string'),
        from: prop('Начало периода (ISO) для custom', 'string'),
        to: prop('Конец периода (ISO) для custom', 'string'),
        strategy: prop('Стратегия: auto, count, min, max, average, latest, sum', 'string'),
      },
      required: ['taskId'],
      additionalProperties: false,
    },
  },
];

export const SCHEDULER_TOOL_NAMES = new Set(SCHEDULER_TOOL_DEFINITIONS.map((t) => t.name));

const idSchema = z.object({ taskId: z.string().min(1) }).passthrough();
const createSchema = z.object({
  id: z.string().optional(),
  name: z.string().min(1),
  description: z.string().optional(),
  enabled: z.boolean().optional(),
  schedule: z.record(z.string(), z.unknown()),
  action: z.record(z.string(), z.unknown()),
  aggregation: z.record(z.string(), z.unknown()).optional(),
});
const updateSchema = z
  .object({
    taskId: z.string().min(1),
    patch: z.record(z.string(), z.unknown()),
  })
  .passthrough();
const historySchema = z
  .object({
    taskId: z.string().min(1),
    limit: z.coerce.number().int().min(1).max(200).optional(),
    offset: z.coerce.number().int().min(0).optional(),
  })
  .passthrough();
const summarySchema = z
  .object({
    taskId: z.string().min(1),
    window: z.enum(['1h', '24h', '7d', '30d', 'all', 'custom']).optional(),
    from: z.string().optional(),
    to: z.string().optional(),
    strategy: z.string().optional(),
  })
  .passthrough();

/** Выполнить scheduler tool через TaskManager (общая логика для MCP). */
export async function handleSchedulerTool(taskManager: TaskManager, name: string, args: unknown): Promise<unknown> {
  switch (name) {
    case 'create_scheduled_task': {
      const value = parse(createSchema, args);
      const input: TaskInput = { ...(value as unknown as TaskInput) };
      return taskManager.create(input);
    }
    case 'list_scheduled_tasks':
      return taskManager.listTasks();
    case 'get_scheduled_task': {
      const value = parse(idSchema, args);
      return taskManager.getTask(value.taskId);
    }
    case 'update_scheduled_task': {
      const value = parse(updateSchema, args);
      return taskManager.update(value.taskId, value.patch as unknown as TaskUpdate);
    }
    case 'delete_scheduled_task': {
      const value = parse(idSchema, args);
      return taskManager.delete(value.taskId);
    }
    case 'pause_scheduled_task': {
      const value = parse(idSchema, args);
      return taskManager.pause(value.taskId);
    }
    case 'resume_scheduled_task': {
      const value = parse(idSchema, args);
      return taskManager.resume(value.taskId);
    }
    case 'run_scheduled_task_now': {
      const value = parse(idSchema, args);
      const execution = await taskManager.runNow(value.taskId);
      return {
        taskId: value.taskId,
        status: execution.status,
        durationMs: execution.durationMs,
        execution,
        message:
          execution.status === 'success'
            ? `Task executed successfully${execution.durationMs !== undefined ? ` in ${execution.durationMs}ms` : ''}`
            : `Task failed: ${execution.error ?? 'unknown error'}`,
      };
    }
    case 'get_task_history': {
      const value = parse(historySchema, args);
      return taskManager.getHistory(value.taskId, value.offset ?? 0, value.limit ?? 50);
    }
    case 'get_task_summary': {
      const value = parse(summarySchema, args);
      return taskManager.getSummary(value.taskId, {
        window: value.window,
        from: value.from,
        to: value.to,
        strategy: value.strategy as never,
      });
    }
    default:
      throw userError(`Unknown scheduler tool: ${name}`, 'UNKNOWN_TOOL');
  }
}

function parse<T>(schema: z.ZodType<T>, args: unknown): T {
  const result = schema.safeParse(args ?? {});
  if (!result.success) {
    const message = result.error.issues.map((i) => `${i.path.join('.') || 'input'}: ${i.message}`).join('; ');
    throw userError(`Invalid arguments: ${message}`, 'INVALID_TOOL_INPUT');
  }
  return result.data;
}