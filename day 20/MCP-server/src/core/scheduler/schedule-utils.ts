import { Cron } from 'croner';
import type { TaskSchedule } from './task-types.js';

/** Проверка IANA-таймзоны через Intl (валидные: UTC, Europe/Berlin, ...). */
export function validateTimezone(timezone: string): boolean {
  if (typeof timezone !== 'string' || timezone.trim() === '') return false;
  try {
    new Intl.DateTimeFormat('en-US', { timeZone: timezone });
    return true;
  } catch {
    return false;
  }
}

/** Проверка 5-польного cron-выражения. */
export function validateCron(cron: string): boolean {
  if (typeof cron !== 'string' || cron.trim() === '') return false;
  try {
    new Cron(normalizeCron(cron.trim()));
    return true;
  } catch {
    return false;
  }
}

/**
 * Следующий запуск cron-задачи в заданной таймзоне, строго после afterMs.
 * Возвращает epoch ms или null. Пропущенные срабатывания при этом «перескакиваются»,
 * т.е. если сервер лежал — задача просто получит следующий будущий запуск.
 */
export function nextCronRunMs(cron: string, timezone: string, afterMs: number): number | null {
  try {
    const instance = new Cron(normalizeCron(cron.trim()), { timezone });
    const next = instance.nextRun(new Date(afterMs + 1));
    return next ? next.getTime() : null;
  } catch {
    return null;
  }
}

export function parseDateMs(iso: string): number | null {
  const ms = Date.parse(iso);
  return Number.isFinite(ms) ? ms : null;
}

/** Интерфейс croner принимает 5 следующих полей; нормализуем избыточные пробелы. */
function normalizeCron(cron: string): string {
  return cron.trim().split(/\s+/).join(' ');
}

/** nextRunAt (epoch ms) для расписания. Для once — просто executeAt (может быть в прошлом: catch-up). */
export function computeNextRunAtMs(schedule: TaskSchedule, nowMs: number): number | null {
  if (schedule.type === 'once') {
    const at = parseDateMs(schedule.executeAt ?? '');
    return at;
  }
  return nextCronRunMs(schedule.cron ?? '', schedule.timezone ?? 'UTC', nowMs);
}

/** Человекочитаемое описание cron для UI. */
export function humanizeCron(cron: string): string {
  const expr = normalizeCron(cron);
  const exact: Record<string, string> = {
    '* * * * *': 'Every minute',
    '*/5 * * * *': 'Every 5 minutes',
    '*/10 * * * *': 'Every 10 minutes',
    '*/15 * * * *': 'Every 15 minutes',
    '*/30 * * * *': 'Every 30 minutes',
    '0 * * * *': 'Every hour',
    '0 */2 * * *': 'Every 2 hours',
    '0 */3 * * *': 'Every 3 hours',
    '0 */6 * * *': 'Every 6 hours',
    '0 0 * * *': 'Every day at 00:00',
    '0 9 * * *': 'Every day at 09:00',
    '0 9 * * 1': 'Every Monday at 09:00',
  };
  if (exact[expr]) return exact[expr];

  const parts = expr.split(' ');
  if (parts.length === 5) {
    const [, hour, dom, mon, dow] = parts;
    const minute = parts[0];
    const hm = `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;
    if (dom === '*' && mon === '*' && dow === '*') return `Every day at ${hm}`;
    if (dom === '*' && mon === '*' && /^\d$/.test(dow)) {
      const days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
      return `${days[Number(dow)]} at ${hm}`;
    }
    if (minute === '*') return `Every minute`;
  }
  return expr;
}

/** Краткое описание расписания задачи. */
export function describeSchedule(schedule: TaskSchedule): string {
  if (schedule.type === 'once') {
    return schedule.executeAt ? `Once at ${new Date(schedule.executeAt).toLocaleString()}` : 'Once';
  }
  return humanizeCron(schedule.cron ?? '');
}