import { describe, expect, it, afterEach, beforeEach } from 'vitest';
import { mkdtempSync, rmSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { HttpClient } from '../src/core/http/http-client.js';
import { RequestLogger } from '../src/core/logging/request-logger.js';
import { Logger } from '../src/core/logging/logger.js';
import { readLogLines } from './helpers.js';

let tmp: string;
let logsDir: string;
let requestLogger: RequestLogger;

beforeEach(() => {
  tmp = mkdtempSync(path.join(os.tmpdir(), 'mcp-gw-log-'));
  logsDir = path.join(tmp, 'logs');
  requestLogger = new RequestLogger({ logsDir, maxResponseLogSize: 1024 });
});

afterEach(() => rmSync(tmp, { recursive: true, force: true }));

const SECRET_TOKEN = 'ghp_AAAAAAAAAAAAAAAA1111';
const SECRET_QUERY = 'supersecretqueryparam';

describe('Logging & redaction', () => {
  it('never writes Authorization header, query tokens, or API keys into log files', async () => {
    const client = new HttpClient({
      fetchImpl: async (_url, init) =>
        new Response(JSON.stringify({ ok: true, apiKey: 'bodysecret999', data: 'hello' }), {
          status: 200,
          headers: { 'content-type': 'application/json', 'set-cookie': 'session=abc123' },
        }),
      requestLogger,
      logger: new Logger({ level: 'silent' }),
    });

    await client.get('https://api.example.com/v1/data', {
      query: { token: SECRET_QUERY, page: 2 },
      headers: { authorization: `Bearer ${SECRET_TOKEN}`, accept: 'application/json' },
      body: { prompt: 'hello', apiKey: 'bodysecret999' },
      log: { provider: 'test', tool: 'test_tool', direction: 'mcp' },
      timeoutMs: 5000,
    });

    const lines = readLogLines(tmp);
    expect(lines.length).toBeGreaterThan(0);
    const all = lines.join('\n');

    // секреты отсутствуют в любом виде
    expect(all).not.toContain(SECRET_TOKEN);
    expect(all).not.toContain(SECRET_QUERY);
    expect(all).not.toContain('bodysecret999');
    expect(all).not.toContain('abc123');
    // но помечены как заредактированные
    expect(all).toContain('[REDACTED]');
    expect(all).toContain('token=[REDACTED]');
    expect(all).toContain('"authorization":"[REDACTED]"');
    // URL и результат на месте
    expect(all).toContain('https://api.example.com/v1/data');
    expect(all).toContain('"status":200');

    const entry = JSON.parse(lines[0]);
    expect(entry.request.body).toContain('"apiKey":"[REDACTED]"');
    expect(entry.success).toBe(true);
    expect(entry.provider).toBe('test');
    expect(entry.tool).toBe('test_tool');
  });

  it('does not log response cookies or secrets in response headers', async () => {
    const client = new HttpClient({
      fetchImpl: async () =>
        new Response(JSON.stringify({ data: 1 }), {
          status: 200,
          headers: { 'content-type': 'application/json', 'set-cookie': 'secretCookie=xyz', 'x-secret-header': 'hidden' },
        }),
      requestLogger,
      logger: new Logger({ level: 'silent' }),
    });
    await client.get('https://api.example.com/v1', { log: { provider: 'test', direction: 'mcp' }, timeoutMs: 5000 });

    const all = readLogLines(tmp).join('\n');
    expect(all).not.toContain('secretCookie');
    expect(all).not.toContain('x-secret-header');
  });

  it('truncates large response bodies at maxResponseLogSize', async () => {
    const big = `x`.repeat(5000);
    requestLogger.setSettings({ maxResponseLogSize: 256 });
    const client = new HttpClient({
      fetchImpl: async () => new Response(JSON.stringify({ data: big, apiKey: 'internal-secret' }), { status: 200 }),
      requestLogger,
      logger: new Logger({ level: 'silent' }),
    });
    await client.get('https://api.example.com/v1/big', { log: { provider: 'test', direction: 'health' }, timeoutMs: 5000 });

    const all = readLogLines(tmp).join('\n');
    expect(all).toContain('[Response truncated]');
    expect(all).not.toContain('internal-secret');
    // загруженная запись имеет флаг bodyTruncated
    expect(JSON.parse(readLogLines(tmp)[0]).response.bodyTruncated).toBe(true);
  });

  it('records error entries with sanitized message (no stack traces)', async () => {
    const client = new HttpClient({
      fetchImpl: async () => new Response(JSON.stringify({ message: 'Not Found' }), { status: 404 }),
      requestLogger,
      logger: new Logger({ level: 'silent' }),
    });
    await client.get('https://api.example.com/v1/missing', { log: { provider: 'test', direction: 'mcp' }, timeoutMs: 5000 }).catch(() => undefined);

    const entry = JSON.parse(readLogLines(tmp)[0]);
    expect(entry.success).toBe(false);
    expect(entry.status).toBe(404);
    expect(entry.error.kind).toBe('external');
    expect(entry.error.message).toContain('Not Found');
    expect(entry.error.message).not.toContain('at ');
  });

  it('redacts typical token patterns in arbitrary error text', async () => {
    const client = new HttpClient({
      fetchImpl: async () => {
        throw new Error(`fetch failed for ghp_AAAAAA2222223333 endpoint`);
      },
      requestLogger,
      logger: new Logger({ level: 'silent' }),
    });
    await client.get('https://api.example.com/v1', { log: { provider: 'test', direction: 'mcp' }, timeoutMs: 5000 }).catch(() => undefined);

    const all = readLogLines(tmp).join('\n');
    expect(all).not.toContain('ghp_AAAAAA2222223333');
  });
});