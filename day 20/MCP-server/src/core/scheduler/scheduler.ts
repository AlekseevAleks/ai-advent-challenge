import type { Logger } from '../logging/logger.js';
import type { SchedulerSettings } from '../types.js';
import type { TaskStorage } from './task-storage.js';
import { rowToTask } from './task-storage.js';
import type { TaskManager } from './task-manager.js';
import { computeNextRunAtMs } from './schedule-utils.js';

export interface SchedulerOptions {
  storage: TaskStorage;
  taskManager: TaskManager;
  logger: Logger;
  getSettings: () => SchedulerSettings;
  /** Текущее время (ms), переопределяется в тестах. */
  now?: () => number;
}

const MAX_TIMER_DELAY_MS = 3600_000; // таймер не дольше часа — перевооружаемся точно

/**
 * Scheduler: отвечает ТОЛЬКО за время запуска.
 * - при старте: восстанавливает nextRunAt, сбрасывает «зависшие» running-флаги;
 * - ставит один таймер на ближайшую задачу (не poll'ит каждую секунду)
 *   плюс редкий страховочный интервал (tickIntervalMs) на случай сбоя таймера;
 * - выполнение делегирует в TaskManager.executeDue → TaskExecutor;
 * - пропущенные cron-срабатывания «перескакиваются» (nextRunAt всегда в будущем);
 * - один раз выполняется once-задача, if она «просрочена» после рестарта.
 */
export class Scheduler {
  private readonly storage: TaskStorage;
  private readonly taskManager: TaskManager;
  private readonly logger: Logger;
  private readonly getSettings: () => SchedulerSettings;
  private readonly now: () => number;

  private started = false;
  private stopped = false;
  private timer: NodeJS.Timeout | null = null;
  private safetyTimer: NodeJS.Timeout | null = null;
  private ticking: Promise<void> | null = null;

  constructor(opts: SchedulerOptions) {
    this.storage = opts.storage;
    this.taskManager = opts.taskManager;
    this.logger = opts.logger;
    this.getSettings = opts.getSettings;
    this.now = opts.now ?? (() => Date.now());
  }

  get isRunning(): boolean {
    return this.started;
  }

  /** Запуск вместе с сервером. */
  start(): void {
    if (this.started) return;
    const settings = this.getSettings();
    if (!settings.enabled) {
      this.logger.info('[Scheduler] disabled by configuration');
      this.started = true;
      this.stopped = false;
      return;
    }
    this.started = true;
    this.stopped = false;

    // После рестарта не должно оставаться «зависших» флагов выполнения
    this.storage.resetRunningFlags();
    this.ensureNextRuns();

    this.arm();
    const interval = Math.max(1000, settings.tickIntervalMs || 60_000);
    this.safetyTimer = setInterval(() => {
      void this.tick();
    }, interval);
    if (typeof this.safetyTimer.unref === 'function') this.safetyTimer.unref();
    this.logger.info(`[Scheduler] started (timer-based; safety poll ${interval}ms)`);
  }

  /** Остановка: без новых запусков, дожидаемся текущего выполнения. */
  async stop(): Promise<void> {
    if (!this.started) return;
    this.stopped = true;
    this.started = false;
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    if (this.safetyTimer) {
      clearInterval(this.safetyTimer);
      this.safetyTimer = null;
    }
    if (this.ticking) {
      this.logger.info('[Scheduler] waiting for in-flight execution...');
      await this.ticking;
    }
  }

  /** Вызывается TaskManager'ом при изменении задач — перевооружаем таймер. */
  notifyChanged(): void {
    if (this.started) this.arm();
  }

  // ------------------------------------------------------------ internals

  /** Для тестов: мгновенная проверка «просроченных» задач. */
  async tickNow(): Promise<void> {
    await this.runDue();
  }

  private ensureNextRuns(): void {
    for (const row of this.storage.listTasks()) {
      if (row.enabled !== 1 || row.status !== 'active') continue;
      if (row.next_run_at) continue;
      const task = rowToTask(row);
      const next = computeNextRunAtMs(task.schedule, this.now());
      if (next !== null) {
        this.storage.updateNextRunAt(task.id, new Date(next).toISOString());
      }
    }
  }

  private arm(): void {
    if (!this.started || this.stopped) return;
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    const next = this.storage.findNextPending();
    if (!next?.next_run_at) return;
    const dueMs = Date.parse(next.next_run_at);
    if (Number.isNaN(dueMs)) return;
    const delay = Math.min(Math.max(100, dueMs - this.now()), MAX_TIMER_DELAY_MS);
    this.timer = setTimeout(() => {
      this.timer = null;
      void this.tick();
    }, delay);
    if (typeof this.timer.unref === 'function') this.timer.unref();
  }

  private tick(): Promise<void> {
    if (this.ticking) return this.ticking;
    this.ticking = this.runDue().finally(() => {
      this.ticking = null;
    });
    return this.ticking;
  }

  private async runDue(): Promise<void> {
    try {
      const due = this.storage.findDueTasks(new Date(this.now()).toISOString());
      for (const row of due) {
        if (this.stopped) break;
        try {
          await this.taskManager.executeDue(row.id);
        } catch (err) {
          this.logger.error('[Scheduler] unexpected tick error', { taskId: row.id, error: err instanceof Error ? err.message : String(err) });
        }
      }
    } finally {
      if (this.started && !this.stopped) this.arm();
    }
  }
}