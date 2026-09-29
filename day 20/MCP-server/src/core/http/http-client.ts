import type { Logger } from '../logging/logger.js';
import type { RequestLogger } from '../logging/request-logger.js';
import { AppError, authError, externalApiError, rateLimitError, timeoutError, userError } from '../errors.js';
import { redactText, redactUrl, safeStringify } from '../util/redact.js';

export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

/** Контекст для логов запросов: какой провайдер/tool инициировал вызов. */
export interface HttpLogContext {
  provider: string;
  providerName?: string;
  tool?: string;
  direction: 'mcp' | 'test' | 'health';
}

export interface HttpRequestOptions {
  method: HttpMethod;
  url: string;
  query?: Record<string, string | number | boolean | undefined | null>;
  headers?: Record<string, string>;
  body?: unknown;
  timeoutMs?: number;
  retries?: number;
  retryBackoffMs?: number;
  log?: HttpLogContext;
  responseType?: 'json' | 'text';
  /**
   * Извлечение понятного сообщения об ошибке из тела ответа внешнего API.
   * Вернуть null, чтобы использовать дефолтное сообщение.
   */
  errorMessageExtractor?: (status: number, body: unknown) => string | null;
}

export interface HttpResult<T = unknown> {
  status: number;
  headers: Record<string, string>;
  data: T;
  url: string;
}

interface FetchOutcome {
  ok: boolean;
  error?: string;
}

/**
 * Единый HTTP-слой для всех провайдеров. Провайдеры не вызывают fetch() напрямую:
 * таймаут, ретраи с exponential backoff, обработка ошибок (404/429/401/5xx),
 * rate-limit с Retry-After и логгирование (с редaкцией секретов) живут здесь.
 */
export class HttpClient {
  private readonly fetchImpl: typeof fetch;
  private readonly requestLogger?: RequestLogger;
  private readonly logger?: Logger;
  private readonly defaultTimeoutMs: number;
  private readonly defaultRetries: number;
  private readonly defaultRetryBackoffMs: number;

  constructor(opts: {
    fetchImpl?: typeof fetch;
    requestLogger?: RequestLogger;
    logger?: Logger;
    defaultTimeoutMs?: number;
    defaultRetries?: number;
    defaultRetryBackoffMs?: number;
  } = {}) {
    this.fetchImpl = opts.fetchImpl ?? globalThis.fetch.bind(globalThis);
    this.requestLogger = opts.requestLogger;
    this.logger = opts.logger;
    this.defaultTimeoutMs = opts.defaultTimeoutMs ?? 15_000;
    this.defaultRetries = opts.defaultRetries ?? 2;
    this.defaultRetryBackoffMs = opts.defaultRetryBackoffMs ?? 250;
  }

  async get<T = unknown>(url: string, opts?: Partial<HttpRequestOptions>): Promise<HttpResult<T>> {
    return this.request<T>({ method: 'GET', url, ...opts });
  }

  async post<T = unknown>(url: string, opts?: Partial<HttpRequestOptions>): Promise<HttpResult<T>> {
    return this.request<T>({ method: 'POST', url, ...opts });
  }

  async put<T = unknown>(url: string, opts?: Partial<HttpRequestOptions>): Promise<HttpResult<T>> {
    return this.request<T>({ method: 'PUT', url, ...opts });
  }

  async patch<T = unknown>(url: string, opts?: Partial<HttpRequestOptions>): Promise<HttpResult<T>> {
    return this.request<T>({ method: 'PATCH', url, ...opts });
  }

  async delete<T = unknown>(url: string, opts?: Partial<HttpRequestOptions>): Promise<HttpResult<T>> {
    return this.request<T>({ method: 'DELETE', url, ...opts });
  }

  async request<T = unknown>(opts: HttpRequestOptions): Promise<HttpResult<T>> {
    const url = opts.url;
    if (!/^https?:\/\//i.test(url)) {
      throw userError(`Unsupported URL protocol in ${redactUrl(url)}`, 'INVALID_URL');
    }

    const fullUrl = this.buildUrl(url, opts.query);
    const timeoutMs = opts.timeoutMs ?? this.defaultTimeoutMs;
    const retries = Math.max(0, opts.retries ?? this.defaultRetries);
    const retryBackoffMs = opts.retryBackoffMs ?? this.defaultRetryBackoffMs;
    const startedAt = Date.now();
    let attempts = 0;

    for (let attempt = 0; ; attempt++) {
      attempts = attempt + 1;
      try {
        const outcome = await this.performOnce<T>({ ...opts, url: fullUrl, timeoutMs });
        if (outcome.ok) {
          this.finishLog(opts, fullUrl, {
            status: outcome.result!.status,
            durationMs: Date.now() - startedAt,
            success: true,
            requestBody: opts.body,
            responseHead: outcome.head,
            responseBody: outcome.body,
            attempts,
          });
          return outcome.result!;
        }
        throw outcome.error;
      } catch (err) {
        const appErr = this.normalizeError(err, opts, fullUrl, timeoutMs);
        if (this.shouldRetry(appErr, attempt, retries)) {
          const delay = Math.min(retryBackoffMs * 2 ** attempt, 10_000);
          this.logger?.warn(`[http] ${opts.method} ${redactUrl(fullUrl)} failed (${appErr.message}); retry ${attempt + 1}/${retries} in ${delay}ms`);
          await sleep(delay);
          continue;
        }
        this.finishLog(opts, fullUrl, {
          status: appErr.status,
          durationMs: Date.now() - startedAt,
          success: false,
          error: {
            kind: appErr.kind,
            code: appErr.code,
            message: appErr.message,
            retryAfter: appErr.retryAfter,
          },
          requestBody: opts.body,
          attempts,
        });
        throw appErr;
      }
    }
  }

  private async performOnce<T>(opts: HttpRequestOptions & { url: string; timeoutMs: number }): Promise<
    | { ok: true; result: HttpResult<T>; head: Record<string, string>; body: string }
    | { ok: false; error: unknown }
  > {
    const headers: Record<string, string> = { accept: 'application/json', ...opts.headers };
    if (opts.body !== undefined) headers['content-type'] = 'application/json';
    const body =
      opts.body === undefined ? undefined : typeof opts.body === 'string' ? opts.body : JSON.stringify(opts.body);

    let res: Response;
    try {
      res = await this.fetchImpl(opts.url, {
        method: opts.method,
        headers,
        body,
        signal: AbortSignal.timeout(opts.timeoutMs),
        redirect: 'follow',
      });
    } catch (err) {
      return { ok: false, error: err };
    }

    const text = await res.text().catch(() => '');
    const headersRecord = Object.fromEntries(res.headers.entries());
    const parsed = opts.responseType === 'text' ? text : safeParseJson(text);

    if (res.status === 429) {
      const retryAfter = parseRetryAfter(headersRecord);
      return {
        ok: false,
        error: rateLimitError(
          `Rate limit exceeded (HTTP 429).${retryAfter ? ` Retry after ${retryAfter}s.` : ''}`,
          retryAfter,
        ),
      };
    }
    if (res.status === 403 && headersRecord['x-ratelimit-remaining'] === '0') {
      return { ok: false, error: rateLimitError('Rate limit exceeded (HTTP 403, X-RateLimit-Remaining: 0)') };
    }
    if (!res.ok) {
      const message = this.extractErrorMessage(opts, res.status, parsed, text);
      if (res.status === 401 || res.status === 403) {
        return { ok: false, error: authError(message, 'API_AUTH_ERROR', res.status) };
      }
      return { ok: false, error: externalApiError(message, res.status) };
    }

    return {
      ok: true,
      result: { status: res.status, headers: headersRecord, data: parsed as T, url: opts.url },
      head: headersRecord,
      body: text,
    };
  }

  private extractErrorMessage(opts: HttpRequestOptions, status: number, parsed: unknown, text: string): string {
    const extracted = opts.errorMessageExtractor?.(status, parsed);
    if (extracted) return extracted;
    if (parsed && typeof parsed === 'object') {
      const message = (parsed as Record<string, unknown>).message;
      if (typeof message === 'string') return message;
    }
    const providerName = opts.log?.providerName ?? opts.log?.provider ?? 'API';
    const snippet = text.slice(0, 200).trim();
    return snippet
      ? `${providerName} returned HTTP ${status}: ${snippet}`
      : `${providerName} returned HTTP ${status}`;
  }

  private normalizeError(err: unknown, opts: HttpRequestOptions, fullUrl: string, timeoutMs: number) {
    // Уже типизированные ошибки (rate_limit, auth, external с status) передаются как есть
    if (err instanceof AppError) return err;
    if (err instanceof Error) {
      if (err.name === 'TimeoutError' || err.name === 'AbortError') {
        return timeoutError(`Request timed out after ${timeoutMs}ms (${opts.method} ${redactUrl(fullUrl)})`, 'TIMEOUT', err);
      }
      let message = `Network error calling ${redactUrl(fullUrl)}: ${err.message}`;
      if (/fetch failed/i.test(err.message)) {
        message = `Network error calling ${redactUrl(fullUrl)}: ${err.cause instanceof Error ? err.cause.message : 'connection failed'}`;
      }
      return externalApiError(message, undefined, undefined, 'NETWORK_ERROR');
    }
    return externalApiError('Unknown network error', undefined, undefined, 'NETWORK_ERROR');
  }

  private shouldRetry(err: Awaited<ReturnType<typeof this.normalizeError>>, attempt: number, retries: number): boolean {
    if (attempt >= retries) return false;
    if (err.kind === 'timeout') return true;
    if (err.kind === 'external') {
      // Ретраим сетевые ошибки и 5xx; 4xx и rate limit не ретраим автоматически.
      if (err.status === undefined) return true;
      if (err.status >= 500) return true;
    }
    return false;
  }

  private finishLog(
    opts: HttpRequestOptions,
    fullUrl: string,
    info: {
      status?: number;
      durationMs: number;
      success: boolean;
      error?: { kind: string; code: string; message: string; retryAfter?: number };
      requestBody?: unknown;
      responseHead?: Record<string, string>;
      responseBody?: string;
      attempts: number;
    },
  ): void {
    const ctx = opts.log;
    if (ctx) {
      const statusText = info.success ? String(info.status) : `${info.status ?? '-'} (${info.error?.kind ?? 'error'})`;
      this.logger?.debug(
        `[http] ${opts.method} ${redactUrl(fullUrl)} -> ${statusText} in ${info.durationMs}ms (attempts: ${info.attempts})`,
      );
    }
    this.requestLogger?.record({
      direction: ctx?.direction ?? 'mcp',
      provider: ctx?.provider ?? 'unknown',
      providerName: ctx?.providerName,
      tool: ctx?.tool,
      method: opts.method,
      url: fullUrl,
      status: info.status,
      durationMs: info.durationMs,
      success: info.success,
      error: info.error,
      request: opts.headers || info.requestBody !== undefined ? { headers: opts.headers, bodyRaw: info.requestBody } : undefined,
      response:
        info.responseBody !== undefined || info.responseHead
          ? { headers: info.responseHead, bodyRaw: info.responseBody }
          : undefined,
      attempts: info.attempts,
    });
  }

  private buildUrl(base: string, query?: HttpRequestOptions['query']): string {
    if (!query) return base;
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined || value === null) continue;
      params.set(key, String(value));
    }
    const qs = params.toString();
    if (!qs) return base;
    return base + (base.includes('?') ? '&' : '?') + qs;
  }
}

function safeParseJson(text: string): unknown {
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function parseRetryAfter(headers: Record<string, string>): number | undefined {
  const raw = headers['retry-after'];
  if (!raw) return undefined;
  const secs = Number(raw);
  if (Number.isFinite(secs) && secs >= 0) return Math.ceil(secs);
  const date = Date.parse(raw);
  if (Number.isFinite(date)) return Math.max(0, Math.ceil((date - Date.now()) / 1000));
  return undefined;
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export { redactText, safeStringify };