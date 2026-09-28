import { randomUUID } from 'node:crypto';
import { userError } from '../errors.js';
import type { Logger } from '../logging/logger.js';
import type { ProviderRegistry } from '../registry/provider-registry.js';
import { redactText, redactValue } from '../util/redact.js';
import type { SchedulerSettings } from '../types.js';
import type {
  AggregationOptions,
  ScheduledTask,
  TaskExecution,
  TaskExecutionHistoryPage,
  TaskInput,
  TaskSummary,
  TaskUpdate,
} from './task-types.js';
import { taskInputSchema, taskUpdateSchema } from './task-types.js';
import type { TaskStorage } from './task-storage.js';
import { rowToTask, taskToRow } from './task-storage.js';
import type { TaskExecutor } from './task-executor.js';
import type { Aggregator } from './aggregation/aggregator.js';
import { GenericAggregator } from './aggregation/generic-aggregator.js';
import { resolveAggregationWindow } from './aggregation/aggregator.js';
import { computeNextRunAtMs, describeSchedule } from './schedule-utils.js';

export interface TaskManagerOptions {
  storage: TaskStorage;
  executor: TaskExecutor;
  registry: ProviderRegistry;
  logger: Logger;
  aggregator?: Aggregator;
  getSettings: () => SchedulerSettings;
  /** Вызывается при любом изменении задач (Scheduler пересчитывает таймеры). */
  onTaskChanged?: () => void;
  now?: () => number;
}

const ID_SLUG_RE = /^[a-zA-Z0-9_-]{1,64}$/;

function zodErrorMessage(err: unknown): string {
  const e = err as { issues?: Array<{ path: Array<string | number>; message: string }> };
  if (e?.issues) {
    return e.issues.map((i) => `${i.path.join('.') || 'input'}: ${i.message}`).join('; ');
  }
  return String(err);
}

function zodError(err: unknown): Error {
  return userError(`Invalid task: ${zodErrorMessage(err)}`, 'INVALID_TASK');
}

/**
 * TaskManager — центр бизнес-логики Scheduled Tasks.
 * MCP tools и REST API используют ТОЛЬКО этот компонент:
 *   create/update/delete/pause/resume/runNow/list/get/history/summary.
 * Scheduler отвечает только за время запуска, TaskExecutor — за выполнение,
 * Storage — за сохранение.
 */
export class TaskManager {
  private readonly storage: TaskStorage;
  private readonly executor: TaskExecutor;
  private readonly registry: ProviderRegistry;
  private readonly logger: Logger;
  private readonly aggregator: Aggregator;
  private readonly getSettings: () => SchedulerSettings;
  private readonly onTaskChanged?: () => void;
  private readonly now: () => number;

  constructor(opts: TaskManagerOptions) {
    this.storage = opts.storage;
    this.executor = opts.executor;
    this.registry = opts.registry;
    this.logger = opts.logger;
    this.aggregator = opts.aggregator ?? new GenericAggregator();
    this.getSettings = opts.getSettings;
    this.onTaskChanged = opts.onTaskChanged;
    this.now = opts.now ?? (() => Date.now());
  }

  // ---------------------------------------------------------------- create

  async create(input: TaskInput): Promise<ScheduledTask> {
    const parsed = taskInputSchema.safeParse(input);
    if (!parsed.success) throw zodError(parsed.error);
    const data = parsed.data;

    const id = this.resolveId(data, data.name);
    this.validateTarget(data.action.provider, data.action.tool);

    const nowIso = new Date(this.now()).toISOString();
    const enabled = data.enabled ?? true;
    const schedule = {
      type: data.schedule.type,
      executeAt: data.schedule.type === 'once' ? data.schedule.executeAt : undefined,
      cron: data.schedule.type === 'cron' ? data.schedule.cron : undefined,
      timezone: data.schedule.timezone,
    };
    const nextRunAt = computeNextRunAtMs(schedule, this.now());

    const task: ScheduledTask = {
      id,
      name: data.name,
      description: data.description,
      enabled,
      schedule,
      action: { type: 'provider_tool', provider: data.action.provider, tool: data.action.tool, input: data.action.input ?? {} },
      aggregation: data.aggregation ?? { enabled: false, strategy: 'auto' },
      createdAt: nowIso,
      updatedAt: nowIso,
      nextRunAt: nextRunAt !== null ? new Date(nextRunAt).toISOString() : undefined,
      status: enabled ? 'active' : 'paused',
      running: false,
      version: 1,
    };
    this.storage.insertTask(task);
    this.onTaskChanged?.();
    this.logger.info(`[Scheduler] task created: ${id} (${describeSchedule(schedule)})`);
    return this.sanitize(task);
  }

  // ---------------------------------------------------------------- update

  async update(id: string, patch: TaskUpdate): Promise<ScheduledTask> {
    const current = this.storage.getTask(id);
    if (!current) throw this.taskNotFound(id);
    const parsed = taskUpdateSchema.safeParse(patch);
    if (!parsed.success) throw zodError(parsed.error);
    const data = parsed.data;

    if (data.action && (data.action.provider !== current.provider || data.action.tool !== current.tool || data.action.input !== undefined)) {
      const provider = data.action.provider ?? current.provider;
      const tool = data.action.tool ?? current.tool;
      this.validateTarget(provider, tool);
    }

    const schedule = data.schedule
      ? {
          type: data.schedule.type,
          executeAt: data.schedule.type === 'once' ? data.schedule.executeAt : undefined,
          cron: data.schedule.type === 'cron' ? data.schedule.cron : undefined,
          timezone: data.schedule.timezone,
        }
      : { type: current.schedule_type as 'once' | 'cron', executeAt: current.execute_at ?? undefined, cron: current.cron ?? undefined, timezone: current.timezone ?? undefined };

    const enabled = data.enabled ?? current.enabled === 1;
    const nextRunAt = computeNextRunAtMs(schedule, this.now());
    const ranOnce = current.last_run_at !== null && current.schedule_type === 'once' && schedule.type === 'once';

    const task: ScheduledTask = {
      id,
      name: data.name ?? current.name,
      description: data.description !== undefined ? data.description : (current.description ?? undefined),
      enabled,
      schedule,
      action: {
        type: 'provider_tool',
        provider: data.action?.provider ?? current.provider,
        tool: data.action?.tool ?? current.tool,
        input: data.action?.input !== undefined ? (data.action.input ?? {}) : JSON.parse(current.input_json),
      },
      aggregation:
        data.aggregation !== undefined
          ? data.aggregation
          : JSON.parse(current.aggregation_json),
      createdAt: current.created_at,
      updatedAt: new Date(this.now()).toISOString(),
      lastRunAt: current.last_run_at ?? undefined,
      nextRunAt: nextRunAt !== null ? new Date(nextRunAt).toISOString() : undefined,
      status: this.computeStatus({ enabled, isOnce: schedule.type === 'once', ranOnce, lastRunAtIsSet: current.last_run_at !== null }),
      running: false,
      version: current.version + 1,
    };
    this.storage.updateTask(task);
    this.onTaskChanged?.();
    return this.sanitize(task);
  }

  // ---------------------------------------------------------------- lifecycle

  async delete(id: string): Promise<{ deleted: boolean }> {
    const existing = this.storage.getTask(id);
    if (!existing) throw this.taskNotFound(id);
    this.storage.deleteExecutionsForTask(id);
    const deleted = this.storage.deleteTask(id);
    this.onTaskChanged?.();
    this.logger.info(`[Scheduler] task deleted: ${id}`);
    return { deleted };
  }

  async pause(id: string): Promise<ScheduledTask> {
    const row = this.mustGet(id);
    if (row.enabled === 0) return this.sanitize(rowToTask(row));
    this.storage.setTaskPaused(id, false);
    this.onTaskChanged?.();
    return this.sanitize(rowToTask(this.storage.getTask(id) as NonNullable<typeof row>));
  }

  async resume(id: string): Promise<ScheduledTask> {
    const row = this.mustGet(id);
    if (row.enabled === 1) return this.sanitize(rowToTask(row));
    const task = rowToTask(row);
    const enabled = true;
    const done =
      task.schedule.type === 'once' &&
      task.lastRunAt !== undefined &&
      task.schedule.executeAt !== undefined &&
      Date.parse(task.schedule.executeAt) <= this.now();
    task.enabled = enabled;
    task.status = done ? 'completed' : 'active';
    const nextMs = computeNextRunAtMs(task.schedule, this.now());
    task.nextRunAt = done ? undefined : nextMs !== null ? new Date(nextMs).toISOString() : undefined;
    task.updatedAt = new Date(this.now()).toISOString();
    task.version += 1;
    this.storage.updateTask(task);
    this.onTaskChanged?.();
    return this.sanitize(task);
  }

  /** Немедленный запуск (Web UI / MCP). Возвращает запись выполнения (успех или ошибку). */
  async runNow(id: string): Promise<TaskExecution> {
    const task = this.mustGetEntity(id);
    if (task.running) throw userError(`Task "${id}" is already running`, 'TASK_RUNNING');
    try {
      return await this.executor.execute(task);
    } catch (err) {
      if (err instanceof Error && 'code' in err && (err as { code: string }).code === 'TASK_RUNNING') throw err;
      return this.persistFailure(task, err);
    }
  }

  /** Запуск по расписанию (Scheduler). Тихий skip, если задача занята. */
  async executeDue(id: string): Promise<TaskExecution | null> {
    const task = this.mustGetEntity(id);
    if (!task.enabled || task.status !== 'active') return null;
    if (task.running) return null; // защита от двойного запуска (плюс атомарный claim в executor)
    try {
      return await this.executor.execute(task);
    } catch (err) {
      if (err instanceof Error && 'code' in err && (err as { code: string }).code === 'TASK_RUNNING') return null;
      this.logger.warn(`[Scheduler] task ${id} skipped by error: ${err instanceof Error ? err.message : String(err)}`);
      return this.persistFailure(task, err);
    }
  }

  // ---------------------------------------------------------------- queries

  listTasks(): ScheduledTask[] {
    return this.storage.listTasks().map((row) => this.sanitize(rowToTask(row)));
  }

  async getTask(id: string): Promise<ScheduledTask> {
    return this.sanitize(rowToTask(this.mustGet(id)));
  }

  async getHistory(id: string, offset: number, limit: number): Promise<TaskExecutionHistoryPage> {
    this.mustGet(id);
    const page = this.storage.listExecutions(id, offset, limit);
    return {
      items: page.rows.map((row) => {
        const exec = {
          id: row.id,
          taskId: row.task_id,
          startedAt: row.started_at,
          finishedAt: row.finished_at ?? undefined,
          status: row.status,
          durationMs: row.duration_ms ?? undefined,
          result: row.result_json === null ? undefined : parseJsonSafe(row.result_json),
          error: row.error_text ?? undefined,
        };
        return sanitizeExecution(exec);
      }),
      total: page.total,
      offset,
      limit,
    };
  }

  async getSummary(id: string, options: AggregationOptions = {}): Promise<TaskSummary> {
    this.mustGet(id);
    const window = resolveAggregationWindow(options, this.now());
    const executions = this.storage.executionsBetween(id, window.from ?? null, window.to ?? null);
    const summary = await this.aggregator.aggregate(executions, options);
    summary.taskId = id;
    return summary;
  }

  /** Демо-задачи (Weather hourly, GitHub issues 30min). Возвращает id созданных. */
  async createDemoTasks(): Promise<string[]> {
    const nowIso = new Date(this.now()).toISOString();
    const created: string[] = [];
    const demos: TaskInput[] = [
      {
        id: 'demo-weather-berlin',
        name: 'Demo: Berlin Weather',
        description: 'Каждый час: текущая погода в Берлине (Open-Meteo).',
        schedule: { type: 'cron', cron: '0 * * * *', timezone: 'Europe/Berlin' },
        action: { type: 'provider_tool', provider: 'weather', tool: 'weather_current', input: { latitude: 52.52, longitude: 13.405 } },
        aggregation: { enabled: true, strategy: 'auto', window: '24h' },
      },
      {
        id: 'demo-github-linux-issues',
        name: 'Demo: GitHub Linux Issues',
        description: 'Каждые 30 минут: количество открытых issues torvalds/linux.',
        schedule: { type: 'cron', cron: '*/30 * * * *', timezone: 'UTC' },
        action: {
          type: 'provider_tool',
          provider: 'github',
          tool: 'github_list_issues',
          input: { owner: 'torvalds', repo: 'linux', state: 'open', limit: 30 },
        },
        aggregation: { enabled: true, strategy: 'auto', window: '24h' },
      },
    ];
    for (const demo of demos) {
      if (this.storage.getTask(demo.id as string)) continue;
      await this.create({ ...demo, createdAt: nowIso } as unknown as TaskInput);
      created.push(demo.id as string);
    }
    return created;
  }

  // ---------------------------------------------------------------- internals

  private persistFailure(task: ScheduledTask, err: unknown): TaskExecution {
    const nowMs = this.now();
    const exec: TaskExecution = {
      id: `${Date.now().toString(36)}-${randomUUID().slice(0, 8)}`,
      taskId: task.id,
      startedAt: new Date(nowMs).toISOString(),
      finishedAt: new Date(nowMs).toISOString(),
      status: 'error',
      durationMs: 0,
      error: redactText(err instanceof Error ? err.message : String(err)).slice(0, 2000),
    };
    this.storage.insertExecution(exec);
    this.storage.finishExecution(exec);
    return sanitizeExecution(exec);
  }

  private mustGet(id: string): NonNullable<ReturnType<TaskStorage['getTask']>> {
    const row = this.storage.getTask(id);
    if (!row) throw this.taskNotFound(id);
    return row;
  }

  private mustGetEntity(id: string): ScheduledTask {
    return rowToTask(this.mustGet(id));
  }

  private taskNotFound(id: string): AppError2 {
    return userError(`Scheduled task "${id}" not found`, 'TASK_NOT_FOUND');
  }

  /** Валидация цели через registry: провайдер существует/enabled, tool существует/enabled. */
  private validateTarget(providerId: string, toolName: string): void {
    const provider = this.registry.getProvider(providerId);
    if (!provider) throw userError(`Provider "${providerId}" does not exist`, 'TASK_PROVIDER_NOT_FOUND');
    if (!this.registry.isEnabled(providerId)) {
      throw userError(`Provider "${providerId}" is disabled`, 'TASK_PROVIDER_DISABLED');
    }
    const tool = provider.getTools().find((t) => t.name === toolName);
    if (!tool) throw userError(`Tool "${toolName}" does not exist in provider "${providerId}"`, 'TASK_TOOL_NOT_FOUND');
    if (!this.registry.isToolEnabled(toolName)) {
      throw userError(`Tool "${toolName}" is disabled in provider "${providerId}"`, 'TASK_TOOL_DISABLED');
    }
  }

  private resolveId(data: TaskInput, name: string): string {
    if (data.id) {
      if (!ID_SLUG_RE.test(data.id)) {
        throw userError('Task id must match [a-zA-Z0-9_-]{1,64}', 'INVALID_TASK_ID');
      }
      if (this.storage.getTask(data.id)) {
        throw userError(`Task id "${data.id}" already exists`, 'TASK_ID_EXISTS');
      }
      return data.id;
    }
    const base = slugify(name) || 'task';
    if (!this.storage.getTask(base)) return base;
    return `${base}-${randomUUID().slice(0, 6)}`;
  }

  private computeStatus(opts: { enabled: boolean; isOnce: boolean; ranOnce: boolean; lastRunAtIsSet: boolean }): ScheduledTask['status'] {
    if (!opts.enabled) return 'paused';
    if (opts.isOnce && opts.ranOnce && opts.lastRunAtIsSet) return 'completed';
    return 'active';
  }

  /** Убрать потенциальные секреты из task перед отдачей наружу. */
  private sanitize(task: ScheduledTask): ScheduledTask {
    return { ...task, action: { ...task.action, input: redactValue(task.action.input ?? {}) } };
  }
}

function sanitizeExecution(exec: TaskExecution): TaskExecution {
  return {
    ...exec,
    result: exec.result === undefined ? undefined : redactValue(exec.result),
    error: exec.error === undefined ? undefined : redactText(exec.error),
  };
}

function parseJsonSafe(json: string): unknown {
  try {
    return JSON.parse(json);
  } catch {
    return undefined;
  }
}

function slugify(value: string): string {
  const slug = value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 48);
  return slug;
}

type AppError2 = ReturnType<typeof userError>;