import type { AggregationOptions, NumericStats, TaskExecution, TaskSummary } from '../task-types.js';

export { AggregationOptions, NumericStats, TaskExecution, TaskSummary };

/**
 * Агрегатор результатов выполнения задач.
 * В v1 — GenericAggregator (числовые ряды по leaf-путям + категории).
 * Архитектура позволяет добавить provider-specific агрегаторы и в будущем
 * LLM-усиление: Structured summary → LLM → Human readable summary.
 */
export interface Aggregator {
  aggregate(executions: TaskExecution[], options: AggregationOptions): Promise<TaskSummary>;
}

/** Окно агрегации: from/to (epoch ms), либо вычисленные из шаблона. */
export interface AggregationWindow {
  label: string;
  from?: string;
  to?: string;
}

const WINDOW_MS: Record<string, number> = {
  '1h': 3600_000,
  '24h': 24 * 3600_000,
  '7d': 7 * 24 * 3600_000,
  '30d': 30 * 24 * 3600_000,
};

/** Превратить options в окно выборки. */
export function resolveAggregationWindow(options: AggregationOptions, now: number = Date.now()): AggregationWindow {
  const to = options.to ? new Date(options.to) : new Date(now);
  if (options.from) {
    return { label: 'custom', from: new Date(options.from).toISOString(), to: to.toISOString() };
  }
  if (options.window && WINDOW_MS[options.window] !== undefined) {
    const fromMs = now - WINDOW_MS[options.window];
    return { label: options.window, from: new Date(fromMs).toISOString(), to: to.toISOString() };
  }
  return { label: 'all' };
}