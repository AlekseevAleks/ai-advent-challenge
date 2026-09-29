import { describe, expect, it, afterEach } from 'vitest';
import { createSchedulerHarness, weatherOk, type SchedulerHarness } from './helpers.js';
import type { TaskInputLeft } from './task-input.js';
import { rowToTask } from '../../src/core/scheduler/task-storage.js';
import type { ScheduledTask } from '../../src/core/scheduler/task-types.js';

let h: SchedulerHarness | undefined;
afterEach(() => h?.cleanup());

const action = (provider: string, tool: string, input?: unknown) => ({ type: 'provider_tool' as const, provider, tool, input });
const cronSched = (cron: string, timezone = 'UTC') => ({ type: 'cron' as const, cron, timezone });

function makeTask(overrides: Partial<ScheduledTask> = {}): ScheduledTask {
  return {
    id: 'exec-task',
    name: 'Exec Task',
    enabled: true,
    schedule: { type: 'cron', cron: '0 * * * *', timezone: 'UTC' },
    action: { type: 'provider_tool', provider: 'weather', tool: 'weather_current', input: { latitude: 52.52, longitude: 13.405 } },
    aggregation: { enabled: true, strategy: 'auto' },
    createdAt: '2026-09-27T10:00:00.000Z',
    updatedAt: '2026-09-27T10:00:00.000Z',
    nextRunAt: '2026-09-27T11:00:00.000Z',
    status: 'active',
    running: false,
    version: 1,
    ...overrides,
  };
}

describe('TaskExecutor', () => {
  it('validates provider/tool availability and enabled state', async () => {
    h = await createSchedulerHarness({
      providerConfigs: { weather: { id: 'weather', enabled: true, tools: { weather_current: { enabled: false } } } },
      onFetch: weatherOk,
    });
    await h.harness.registry.loadProviders();
    await h.harness.registry.initializeAll();

    // tool выключен → runNow возвращает error-выполнение с понятным сообщением
    const task = makeTask();
    h.storage.insertTask(task);
    const execution = await h.manager.runNow(task.id);
    expect(execution.status).toBe('error');
    expect(execution.error).toContain('disabled');

    // несуществующий tool → тоже error
    h.storage.updateTask(makeTask({ action: { type: 'provider_tool', provider: 'weather', tool: 'nope_tool', input: {} } }));
    const execution2 = await h.manager.runNow(task.id);
    expect(execution2.status).toBe('error');
    expect(execution2.error).toMatch(/not available|disabled/);
  });

  it('successful execution stores result and updates task state', async () => {
    h = await createSchedulerHarness({ onFetch: weatherOk });
    await h.harness.registry.loadProviders();
    await h.harness.registry.initializeAll();
    const task = makeTask();
    h.storage.insertTask(task);

    const execution = await h.executor.execute(task);
    expect(execution.status).toBe('success');
    expect((execution.result as Record<string, unknown>).weather).toBeDefined();

    const row = h.storage.getTask(task.id)!;
    expect(row.last_run_at).toBeTruthy();
    expect(row.next_run_at).toBeTruthy();
    const next = Date.parse(rowToTask(row).nextRunAt as string);
    expect(next).toBeGreaterThan(Date.parse(task.nextRunAt as string));
  });

  it('failed execution stores error and keeps cron task active', async () => {
    h = await createSchedulerHarness({ onFetch: () => new Response('{"message":"boom"}', { status: 400 }) });
    await h.harness.registry.loadProviders();
    await h.harness.registry.initializeAll();
    const task = makeTask();
    h.storage.insertTask(task);

    const execution = await h.executor.execute(task);
    expect(execution.status).toBe('error');
    expect(execution.error).toContain('boom');
    const row = h.storage.getTask(task.id)!;
    expect(row.status).toBe('active');
    expect(row.last_run_at).toBeTruthy();
  });

  it('does not retry when retry is disabled', async () => {
    let calls = 0;
    h = await createSchedulerHarness({
      onFetch: () => {
        calls++;
        return new Response('fail', { status: 400 });
      },
      settings: { retry: { enabled: false, maxAttempts: 3, delayMs: 0 } },
    });
    await h.harness.registry.loadProviders();
    await h.harness.registry.initializeAll();
    h.storage.insertTask(makeTask());
    await h.executor.execute(makeTask());
    expect(calls).toBe(1);
  });

  it('retries up to maxAttempts and reports the final error', async () => {
    let calls = 0;
    h = await createSchedulerHarness({
      onFetch: () => {
        calls++;
        return new Response('fail', { status: 400 });
      },
      settings: { retry: { enabled: true, maxAttempts: 3, delayMs: 0 } },
    });
    await h.harness.registry.loadProviders();
    await h.harness.registry.initializeAll();
    const task = makeTask();
    h.storage.insertTask(task);
    const execution = await h.executor.execute(task);
    expect(calls).toBe(3);
    expect(execution.status).toBe('error');
  });

  it('protects from concurrent execution via claim', async () => {
    h = await createSchedulerHarness({ onFetch: weatherOk });
    await h.harness.registry.loadProviders();
    await h.harness.registry.initializeAll();
    const task = makeTask();
    h.storage.insertTask(task);
    // Принудительно «занято»
    expect(h.storage.claimRunning(task.id)).toBe(true);
    await expect(h.executor.execute(task)).rejects.toMatchObject({ code: 'TASK_RUNNING' });
    h.storage.releaseRunning(task.id);
    const execution = await h.executor.execute(task);
    expect(execution.status).toBe('success');
  });

  it('once task executes via scheduler after restart (missed while down)', async () => {
    h = await createSchedulerHarness({ onFetch: weatherOk });
    await h.harness.registry.loadProviders();
    await h.harness.registry.initializeAll();
    const past = new Date(h.clock.value - 30 * 60_000).toISOString();
    h.storage.insertTask(
      makeTask({ id: 'once-missed', schedule: { type: 'once', executeAt: past, timezone: 'UTC' }, nextRunAt: past, lastRunAt: undefined }),
    );
    const execution = await h.executor.execute(makeTask({ id: 'once-missed', schedule: { type: 'once', executeAt: past, timezone: 'UTC' }, nextRunAt: past }));
    expect(execution.status).toBe('success');
    const row = h.storage.getTask('once-missed')!;
    expect(row.status).toBe('completed');
  });
});