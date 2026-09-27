// Небольшие форматтеры чисел/дат для всего интерфейса (Intl).

const timeFormatter = new Intl.DateTimeFormat('en-GB', {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
});

const dateTimeFormatter = new Intl.DateTimeFormat('en-GB', {
  year: 'numeric',
  month: 'short',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
});

const relativeFormatter = new Intl.RelativeTimeFormat('en', { numeric: 'auto' });

const numberFormatter = new Intl.NumberFormat('en-US');

/** 123 → 123; 3600 → 1h 0m; 3725 → 1h 2m; 90000 → 1d 1h. */
export function formatDuration(totalSeconds: number): string {
  const s = Math.floor(Math.max(0, totalSeconds));
  if (s < 60) return `${s}s`;
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m ${s % 60}s`;
}

/** ISO → "21:30:05". */
export function formatTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : timeFormatter.format(d);
}

/** ISO → "Sep 27, 2026, 21:30:05" (en-GB). */
export function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : dateTimeFormatter.format(d);
}

/** ISO → "5 min ago", "in 2 hours". */
export function formatRelative(iso: string): string {
  const time = new Date(iso).getTime();
  if (Number.isNaN(time)) return '';
  const diffMs = time - Date.now();
  const abs = Math.abs(diffMs);
  if (abs < 60_000) return relativeFormatter.format(Math.round(diffMs / 1000), 'second');
  if (abs < 3_600_000) return relativeFormatter.format(Math.round(diffMs / 60_000), 'minute');
  if (abs < 86_400_000) return relativeFormatter.format(Math.round(diffMs / 3_600_000), 'hour');
  return relativeFormatter.format(Math.round(diffMs / 86_400_000), 'day');
}

export function formatNumber(n: number): string {
  return numberFormatter.format(n);
}

/** 2048 → "2.0 KB". */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Полный URL → только pathname[?query] для компактной таблицы. */
export function pathOnly(url: string): string {
  try {
    const u = new URL(url);
    return `${u.pathname}${u.search}`;
  } catch {
    return url;
  }
}

/** Заголовки ответа/запроса → текст для <pre> (Authorization уже [REDACTED] на бэке). */
export function formatHeaders(headers: Record<string, string>): string {
  return Object.entries(headers)
    .map(([key, value]) => `${key}: ${value}`)
    .join('\n');
}

/** ISO → "2026-09-27T21:30" для input[type=datetime-local]. */
export function toDatetimeLocal(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}