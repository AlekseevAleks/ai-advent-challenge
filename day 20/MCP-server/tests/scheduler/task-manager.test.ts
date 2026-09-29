import { describe, expect, it, afterEach } from 'vitest';
import { createSchedulerHarness, weatherOk, type SchedulerHarness } from './helpers.js';
import type { TaskInputLeft } from './task-input.js';

let h: SchedulerHarness | undefined;
afterEach(() => h?.cleanup());

const action = (provider: string, tool: string, input?: unknown) =>
  ({ type: 'provider_tool' as const, provider, tool, input });

const cronSched = (cron: string, timezone = 'UTC') => ({ type: 'cron' as const, cron, timezone });

async function errCode(promise: Promise<unknown>): Promise<string | undefined> {
  try {
    await promise;
    return undefined;
  } catch (err) {
    return (err as { code?: string }).code;
  }
}

const cronWeather: TaskInputLeft = {
  name: 'Berlin Weather',
  description: 'Collect weather every hour',
  schedule: cronSched('0 * * * *', 'Europe/Berlin'),
  action: action('weather', 'weather_current', { latitude: 52.52, longitude: 13.405 }),
};

describe('TaskManager', () => {
  it('creates a cron task with computed nextRunAt', async () => {
    h = await createSchedulerHarness({ onFetch: weatherOk });
    const task = await h.manager.create(cronWeather);
    expect(task.id).toMatch(/^[a-z0-9-]+$/);
    expect(task.status).toBe('active');
    expect(task.enabled).toBe(true);
    expect(task.schedule.cron).toBe('0 * * * *');
    expect(task.nextRunAt).toBeTruthy();
    const minuteInTz = Number(
      new Intl.DateTimeFormat('en-US', { timeZone: 'Europe/Berlin', minute: '2-digit' }).formatToParts(new Date(task.nextRunAt as string)).find((p) => p.type === 'minute')?.value,
    );
    expect(minuteInTz).toBe(0);
    expect(h.storage.getTask(task.id)).not.toBeNull();
  });

  it('uses explicit id if provided and rejects duplicates', async () => {
    h = await createSchedulerHarness({ onFetch: weatherOk });
    await h.manager.create({ ...cronWeather, id: 'weather-berlin' });
    expect(await errCode(h.manager.create({ ...cronWeather, id: 'weather-berlin' }))).toBe('TASK_ID_EXISTS');
  });

  it('creates a once task at a future time', async () => {
    h = await createSchedulerHarness({ onFetch: weatherOk });
    const future = new Date(h.clock.value + 60_000).toISOString();
    const task = await h.manager.create({
      name: 'Once',
      schedule: { type: 'once', executeAt: future, timezone: 'Europe/Berlin' },
      action: action('weather', 'weather_current', { latitude: 52.52, longitude: 13.405 }),
    });
    expect(task.schedule.type).toBe('once');
    expect(task.nextRunAt).toBe(future);
  });

  it('rejects once task in the past', async () => {
    h = await createSchedulerHarness({ onFetch: weatherOk });
    const past = new Date(h.clock.value - 60_000).toISOString();
    const err = await errCode(
      h.manager.create({ name: 'Once', schedule: { type: 'once', executeAt: past }, action: action('weather', 'weather_current') }),
    );
    expect(err).toBe('INVALID_TASK');
  });

  it('rejects unknown provider, disabled provider, unknown/disabled tool', async () => {
    h = await createSchedulerHarness({
      providerConfigs: {
        weather: { id: 'weather', enabled: true, tools: { weather_forecast: { enabled: false } } },
        github: { id: 'github', enabled: false },
      },
      onFetch: weatherOk,
    });

    expect(await errCode(h.manager.create({ name: 'x', schedule: cronSched('0 * * * *'), action: action('nope', 'weather_current') }))).toBe(
      'TASK_PROVIDER_NOT_FOUND',
    );
    expect(
      await errCode(h.manager.create({ name: 'x', schedule: cronSched('0 * * * *'), action: action('github', 'github_get_repository') })),
    ).toBe('TASK_PROVIDER_DISABLED');
    expect(await errCode(h.manager.create({ name: 'x', schedule: cronSched('0 * * * *'), action: action('weather', 'nope_tool') }))).toBe(
      'TASK_TOOL_NOT_FOUND',
    );
    expect(await errCode(h.manager.create({ name: 'x', schedule: cronSched('0 * * * *'), action: action('weather', 'weather_forecast') }))).toBe(
      'TASK_TOOL_DISABLED',
    );
  });

  it('rejects invalid cron and timezone', async () => {
    h = await createSchedulerHarness({ onFetch: weatherOk });
    expect(
      await errCode(
        h.manager.create({ name: 'x', schedule: { type: 'cron', cron: 'not-a-cron', timezone: 'UTC' }, action: action('weather', 'weather_current') }),
      ),
    ).toBe('INVALID_TASK');
    expect(
      await errCode(
        h.manager.create({ name: 'x', schedule: { type: 'cron', cron: '0 * * * *', timezone: 'Mars/Olympus' }, action: action('weather', 'weather_current') }),
      ),
    ).toBe('INVALID_TASK');
  });

  it('pause / resume / delete', async () => {
    h = await createSchedulerHarness({ onFetch: weatherOk });
    const created = await h.manager.create(cronWeather);

    const paused = await h.manager.pause(created.id);
    expect(paused.enabled).toBe(false);
    expect(paused.status).toBe('paused');
    expect(h.storage.findDueTasks('2099-01-01T00:00:00.000Z')).toHaveLength(0);

    const resumed = await h.manager.resume(created.id);
    expect(resumed.enabled).toBe(true);
    expect(resumed.status).toBe('active');
    expect(resumed.nextRunAt).toBeTruthy();

    const { deleted } = await h.manager.delete(created.id);
    expect(deleted).toBe(true);
    expect(await errCode(h.manager.getTask(created.id))).toBe('TASK_NOT_FOUND');
  });

  it('update changes schedule and recomputes nextRunAt', async () => {
    h = await createSchedulerHarness({ onFetch: weatherOk });
    const created = await h.manager.create(cronWeather);
    const updated = await h.manager.update(created.id, {
      name: 'Berlin Weather v2',
      schedule: cronSched('*/30 * * * *', 'UTC'),
      enabled: true,
    });
    expect(updated.name).toBe('Berlin Weather v2');
    expect(updated.schedule.cron).toBe('*/30 * * * *');
    const minutes = new Date(updated.nextRunAt as string).getUTCMinutes();
    expect([0, 30]).toContain(minutes);
  });

  it('runNow executes immediately and stores history', async () => {
    h = await createSchedulerHarness({ onFetch: weatherOk });
    const created = await h.manager.create(cronWeather);
    const execution = await h.manager.runNow(created.id);
    expect(execution.status).toBe('success');
    expect((execution.result as Record<string, unknown>).weather).toBeDefined();
    const history = await h.manager.getHistory(created.id, 0, 10);
    expect(history.total).toBe(1);
    expect(history.items[0].status).toBe('success');
    const updated = await h.manager.getTask(created.id);
    expect(updated.lastRunAt).toBeTruthy();
    expect(updated.nextRunAt).toBeTruthy();
  });

  it('once task becomes completed after success', async () => {
    h = await createSchedulerHarness({ onFetch: weatherOk });
    const future = new Date(h.clock.value + 120_000).toISOString();
    const created = await h.manager.create({
      name: 'Once',
      schedule: { type: 'once', executeAt: future, timezone: 'UTC' },
      action: action('weather', 'weather_current', { latitude: 52.52, longitude: 13.405 }),
    });
    await h.manager.runNow(created.id);
    const updated = await h.manager.getTask(created.id);
    expect(updated.status).toBe('completed');
  });

  it('cron task stays active after a failed run', async () => {
    h = await createSchedulerHarness({ onFetch: () => new Response('boom', { status: 500 }) });
    const created = await h.manager.create(cronWeather);
    const execution = await h.manager.runNow(created.id);
    expect(execution.status).toBe('error');
    const updated = await h.manager.getTask(created.id);
    expect(updated.status).toBe('active');
    expect(updated.lastRunAt).toBeTruthy();
  });

  it('demo tasks are created once and idempotent', async () => {
    h = await createSchedulerHarness({ onFetch: weatherOk });
    const first = await h.manager.createDemoTasks();
    expect(first.length).toBe(2);
    const tasks = h.manager.listTasks();
    expect(tasks.map((t) => t.id).sort()).toEqual(['demo-github-linux-issues', 'demo-weather-berlin']);
    const second = await h.manager.createDemoTasks();
    expect(second.length).toBe(0);
  });
});