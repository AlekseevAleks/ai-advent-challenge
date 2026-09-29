import path from 'node:path';
import type { SchedulerSettings } from '../../src/core/types.js';
import { Logger } from '../../src/core/logging/logger.js';
import { TaskStorage } from '../../src/core/scheduler/task-storage.js';
import { TaskExecutor } from '../../src/core/scheduler/task-executor.js';
import { TaskManager } from '../../src/core/scheduler/task-manager.js';
import { Scheduler } from '../../src/core/scheduler/scheduler.js';
import { createHarness, type Harness } from '../helpers.js';

export interface Clock {
  value: number;
  set(ms: number): void;
  advance(ms: number): void;
}

export interface SchedulerHarness {
  harness: Harness;
  storage: TaskStorage;
  executor: TaskExecutor;
  manager: TaskManager;
  scheduler: Scheduler;
  settings: SchedulerSettings;
  clock: Clock;
  cleanup: () => void;
}

export function defaultSchedulerSettings(overrides: Partial<SchedulerSettings> = {}): SchedulerSettings {
  return {
    enabled: true,
    tickIntervalMs: 60_000,
    maxStoredExecutionsPerTask: 100,
    executionRetentionDays: 7,
    retry: { enabled: false, maxAttempts: 1, delayMs: 0 },
    ...overrides,
  };
}

/** Полный стек Scheduler с реальными registry/providers и управляемыми часами. */
export async function createSchedulerHarness(opts: {
  providerConfigs?: Record<string, unknown>;
  onFetch?: (url: string, init?: RequestInit) => Response;
  settings?: Partial<SchedulerSettings>;
  now?: number;
  /** Переиспользовать существующий файл БД (для тестов restart). */
  dbPath?: string;
} = {}): Promise<SchedulerHarness> {
  const harness = createHarness({
    providerConfigs: opts.providerConfigs,
    onFetch: opts.onFetch,
  });
  // Регистрируем и инициализируем провайдеров сразу (как делает runtime),
  // чтобы TaskManager.create мог валидировать provider/tool.
  await harness.registry.loadProviders();
  await harness.registry.initializeAll();
  const dbPath = opts.dbPath ?? path.join(harness.dataDir, 'scheduler-test.db');
  const clock: Clock = {
    value: opts.now ?? Date.now(),
    set: (ms) => {
      clock.value = ms;
    },
    advance: (ms) => {
      clock.value += ms;
    },
  };
  const storage = new TaskStorage(dbPath);
  const settings = defaultSchedulerSettings(opts.settings);
  const logger = new Logger({ level: 'silent' });

  const executor = new TaskExecutor({
    registry: harness.registry,
    storage,
    logger,
    getSettings: () => settings,
    now: () => clock.value,
  });

  let schedulerRef: Scheduler | undefined;
  const manager = new TaskManager({
    storage,
    executor,
    registry: harness.registry,
    logger,
    getSettings: () => settings,
    onTaskChanged: () => schedulerRef?.notifyChanged(),
    now: () => clock.value,
  });

  const scheduler = new Scheduler({
    storage,
    taskManager: manager,
    logger,
    getSettings: () => settings,
    now: () => clock.value,
  });
  schedulerRef = scheduler;

  return {
    harness,
    storage,
    executor,
    manager,
    scheduler,
    settings,
    clock,
    cleanup: () => {
      scheduler.stop().catch(() => undefined);
      storage.close();
      harness.cleanup();
    },
  };
}

export const weatherOk = (): Response =>
  new Response(
    JSON.stringify({
      latitude: 52.52,
      longitude: 13.405,
      timezone: 'auto',
      current: { time: '2026-09-27T10:00', temperature_2m: 20.5, weather_code: 2, wind_speed_10m: 11.2 },
      current_units: { temperature_2m: '°C', wind_speed_10m: 'km/h' },
    }),
    { status: 200 },
  );