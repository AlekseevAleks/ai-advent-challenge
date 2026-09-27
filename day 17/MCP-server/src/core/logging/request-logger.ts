import { appendFileSync, existsSync, mkdirSync, readdirSync, readFileSync, statSync, unlinkSync } from 'node:fs';
import { randomUUID } from 'node:crypto';
import path from 'node:path';
import { LOG_QUERY_LIMIT_MAX } from '../config/schemas.js';
import { redactHeaders, redactText, redactUrl, redactValue, stringifyForLog } from '../util/redact.js';
import type { Logger } from './logger.js';

export type LogDirection = 'mcp' | 'test' | 'health';

export interface LogErrorInfo {
  kind: string;
  code: string;
  message: string;
  retryAfter?: number;
}

export interface RequestLogEntry {
  id: string;
  timestamp: string;
  direction: LogDirection;
  provider: string;
  providerName?: string;
  tool?: string;
  method: string;
  url: string;
  status?: number;
  durationMs?: number;
  success: boolean;
  error?: LogErrorInfo;
  request?: { headers?: Record<string, string>; body?: string; bodyTruncated?: boolean };
  response?: { headers?: Record<string, string>; body?: string; bodyTruncated?: boolean };
  attempts?: number;
}

export type LogEntryInput = Omit<RequestLogEntry, 'id' | 'timestamp' | 'url' | 'request' | 'response'> & {
  url: string;
  /** Тела в сыром виде: будут заредактированы и обрезаны до записи. */
  request?: { headers?: Record<string, string>; bodyRaw?: unknown };
  response?: { headers?: Record<string, string>; bodyRaw?: unknown };
};

export interface LogQuery {
  search?: string;
  provider?: string;
  tool?: string;
  status?: number;
  result?: 'success' | 'error' | 'all';
  from?: string;
  to?: string;
  offset?: number;
  limit?: number;
}

export interface LogQueryResult {
  items: RequestLogEntry[];
  total: number;
  offset: number;
  limit: number;
}

/**
 * Хранение запросов AI → MCP → API в JSONL-файлах по дням:
 *   data/logs/2026-09-27.jsonl
 *
 * Секреты вырезаются ДО записи: Authorization → [REDACTED], секретные query-параметры,
 * ключи в JSON-телах, типичные токены в тексте. Размеры тел ограничиваются
 * maxResponseLogSize.
 */
export class RequestLogger {
  private readonly logsDir: string;
  private readonly logger: Logger | undefined;
  private maxResponseLogSize: number;
  private retentionDays: number;

  constructor(opts: { logsDir: string; maxResponseLogSize?: number; retentionDays?: number; logger?: Logger }) {
    this.logsDir = opts.logsDir;
    this.maxResponseLogSize = opts.maxResponseLogSize ?? 64 * 1024;
    this.retentionDays = opts.retentionDays ?? 7;
    this.logger = opts.logger;
    mkdirSync(this.logsDir, { recursive: true });
  }

  setSettings(opts: { maxResponseLogSize?: number; retentionDays?: number }): void {
    if (opts.maxResponseLogSize !== undefined) this.maxResponseLogSize = opts.maxResponseLogSize;
    if (opts.retentionDays !== undefined) this.retentionDays = opts.retentionDays;
  }

  private fileFor(date: Date): string {
    const y = date.getUTCFullYear();
    const m = String(date.getUTCMonth() + 1).padStart(2, '0');
    const d = String(date.getUTCDate()).padStart(2, '0');
    return path.join(this.logsDir, `${y}-${m}-${d}.jsonl`);
  }

  buildId(): string {
    return `${Date.now().toString(36)}-${randomUUID().slice(0, 8)}`;
  }

  /** Все секреты удаляются здесь — единственное место записи логов запросов. */
  record(input: LogEntryInput): RequestLogEntry {
    const entry: RequestLogEntry = {
      id: this.buildId(),
      timestamp: new Date().toISOString(),
      direction: input.direction,
      provider: input.provider,
      providerName: input.providerName,
      tool: input.tool,
      method: input.method,
      url: redactUrl(input.url),
      status: input.status,
      durationMs: input.durationMs,
      success: input.success,
      attempts: input.attempts,
    };
    if (input.error) {
      entry.error = {
        kind: input.error.kind,
        code: input.error.code,
        message: redactText(input.error.message),
        retryAfter: input.error.retryAfter,
      };
    }
    entry.request = this.sanitizeBodyHeaders(input.request, { headers: requestHeaderAllowlist });
    entry.response = this.sanitizeBodyHeaders(input.response, { headers: responseHeaderAllowlist });

    const line = `${JSON.stringify(entry)}\n`;
    const file = this.fileFor(new Date());
    try {
      appendFileSync(file, line, 'utf8');
    } catch (err) {
      this.logger?.error('[logs] cannot append request log', {
        file,
        error: err instanceof Error ? err.message : String(err),
      });
    }
    return entry;
  }

  private sanitizeBodyHeaders(
    part:
      | { headers?: Record<string, string>; body?: string; bodyTruncated?: boolean; bodyRaw?: unknown }
      | undefined,
    opts?: { headers?: Set<string> },
  ): { headers?: Record<string, string>; body?: string; bodyTruncated?: boolean } | undefined {
    if (!part) return undefined;
    const out: { headers?: Record<string, string>; body?: string; bodyTruncated?: boolean } = {};
    if (part.headers) {
      const filtered: Record<string, string> = {};
      for (const [key, value] of Object.entries(part.headers)) {
        const lower = key.toLowerCase();
        if (opts?.headers && !opts.headers.has(lower)) continue;
        filtered[key] = lower.startsWith('authorization') ? '[REDACTED]' : value;
      }
      out.headers = redactHeaders(filtered);
    }
    if (part.bodyRaw !== undefined) {
      let redacted: unknown;
      if (typeof part.bodyRaw === 'string') {
        let parsed: unknown = null;
        try {
          parsed = JSON.parse(part.bodyRaw);
        } catch {
          /* не JSON — оставляем как текст с redactText ниже */
        }
        redacted = parsed !== null ? redactValue(parsed) : redactText(part.bodyRaw);
      } else {
        redacted = redactValue(part.bodyRaw);
      }
      const { text, truncated } = stringifyForLog(redacted, this.maxResponseLogSize);
      out.body = text;
      out.bodyTruncated = truncated;
    } else if (part.body !== undefined) {
      const redacted = redactText(part.body);
      out.body = redacted.length > this.maxResponseLogSize ? redacted.slice(0, this.maxResponseLogSize) + '\n[Response truncated]' : redacted;
      out.bodyTruncated = redacted.length > this.maxResponseLogSize;
    }
    return Object.keys(out).length ? out : undefined;
  }

  async list(query: LogQuery = {}): Promise<LogQueryResult> {
    const limit = Math.min(Math.max(1, query.limit ?? 50), LOG_QUERY_LIMIT_MAX);
    const offset = Math.max(0, query.offset ?? 0);
    const files = this.listFiles();
    const entries: RequestLogEntry[] = [];
    for (const file of files) {
      for (const raw of readLines(file)) {
        const parsed = parseLine(raw);
        if (parsed) entries.push(parsed);
      }
    }
    entries.sort((a, b) => (a.timestamp < b.timestamp ? 1 : a.timestamp > b.timestamp ? -1 : 0));
    const filtered = entries.filter((e) => this.matches(e, query));
    const total = filtered.length;
    const items = filtered.slice(offset, offset + limit);
    return { items, total, offset, limit };
  }

  async get(id: string): Promise<RequestLogEntry | null> {
    for (const file of this.listFiles().reverse()) {
      for (const raw of readLines(file)) {
        const parsed = parseLine(raw);
        if (parsed?.id === id) return parsed;
      }
    }
    return null;
  }

  async clear(): Promise<number> {
    let count = 0;
    for (const file of this.listFiles()) {
      unlinkSync(file);
      count++;
    }
    return count;
  }

  async stats(date?: Date): Promise<{ today: number; errorsToday: number; avgLatencyMs: number; last: RequestLogEntry[] }> {
    const todayFile = this.fileFor(date ?? new Date());
    let today = 0;
    let errorsToday = 0;
    let latencySum = 0;
    let latencyCount = 0;
    const last: RequestLogEntry[] = [];
    const files = this.listFiles().reverse();
    for (const file of files) {
      for (const raw of readLines(file)) {
        const parsed = parseLine(raw);
        if (!parsed) continue;
        if (file === todayFile) {
          today++;
          if (!parsed.success) errorsToday++;
          if (typeof parsed.durationMs === 'number') {
            latencySum += parsed.durationMs;
            latencyCount++;
          }
        }
        if (last.length < 10) last.push(parsed);
      }
    }
    last.sort((a, b) => (a.timestamp < b.timestamp ? 1 : -1));
    return {
      today,
      errorsToday,
      avgLatencyMs: latencyCount ? Math.round(latencySum / latencyCount) : 0,
      last: last.slice(0, 10),
    };
  }

  /** Удалить файлы логов старше retentionDays. */
  prune(): number {
    if (this.retentionDays <= 0) return 0;
    const cutoff = Date.now() - this.retentionDays * 24 * 60 * 60 * 1000;
    let removed = 0;
    for (const file of [...this.listFiles(), ...this.listLogFiles()]) {
      try {
        if (statSync(file).mtimeMs < cutoff) {
          unlinkSync(file);
          removed++;
        }
      } catch {
        /* ignore */
      }
    }
    return removed;
  }

  private listFiles(): string[] {
    try {
      return readdirSync(this.logsDir)
        .filter((f) => f.endsWith('.jsonl'))
        .map((f) => path.join(this.logsDir, f))
        .sort();
    } catch {
      return [];
    }
  }

  private listLogFiles(): string[] {
    try {
      return readdirSync(path.dirname(this.logsDir))
        .filter((f) => f.endsWith('.log'))
        .map((f) => path.join(path.dirname(this.logsDir), f))
        .sort();
    } catch {
      return [];
    }
  }

  private matches(entry: RequestLogEntry, query: LogQuery): boolean {
    if (query.provider && entry.provider !== query.provider) return false;
    if (query.tool && entry.tool !== query.tool) return false;
    if (query.status !== undefined && entry.status !== query.status) return false;
    if (query.result === 'success' && !entry.success) return false;
    if (query.result === 'error' && entry.success) return false;
    if (query.from && entry.timestamp < query.from) return false;
    if (query.to && entry.timestamp > query.to) return false;
    if (query.search) {
      const needle = query.search.toLowerCase();
      const haystack = [
        entry.tool,
        entry.provider,
        entry.providerName,
        entry.url,
        entry.error?.message,
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();
      if (!haystack.includes(needle)) return false;
    }
    return true;
  }
}

/** Отбираем только заголовки запроса, которые безопасно хранить (credentials исключены). */
const requestHeaderAllowlist = new Set([
  'accept',
  'content-type',
  'user-agent',
  'authorization',
  'x-github-api-version',
  'x-request-id',
  'mcp-session-id',
]);

/** Отбираем только заголовки, которые безопасно хранить (все credentials исключены). */
const responseHeaderAllowlist = new Set([
  'content-type',
  'content-length',
  'date',
  'etag',
  'last-modified',
  'link',
  'retry-after',
  'x-ratelimit-limit',
  'x-ratelimit-remaining',
  'x-ratelimit-reset',
  'x-ratelimit-used',
  'x-ratelimit-resource',
]);

function readLines(file: string): string[] {
  try {
    if (!existsSync(file)) return [];
    return readFileSync(file, 'utf8').split('\n').filter(Boolean);
  } catch {
    return [];
  }
}

function parseLine(raw: string): RequestLogEntry | null {
  try {
    const parsed = JSON.parse(raw) as RequestLogEntry;
    if (parsed && typeof parsed.id === 'string' && typeof parsed.timestamp === 'string') return parsed;
    return null;
  } catch {
    return null;
  }
}