import { describe, expect, it, afterEach } from 'vitest';
import { createSchedulerHarness, weatherOk, type SchedulerHarness } from './helpers.js';

let h: SchedulerHarness | undefined;
afterEach(() => h?.cleanup());

const SECRET = 'ghp_SUPERSECRETTOKEN1234567890';
const action = (provider: string, tool: string, input?: unknown) => ({ type: 'provider_tool' as const, provider, tool, input });

describe('Scheduler security (redaction)', () => {
  it('does not leak secrets from task input through REST/UI task objects', async () => {
    h = await createSchedulerHarness({ onFetch: weatherOk });
    await h.harness.registry.loadProviders();
    await h.harness.registry.initializeAll();

    const created = await h.manager.create({
      name: 'Secret Input',
      schedule: { type: 'cron', cron: '0 * * * *', timezone: 'UTC' },
      action: action('weather', 'weather_current', { latitude: 52.52, longitude: 13.405, apiKey: SECRET, Authorization: `Bearer ${SECRET}` }),
    });

    const fetched = await h.manager.getTask(created.id);
    const serialized = JSON.stringify(fetched);
    expect(serialized).not.toContain(SECRET);
    expect(serialized).toContain('[REDACTED]');
    const input = fetched.action.input as Record<string, unknown>;
    expect(input.apiKey).toBe('[REDACTED]');
    expect(input.Authorization).toBe('[REDACTED]');
  });

  it('does not leak secrets in execution history', async () => {
    h = await createSchedulerHarness({ onFetch: weatherOk });
    await h.harness.registry.loadProviders();
    await h.harness.registry.initializeAll();
    const task = await h.manager.create({
      name: 'Leaky Result',
      schedule: { type: 'cron', cron: '0 * * * *', timezone: 'UTC' },
      action: action('weather', 'weather_current', {}),
    });
    // Намеренно кладём «секретные» ключи в результат (как если бы tool их вернул)
    const recent = new Date(h.clock.value - 60_000).toISOString();
    const recentFinish = new Date(h.clock.value - 59_900).toISOString();
    h.storage.insertExecution({
      id: 'leaky-1',
      taskId: task.id,
      startedAt: recent,
      finishedAt: recentFinish,
      status: 'success',
      durationMs: 100,
      result: { temperatureC: 21, token: SECRET, apiKey: 'another-secret-123', data: { password: 'p@ss' } },
    });
    h.storage.finishExecution({
      id: 'leaky-1',
      taskId: task.id,
      startedAt: recent,
      finishedAt: recentFinish,
      status: 'success',
      durationMs: 100,
      result: { temperatureC: 21, token: SECRET, apiKey: 'another-secret-123', data: { password: 'p@ss' } },
    });

    const history = await h.manager.getHistory(task.id, 0, 10);
    const serialized = JSON.stringify(history);
    expect(serialized).not.toContain(SECRET);
    expect(serialized).not.toContain('another-secret-123');
    expect(serialized).not.toContain('p@ss');
    expect(serialized).toContain('[REDACTED]');

    const summary = await h.manager.getSummary(task.id, { window: '24h' });
    const sumText = JSON.stringify(summary);
    expect(sumText).not.toContain(SECRET);
    expect(sumText).not.toContain('another-secret-123');
    expect(summary.numericSeries['temperatureC'].avg).toBe(21); // числовые данные агрегируются
  });

  it('redacts error messages in history (no tokens, no stack traces)', async () => {
    h = await createSchedulerHarness({
      onFetch: () => new Response('fail', { status: 500 }),
    });
    await h.harness.registry.loadProviders();
    await h.harness.registry.initializeAll();
    const task = await h.manager.create({
      name: 'Failing',
      schedule: { type: 'cron', cron: '0 * * * *', timezone: 'UTC' },
      action: action('weather', 'weather_current', {}),
    });
    // Провоцируем ошибку, содержащую секрет: Http клиент экономит его в сообщении? Нет —
    // вместо этого провайдер вернёт 500 с текстом, и мы добавляем секрет в URL через input.
    // Для проверки редaкции целенаправленно передадим секрет в input как «виновный» параметр.
    await h.manager.update(task.id, { action: action('weather', 'weather_current', { token: SECRET }) });
    const execution = await h.manager.runNow(task.id);
    expect(execution.status).toBe('error');
    const history = await h.manager.getHistory(task.id, 0, 10);
    const serialized = JSON.stringify(history);
    expect(serialized).not.toContain(SECRET);
  });

  it('executions do not expose raw results via SQL rows with secrets (storage-level sanitization on read)', async () => {
    h = await createSchedulerHarness({
      onFetch: () => new Response(JSON.stringify({ ok: true, session: 'cookie-session-xyz' }), { status: 200 }),
    });
    await h.harness.registry.loadProviders();
    await h.harness.registry.initializeAll();
    const task = await h.manager.create({
      name: 'Session',
      schedule: { type: 'cron', cron: '0 * * * *', timezone: 'UTC' },
      action: action('weather', 'weather_current', {}),
    });
    await h.manager.runNow(task.id);
    const history = await h.manager.getHistory(task.id, 0, 10);
    expect(JSON.stringify(history)).not.toContain('cookie-session-xyz');
  });

  it('list_tasks redacts inputs too', async () => {
    h = await createSchedulerHarness({ onFetch: weatherOk });
    await h.harness.registry.loadProviders();
    await h.harness.registry.initializeAll();
    await h.manager.create({
      name: 'WithKey',
      schedule: { type: 'cron', cron: '0 * * * *', timezone: 'UTC' },
      action: action('weather', 'weather_current', { apiKey: SECRET }),
    });
    const items = h.manager.listTasks();
    expect(JSON.stringify(items)).not.toContain(SECRET);
  });
});