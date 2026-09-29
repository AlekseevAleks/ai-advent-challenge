import { describe, expect, it } from 'vitest';
import { GenericAggregator } from '../../src/core/scheduler/aggregation/generic-aggregator.js';
import type { TaskExecution } from '../../src/core/scheduler/task-types.js';

function exec(id: string, startedAt: string, result: unknown, status: 'success' | 'error' = 'success'): TaskExecution {
  return { id, taskId: 't', startedAt, status, durationMs: 10, result, error: status === 'error' ? 'err' : undefined };
}

const weatherResults: TaskExecution[] = [
  exec('1', '2026-09-27T10:00:00.000Z', { temperatureC: 11.2, weather: { windSpeedKmh: 8, precipitationMm: 0 } }),
  exec('2', '2026-09-27T11:00:00.000Z', { temperatureC: 15.7, weather: { windSpeedKmh: 12, precipitationMm: 2.5 } }),
  exec('3', '2026-09-27T12:00:00.000Z', { temperatureC: 19.4, weather: { windSpeedKmh: 16, precipitationMm: 0 } }),
  exec('4', '2026-09-27T13:00:00.000Z', null as unknown as object, 'error'),
];

describe('GenericAggregator', () => {
  it('computes count/min/max/avg/latest/sum per numeric leaf path', async () => {
    const aggregator = new GenericAggregator();
    const summary = await aggregator.aggregate(weatherResults, { window: '24h' });

    expect(summary.executions).toEqual({ total: 4, success: 3, error: 1 });
    const t = summary.numericSeries['temperatureC'];
    expect(t.count).toBe(3);
    expect(t.min).toBe(11.2);
    expect(t.max).toBe(19.4);
    expect(t.avg).toBeCloseTo(15.433, 2);
    expect(t.sum).toBeCloseTo(46.3, 1);
    expect(t.latest).toBe(19.4);
    expect(t.first).toBe(11.2);

    const wind = summary.numericSeries['weather.windSpeedKmh'];
    expect(wind.max).toBe(16);
    expect(wind.min).toBe(8);
  });

  it('handles arrays: records length and aggregates item leaves', async () => {
    const aggregator = new GenericAggregator();
    const summary = await aggregator.aggregate(
      [exec('1', '2026-09-27T10:00:00.000Z', { count: 5, items: [{ stars: 100 }, { stars: 200 }] })],
      {},
    );
    expect(summary.numericSeries['count'].min).toBe(5);
    expect(summary.numericSeries['count'].max).toBe(5);
    expect(summary.numericSeries['items[].stars'].avg).toBe(150);
    expect(summary.numericSeries['items.length']).toBeDefined();
  });

  it('counts categorical values', async () => {
    const aggregator = new GenericAggregator();
    const summary = await aggregator.aggregate(
      [
        exec('1', '2026-09-27T10:00:00.000Z', { state: 'open' }),
        exec('2', '2026-09-27T11:00:00.000Z', { state: 'open' }),
        exec('3', '2026-09-27T12:00:00.000Z', { state: 'closed' }),
      ],
      {},
    );
    const counts = summary.categories['state'];
    expect(counts.values).toEqual({ open: 2, closed: 1 });
  });

  it('builds a human-readable summary text without secrets', async () => {
    const aggregator = new GenericAggregator();
    const summary = await aggregator.aggregate(weatherResults, { window: '24h' });
    expect(summary.summaryText).toContain('24 часа');
    expect(summary.summaryText).toContain('успешно 3, ошибок 1');
    expect(summary.summaryText).toContain('Температура');
    expect(summary.summaryText).toContain('среднее');
    expect(summary.summaryText).not.toContain('undefined');
  });

  it('strategy=count only lists measurement counts', async () => {
    const aggregator = new GenericAggregator();
    const summary = await aggregator.aggregate(weatherResults, { window: '24h', strategy: 'count' });
    expect(summary.summaryText).toContain('измерений');
    expect(summary.summaryText).not.toContain('мин');
  });

  it('skips non-numeric/irrelevant leaves (ids, dates)', async () => {
    const aggregator = new GenericAggregator();
    const summary = await aggregator.aggregate(
      [
        exec('1', '2026-09-27T10:00:00.000Z', { note: 'hello', id: 'abc', temp: 20 }),
        exec('2', '2026-09-27T11:00:00.000Z', { note: 'world', id: 'def', temp: 22 }),
      ],
      {},
    );
    expect(summary.numericSeries['temp'].avg).toBe(21);
    expect(summary.numericSeries['id']).toBeUndefined();
    expect(summary.categories['note'].values).toEqual({ hello: 1, world: 1 });
  });
});