import { randomUUID } from 'node:crypto';
import { AppError, internalError, userError } from '../errors.js';
import type { Logger } from '../logging/logger.js';
import type { ProviderRegistry } from '../registry/provider-registry.js';
import { redactText } from '../util/redact.js';
import type { ScheduledTask, TaskExecution } from './task-types.js';
import type { SchedulerRetrySettings, SchedulerSettings } from '../types.js';
import type { TaskStorage } from './task-storage.js';
import type { PipelineExecutor } from '../pipeline/pipeline-executor.js';
import { computeNextRunAtMs } from './schedule-utils.js';

export interface TaskExecutorOptions {
  registry: ProviderRegistry;
  storage: TaskStorage;
  logger: Logger;
  getSettings: () => SchedulerSettings;
  /** Для задач с action.type = 'pipeline'. */
  pipelineExecutor?: PipelineExecutor;
  /** Текущее время (ms), переопределяется в тестах. */
  now?: () => number;
}

const MAX_ERROR_LENGTH = 2000;

/**
 * TaskExecutor: выполняет одну задачу — проверяет доступность provider/tool,
 * вызывает его через ProviderRegistry (то есть ровно тот же путь, что и MCP),
 * сохраняет результат и историю, обновляет состояние задачи.
 */
export class TaskExecutor {
  private readonly registry: ProviderRegistry;
  private readonly storage: TaskStorage;
  private readonly logger: Logger;
  private readonly getSettings: () => SchedulerSettings;
  private readonly pipelineExecutor?: PipelineExecutor;
  private readonly now: () => number;

  constructor(opts: TaskExecutorOptions) {
    this.registry = opts.registry;
    this.storage = opts.storage;
    this.logger = opts.logger;
    this.getSettings = opts.getSettings;
    this.pipelineExecutor = opts.pipelineExecutor;
    this.now = opts.now ?? (() => Date.now());
  }

  /**
   * Выполнить задачу. Возвращает запись выполнения (success или error).
   * Бросает только при ошибках валидации/занятости (TASK_RUNNING и т.п.).
   */
  async execute(task: ScheduledTask): Promise<TaskExecution> {
    const startedAt = new Date(this.now()).toISOString();
    const executionId = `${Date.now().toString(36)}-${randomUUID().slice(0, 8)}`;

    // 1. проверки ДО захвата (быстрые и понятные)
    if (task.action.type === 'pipeline') {
      if (!this.pipelineExecutor) {
        throw userError('Pipelines are not available in this server', 'PIPELINES_UNAVAILABLE');
      }
    } else {
      const resolved = this.resolveTarget(task);
      if (!resolved.available) {
        throw userError(
          `Provider "${task.action.provider}" or tool "${task.action.tool}" is not available (disabled or unknown). Scheduled task is not executed.`,
          'TASK_TARGET_UNAVAILABLE',
        );
      }
      if (!resolved.enabled) {
        throw userError(`Tool "${task.action.tool}" is disabled in provider "${task.action.provider}"`, 'TASK_TOOL_DISABLED');
      }
    }

    // 2. атомарный захват — защита от двойного запуска
    if (!this.storage.claimRunning(task.id)) {
      throw userError(`Task "${task.id}" is already running`, 'TASK_RUNNING');
    }

    const execution: TaskExecution = {
      id: executionId,
      taskId: task.id,
      startedAt,
      status: 'running',
    };
    this.storage.insertExecution(execution);
    this.logger.info(`[Scheduler] task ${task.id} started`, {
      taskId: task.id,
      taskName: task.name,
      provider: task.action.provider,
      tool: task.action.tool,
      executionId,
    });

    try {
      const result = await this.runWithRetry(task);
      const finishedAt = new Date(this.now()).toISOString();
      execution.status = 'success';
      execution.finishedAt = finishedAt;
      execution.durationMs = this.now() - new Date(startedAt).getTime();
      execution.result = result;
      this.storage.finishExecution(execution);
      this.logger.info(`[Scheduler] task ${task.id} completed in ${execution.durationMs}ms`, {
        taskId: task.id,
        taskName: task.name,
        executionId,
        status: 'success',
        duration: execution.durationMs,
      });
      this.afterRun(task, 'success');
      return execution;
    } catch (err) {
      const finishedAt = new Date(this.now()).toISOString();
      const appErr = err instanceof AppError ? err : internalError('Unexpected task execution error', 'TASK_EXECUTION_ERROR', err);
      if (appErr.kind === 'internal') {
        this.logger.error(`[Scheduler] task ${task.id} crashed`, {
          taskId: task.id,
          executionId,
          stack: appErr.cause instanceof Error ? appErr.cause.stack : undefined,
        });
      }
      const message = redactText(appErr.message).slice(0, MAX_ERROR_LENGTH);
      execution.status = 'error';
      execution.finishedAt = finishedAt;
      execution.durationMs = this.now() - new Date(startedAt).getTime();
      execution.error = message;
      this.storage.finishExecution(execution);
      this.logger.warn(`[Scheduler] task ${task.id} failed: ${message}`, {
        taskId: task.id,
        taskName: task.name,
        executionId,
        status: 'error',
        duration: execution.durationMs,
        reason: message,
      });
      this.afterRun(task, 'error');
      return execution;
    } finally {
      this.storage.releaseRunning(task.id);
    }
  }

  /** Обновить задачу после выполнения: lastRunAt, nextRunAt, статус (cron остаётся active после ошибок). */
  private afterRun(task: ScheduledTask, outcome: 'success' | 'error'): void {
    const nowMs = this.now();
    const nextRun = computeNextRunAtMs(task.schedule, nowMs);
    let status: 'active' | 'completed' | 'error' = 'active';
    if (task.schedule.type === 'once') {
      const executeAt = Date.parse(task.schedule.executeAt ?? '');
      const wasDueBefore = !Number.isNaN(executeAt) && executeAt <= nowMs;
      status = outcome === 'success' ? 'completed' : 'error';
      if (wasDueBefore && outcome === 'error') status = 'error';
    } else {
      status = 'active';
    }
    this.storage.updateTaskRunState(task.id, {
      lastRunAt: new Date(nowMs).toISOString(),
      nextRunAt: nextRun !== null ? new Date(nextRun).toISOString() : null,
      status,
    });
  }

  private runWithRetry(task: ScheduledTask): Promise<unknown> {
    const settings = this.getSettings();
    const retry: SchedulerRetrySettings = settings.retry ?? { enabled: true, maxAttempts: 3, delayMs: 5000 };
    const maxAttempts = retry.enabled ? Math.max(1, retry.maxAttempts) : 1;

    const attempt = async (count: number): Promise<unknown> => {
      try {
        if (task.action.type === 'pipeline') {
          if (!this.pipelineExecutor) throw userError('Pipelines are not available in this server', 'PIPELINES_UNAVAILABLE');
          return await this.pipelineExecutor.run(task.action.pipeline ?? '', (task.action.input ?? {}) as Record<string, unknown>);
        }
        return await this.registry.executeTool(task.action.tool ?? '', task.action.input ?? {});
      } catch (err) {
        if (count < maxAttempts) {
          const delay = this.retryDelay(err, retry);
          this.logger.warn(
            `[Scheduler] task ${task.id}: provider call failed (attempt ${count}/${maxAttempts}), retry in ${delay}ms`,
            { taskId: task.id, attempt: count, message: err instanceof Error ? redactText(err.message) : String(err) },
          );
          await sleep(delay);
          return attempt(count + 1);
        }
        throw err;
      }
    };
    return attempt(1);
  }

  private retryDelay(err: unknown, retry: SchedulerRetrySettings): number {
    if (err instanceof AppError && err.kind === 'rate_limit' && err.retryAfter !== undefined) {
      return Math.min(err.retryAfter * 1000, 120_000);
    }
    return Math.max(0, retry.delayMs);
  }

  /** Проверка доступности цели через registry (единый источник truth о tools). */
  private resolveTarget(task: ScheduledTask): { available: boolean; enabled: boolean } {
    const provider = this.registry.getProvider(task.action.provider ?? '');
    if (!provider) return { available: false, enabled: false };
    const resolved = this.registry
      .getTools()
      .find((t) => t.providerId === task.action.provider && t.tool.name === task.action.tool);
    if (!resolved) return { available: false, enabled: false };
    return { available: true, enabled: resolved.enabled };
  }
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));