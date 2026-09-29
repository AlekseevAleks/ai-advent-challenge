/**
 * Редaкция секретов: credentials никогда не должны попадать в логи,
 * в REST-ответы (кроме маски) или в MCP-ответы.
 */

/** Заголовки, содержимое которых всегда заменяется на [REDACTED]. */
const SECRET_HEADERS = new Set([
  'authorization',
  'proxy-authorization',
  'cookie',
  'set-cookie',
  'x-api-key',
  'api-key',
  'apikey',
  'x-auth-token',
  'x-access-token',
  'x-csrf-token',
  'x-amz-security-token',
  'x-gismeteo-token',
]);

/** Параметры query-строки, считающиеся секретами. */
const SECRET_QUERY_KEYS = new Set([
  'token',
  'access_token',
  'refresh_token',
  'api_key',
  'apikey',
  'key',
  'auth',
  'authorization',
  'password',
  'passwd',
  'secret',
  'client_secret',
  'signature',
  'sig',
  'credential',
  'credentials',
  'code',
]);

/** Имена ключей в JSON-телах (на любом уровне вложенности), считающиеся секретами. */
const SECRET_BODY_KEY_RE = /(token|secret|password|passwd|api[_-]?key|apikey|auth|credential|cookie|session|private[_-]?key|bearer)/i;

export function isSecretHeader(name: string): boolean {
  return SECRET_HEADERS.has(name.toLowerCase());
}

export function isSecretQueryKey(key: string): boolean {
  return SECRET_QUERY_KEYS.has(key.toLowerCase());
}

export function isSecretBodyKey(key: string): boolean {
  return SECRET_BODY_KEY_RE.test(key);
}

/** Замаскировать значения секретных заголовков. Несуществующие ключи не создаются. */
export function redactHeaders(headers: Record<string, string> | undefined): Record<string, string> | undefined {
  if (!headers) return undefined;
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(headers)) {
    out[key] = isSecretHeader(key) ? '[REDACTED]' : value;
  }
  return out;
}

/** Замаскировать секретные параметры в query-строке. */
export function redactQueryString(query: string): string {
  if (!query) return query;
  return query
    .split('&')
    .map((pair) => {
      const eq = pair.indexOf('=');
      if (eq === -1) return pair;
      const key = pair.slice(0, eq);
      if (isSecretQueryKey(key)) return `${key}=[REDACTED]`;
      return pair;
    })
    .join('&');
}

/** Вернуть URL с замаскированными секретными query-параметрами. */
export function redactUrl(url: string): string {
  const hashIdx = url.indexOf('#');
  const qIdx = url.indexOf('?');
  if (qIdx === -1) return url;
  const end = hashIdx === -1 ? undefined : hashIdx;
  const query = url.slice(qIdx + 1, end);
  return url.slice(0, qIdx + 1) + redactQueryString(query) + (end === undefined ? '' : url.slice(end));
}

/** Рекурсивно замаскировать секретные ключи в любом JSON-значении. */
export function redactValue(value: unknown, depth = 0): unknown {
  if (depth > 8) return value;
  if (Array.isArray(value)) {
    return value.map((item) => redactValue(item, depth + 1));
  }
  if (value !== null && typeof value === 'object') {
    const out: Record<string, unknown> = {};
    for (const [key, val] of Object.entries(value as Record<string, unknown>)) {
      out[key] = isSecretBodyKey(key) ? '[REDACTED]' : redactValue(val, depth + 1);
    }
    return out;
  }
  return value;
}

/** Поиск типичных токенов в произвольном тексте (сообщения ошибок, URL). */
export function redactText(text: string): string {
  return text
    .replace(/(gh[pousr]_|github_pat_)[A-Za-z0-9_]{8,}/g, '$1[REDACTED]')
    .replace(/xox[baprs]-[A-Za-z0-9-]{8,}/g, 'xox[REDACTED]')
    .replace(/\bsk-[A-Za-z0-9_-]{8,}/g, 'sk-[REDACTED]')
    .replace(/\bAKIA[0-9A-Z]{16}\b/g, 'AKIA[REDACTED]')
    .replace(/Bearer\s+[A-Za-z0-9._~+/=-]{8,}/gi, 'Bearer [REDACTED]');
}

/** Безопасная сериализация любого значения в JSON-строку (без циклических ссылок). */
export function safeStringify(value: unknown): string {
  const seen = new WeakSet<object>();
  try {
    return JSON.stringify(value, (_key, val) => {
      if (val !== null && typeof val === 'object') {
        if (seen.has(val)) return '[Circular]';
        seen.add(val);
      }
      return val;
    });
  } catch {
    return String(value);
  }
}

/**
 * Сериализовать значение для хранения в логе с ограничением размера.
 * Возвращает текст и флаг обрезки.
 */
export function stringifyForLog(value: unknown, maxBytes: number): { text: string; truncated: boolean } {
  const raw = typeof value === 'string' ? value : safeStringify(value);
  if (raw.length <= maxBytes) return { text: raw, truncated: false };
  const cut = raw.slice(0, Math.max(0, maxBytes));
  return { text: `${cut}\n[Response truncated]`, truncated: true };
}

/** Замаскировать секрет: ghp_************************abcd */
export function maskSecret(value: string): string {
  if (!value) return '';
  if (value.length <= 8) return '********';
  const head = value.slice(0, 4);
  const tail = value.slice(-4);
  const stars = '*'.repeat(Math.min(24, value.length - 8));
  return `${head}${stars}${tail}`;
}