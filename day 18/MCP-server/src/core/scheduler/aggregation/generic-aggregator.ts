import { redactText } from '../../util/redact.js';
import type { AggregationOptions, CategoryCounts, NumericStats, TaskExecution, TaskSummary } from '../task-types.js';
import { resolveAggregationWindow, type Aggregator, type AggregationWindow } from './aggregator.js';

const MAX_DEPTH = 4;
const MAX_ARRAY_ITEMS = 100;
const MAX_CATEGORY_VALUES = 20;

/** Человекочитаемые подписи листовых путей для сводок. */
const PATH_LABELS: Record<string, string> = {
  'weather.temperatureC': 'Температура',
  'temperatureC': 'Температура',
  'weather.apparentTemperatureC': 'Ощущается как',
  'apparentTemperatureC': 'Ощущается как',
  'weather.relativeHumidityPct': 'Влажность',
  'humidityPct': 'Влажность',
  'relativeHumidityPct': 'Влажность',
  'weather.windSpeedKmh': 'Ветер',
  'windSpeedKmh': 'Ветер',
  'weather.windSpeedMs': 'Ветер (м/с)',
  'weather.precipitationMm': 'Осадки',
  'precipitationMm': 'Осадки',
  'weather.pressureMmHg': 'Давление',
  'pressureMmHg': 'Давление',
  'count': 'Количество результатов',
  'forecast[].temperatureMaxC': 'Макс. температура',
  'forecast[].temperatureMinC': 'Мин. температура',
  'forecast[].precipitationSumMm': 'Осадки',
  'items[].stars': 'Звёзды',
};

function labelForPath(path: string): string {
  return PATH_LABELS[path] ?? path;
}

/**
 * GenericAggregator: собирает числовые листья и категориальные значения
 * из произвольных JSON-результатов и считает count/min/max/avg/sum/latest.
 * Не требует provider-specific кода — любой tool MCP агрегируется автоматически.
 */
export class GenericAggregator implements Aggregator {
  aggregate(executions: TaskExecution[], options: AggregationOptions): Promise<TaskSummary> {
    const window = resolveAggregationWindow(options);
    const samples = executions; // окно уже применено на уровне хранилища
    const numeric = new Map<string, number[]>();
    const categories = new Map<string, Map<string, number>>();

    for (const exec of samples) {
      if (exec.status === 'error' || exec.result === undefined || exec.result === null) continue;
      try {
        this.collect(exec.result, '', numeric, categories, 0);
      } catch {
        /* результат не стриктифицируется без проблем — пропускаем */
      }
    }

    const numericSeries: Record<string, NumericStats> = {};
    for (const [path, values] of numeric) {
      numericSeries[path] = this.stats(path, values);
    }

    const categoryResult: Record<string, CategoryCounts> = {};
    for (const [path, counts] of categories) {
      const entries = [...counts.entries()].sort((a, b) => b[1] - a[1]);
      categoryResult[path] = { total: samples.filter((e) => e.status === 'success').length, values: Object.fromEntries(entries) };
    }

    const success = samples.filter((e) => e.status === 'success').length;
    const errors = samples.filter((e) => e.status === 'error').length;

    const summary: TaskSummary = {
      taskId: samples[0]?.taskId ?? '',
      window,
      executions: { total: samples.length, success, error: errors },
      numericSeries,
      categories: categoryResult,
      summaryText: '',
    };
    summary.summaryText = this.buildText(summary, options);
    return Promise.resolve(summary);
  }

  private collect(
    value: unknown,
    path: string,
    numeric: Map<string, number[]>,
    categories: Map<string, Map<string, number>>,
    depth: number,
  ): void {
    if (depth > MAX_DEPTH) return;
    if (typeof value === 'number' && Number.isFinite(value)) {
      const list = numeric.get(path) ?? [];
      list.push(value);
      numeric.set(path, list);
      return;
    }
    if (typeof value === 'string' || typeof value === 'boolean') {
      // Категории с секретоподобными путями не собираем (не создаём шума и не рискуем утечкой)
      if (this.isSecretPath(path)) return;
      const key = String(value);
      const map = categories.get(path) ?? new Map<string, number>();
      if (map.size < MAX_CATEGORY_VALUES || map.has(key)) {
        map.set(key, (map.get(key) ?? 0) + 1);
        categories.set(path, map);
      }
      return;
    }
    if (Array.isArray(value)) {
      const lenPath = `${path}${path ? '.' : ''}length`;
      const lengthList = numeric.get(lenPath) ?? [];
      lengthList.push(value.length);
      numeric.set(lenPath, lengthList);
      if (value.length <= MAX_ARRAY_ITEMS) {
        for (const item of value) {
          this.collect(item, `${path}[]`, numeric, categories, depth + 1);
        }
      }
      return;
    }
    if (value !== null && typeof value === 'object') {
      for (const [key, child] of Object.entries(value as Record<string, unknown>)) {
        this.collect(child, path ? `${path}.${key}` : key, numeric, categories, depth + 1);
      }
    }
  }

  private isSecretPath(path: string): boolean {
    return /(token|secret|password|passwd|api[_-]?key|apikey|auth|credential|cookie|session|private[_-]?key|bearer)/i.test(path);
  }

  private stats(path: string, values: number[]): NumericStats {
    const min = Math.min(...values);
    const max = Math.max(...values);
    const sum = values.reduce((a, b) => a + b, 0);
    return {
      count: values.length,
      min: toPrecision(min),
      max: toPrecision(max),
      avg: toPrecision(sum / values.length),
      sum: toPrecision(sum),
      latest: values[values.length - 1],
      first: values[0],
    };
  }

  private buildText(summary: TaskSummary, options: AggregationOptions): string {
    const w = summary.window;
    const head =
      w.label === 'all'
        ? `Всего выполнено ${summary.executions.total} раз (успешно ${summary.executions.success}, ошибок ${summary.executions.error}).`
        : `За последние ${windowLabel(w)} выполнено ${summary.executions.total} раз (успешно ${summary.executions.success}, ошибок ${summary.executions.error}).`;

    const lines: string[] = [];
    const paths = Object.keys(summary.numericSeries).sort();
    for (const p of paths) {
      const s = summary.numericSeries[p];
      const label = labelForPath(p);
      if (options.strategy === 'count') {
        lines.push(`${label}: ${s.count} измерений`);
        continue;
      }
      lines.push(
        `${label}: среднее ${fmt(s.avg)}, мин ${fmt(s.min)}, макс ${fmt(s.max)}${s.latest !== undefined ? `, последнее ${fmt(s.latest)}` : ''} (из ${s.count})`,
      );
    }
    for (const [p, counts] of Object.entries(summary.categories)) {
      const top = Object.entries(counts.values)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 3)
        .map(([v, n]) => `${v} ×${n}`)
        .join(', ');
      lines.push(`${labelForPath(p)}: ${top}`);
    }
    return redactText([head, ...lines].join('\n'));
  }
}

function windowLabel(w: AggregationWindow): string {
  switch (w.label) {
    case '1h':
      return 'час';
    case '24h':
      return '24 часа';
    case '7d':
      return '7 дней';
    case '30d':
      return '30 дней';
    default:
      return 'выбранный период';
  }
}

function fmt(value: number | undefined): string {
  if (value === undefined) return '—';
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

function toPrecision(value: number): number {
  return Math.round(value * 100) / 100;
}