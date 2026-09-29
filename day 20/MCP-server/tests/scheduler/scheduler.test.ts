import { describe, expect, it, afterEach } from 'vitest';
import { mkdtempSync, rmSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createSchedulerHarness, weatherOk, type SchedulerHarness } from './helpers.js';
import type { TaskInputLeft } from './task-input.js';
import { computeNextRunAtMs } from '../../src/core/scheduler/schedule-utils.js';

let h: SchedulerHarness | undefined;
afterEach(() => h?.cleanup());

const action = (provider: string, tool: string, input?: unknown) => ({ type: 'provider_tool' as const, provider, tool, input });
const cronSched = (cron: string, timezone = 'UTC') => ({ type: 'cron' as const, cron, timezone });

async function seedTask(id: string, input: TaskInputLeft): Promise<void> {
  await h!.manager.create({ ...input, id });
}

describe('Scheduler', () => {
  it('executes a due cron task and recomputes nextRunAt in the future', async () => {
    h = await createSchedulerHarness({ onFetch: weatherOk, now: Date.UTC(2026, 8, 27, 10, 30, 0) });
    await h.harness.registry.loadProviders();
    await h.harness.registry.initializeAll();
    h.scheduler.start();

    await seedTask('hourly', {
      name: 'Hourly',
      schedule: cronSched('0 * * * *', 'UTC'),
      action: action('weather', 'weather_current', { latitude: 52.52, longitude: 13.405 }),
    });
    h.clock.set(Date.UTC(2026, 8, 27, 11, 0, 1)); // минута после срабатывания
    await h.scheduler.tickNow();

    const history = await h.manager.getHistory('hourly', 0, 10);
    expect(history.total).toBe(1);
    expect(history.items[0].status).toBe('success');
    const task = await h.manager.getTask('hourly');
    expect(Date.parse(task.nextRunAt as string)).toBeGreaterThan(h.clock.value); // пропущенные циклы не нагоняем
  });

  it('executes a once task that became due while the server was down', async () => {
    h = await createSchedulerHarness({ onFetch: weatherOk, now: Date.UTC(2026, 8, 27, 10, 0, 0) });
    await h.harness.registry.loadProviders();
    await h.harness.registry.initializeAll();
    h.scheduler.start();

    const past = new Date(h.clock.value - 60 * 60_000).toISOString();
    // задача «пережила рестарт»: once-задача стала просроченной, пока сервер лежал.
    // Создание с executeAt в прошлом валидация не пропускает, поэтому вставляем напрямую в БД.
    h.storage.insertTask({
      id: 'once',
      name: 'Once',
      enabled: true,
      schedule: { type: 'once', executeAt: past, timezone: 'UTC' },
      action: { type: 'provider_tool', provider: 'weather', tool: 'weather_current', input: { latitude: 52.52, longitude: 13.405 } },
      aggregation: { enabled: true, strategy: 'auto' },
      createdAt: past,
      updatedAt: past,
      nextRunAt: past,
      status: 'active',
      running: false,
      version: 1,
    });
    await h.scheduler.tickNow();
    const task = await h.manager.getTask('once');
    expect(task.status).toBe('completed');
    expect((await h.manager.getHistory('once', 0, 10)).total).toBe(1);
  });

  it('skips disabled tasks', async () => {
    h = await createSchedulerHarness({ onFetch: weatherOk });
    await h.harness.registry.loadProviders();
    await h.harness.registry.initializeAll();
    h.scheduler.start();

    await seedTask('disabled', {
      name: 'Disabled',
      enabled: false,
      schedule: cronSched('* * * * *', 'UTC'),
      action: action('weather', 'weather_current', { latitude: 52.52, longitude: 13.405 }),
    });
    await h.scheduler.tickNow();
    expect((await h.manager.getHistory('disabled', 0, 10)).total).toBe(0);
  });

  it('does not double-execute a task that is already running', async () => {
    let calls = 0;
    h = await createSchedulerHarness({
      onFetch: () => {
        calls++;
        return weatherOk();
      },
      now: Date.UTC(2026, 8, 27, 11, 0, 1),
    });
    await h.harness.registry.loadProviders();
    await h.harness.registry.initializeAll();
    h.scheduler.start();
    await seedTask('busy', {
      name: 'Busy',
      schedule: cronSched('* * * * *', 'UTC'),
      action: action('weather', 'weather_current', { latitude: 52.52, longitude: 13.405 }),
    });
    expect(h.storage.claimRunning('busy')).toBe(true); // «второй экземпляр» уже выполняет
    await h.scheduler.tickNow();
    expect(calls).toBe(0);
    expect((await h.manager.getHistory('busy', 0, 10)).total).toBe(0);
  });

  it('recovers after restart: task persists, nextRunAt recomputed, execution happens', async () => {
    const dbDir = mkdtempSync(path.join(os.tmpdir(), 'mcp-gw-restart-'));
    const dbPath = path.join(dbDir, 'scheduler.db');
    try {
      // --- запуск №1
      const first = await createSchedulerHarness({ dbPath, onFetch: weatherOk, now: Date.UTC(2026, 8, 27, 10, 45, 0) });
      await first.harness.registry.loadProviders();
      await first.harness.registry.initializeAll();
      first.scheduler.start();
      await first.manager.create({
        id: 'survivor',
        name: 'Survivor',
        schedule: cronSched('0 11 * * *', 'UTC'),
        action: action('weather', 'weather_current', { latitude: 52.52, longitude: 13.405 }),
      });
      const before = await first.manager.getTask('survivor');
      expect(before.nextRunAt).toBe('2026-09-27T11:00:00.000Z');

      // остановка «сервера»: scheduler останавливается, БД закрывается
      await first.scheduler.stop();
      first.storage.close();
      first.harness.cleanup();

      // --- «сервер» поднялся в 11:30 — задача просрочена
      const second = await createSchedulerHarness({
        dbPath,
        onFetch: weatherOk,
        now: Date.UTC(2026, 8, 27, 11, 30, 0),
      });
      await second.harness.registry.loadProviders();
      await second.harness.registry.initializeAll();
      second.scheduler.start();

      const persisted = await second.manager.getTask('survivor');
      expect(persisted.name).toBe('Survivor');
      expect(Date.parse(persisted.nextRunAt as string)).toBeLessThanOrEqual(second.clock.value); // просрочена

      await second.scheduler.tickNow();
      const history = await second.manager.getHistory('survivor', 0, 10);
      expect(history.total).toBe(1);
      const after = await second.manager.getTask('survivor');
      expect(after.lastRunAt).toBeTruthy();
      expect(Date.parse(after.nextRunAt as string)).toBeGreaterThan(second.clock.value);
      second.cleanup();
    } finally {
      rmSync(dbDir, { recursive: true, force: true });
    }
  });

  it('timezone: cron "0 9 * * *" in Europe/Berlin fires at 09:00 Berlin (07:00 UTC)', () => {
    // 2026-09-27 06:00 UTC = 08:00 по Берлину (UTC+2, лето)
    const nowMs = Date.UTC(2026, 8, 27, 6, 0, 0);
    const next = computeNextRunAtMs({ type: 'cron', cron: '0 9 * * *', timezone: 'Europe/Berlin' }, nowMs);
    expect(next).not.toBeNull();
    const hourInBerlin = new Intl.DateTimeFormat('en-US', { timeZone: 'Europe/Berlin', hour: '2-digit', hour12: false })
      .formatToParts(next as number)
      .find((part) => part.type === 'hour')?.value;
    expect(hourInBerlin).toBe('09');
    expect(new Date(next as number).getUTCDate()).toBe(27);
    expect(new Date(next as number).getUTCHours()).toBe(7);
  });
});