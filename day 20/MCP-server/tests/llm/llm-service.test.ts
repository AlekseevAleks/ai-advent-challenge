import { describe, expect, it } from 'vitest';
import { mkdtempSync, rmSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { AppError } from '../../src/core/errors.js';
import { HttpClient } from '../../src/core/http/http-client.js';
import { Logger } from '../../src/core/logging/logger.js';
import { LlmSettingsStore } from '../../src/core/llm/llm-settings-store.js';
import { LlmService } from '../../src/core/llm/llm-service.js';
import { OpenAIProvider } from '../../src/core/llm/openai-provider.js';

const KEY = 'sk-test-1234567890';

function makeService(handler: (url: string, init?: RequestInit) => Response | Promise<Response>, opts: { timeoutMs?: number } = {}) {
  const dir = mkdtempSync(path.join(os.tmpdir(), 'mcp-gw-llmtest-'));
  const client = new HttpClient({
    fetchImpl: (async (url: string, init?: RequestInit) => handler(url, init)) as unknown as typeof fetch,
    logger: new Logger({ level: 'silent' }),
    defaultRetries: 0,
  });
  const service = new LlmService({
    store: new LlmSettingsStore(dir),
    http: client,
    logger: new Logger({ level: 'silent' }),
    getTimeoutMs: () => opts.timeoutMs ?? 5000,
  });
  return { service, dir, client };
}

function json(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json', ...headers } });
}

/** fetch-мок, который корректно реагирует на abort (как реальная сеть). */
function makeTimeoutFetch(): typeof fetch {
  return (async (_url: string, init?: RequestInit) => {
    return new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => {
        reject(new DOMException('The operation was aborted', 'TimeoutError'));
      });
    });
  }) as unknown as typeof fetch;
}

function errCode(promise: Promise<unknown>): Promise<string | undefined> {
  return promise.then(
    () => undefined,
    (err: { code?: string }) => err?.code,
  );
}

describe('LLMService (OpenAIProvider)', () => {
  it('summarize path: uses the saved model and returns structured summary', async () => {
    const captured: Array<{ url: string; body: unknown; headers?: Record<string, string> }> = [];
    const { service, dir } = makeService(async (url, init) => {
      captured.push({ url: String(url), body: init?.body ? JSON.parse(String(init.body)) : null, headers: init?.headers as Record<string, string> });
      return json(200, { choices: [{ message: { content: 'Concise summary text' } }] });
    });
    service.save({ provider: 'openai', apiUrl: 'https://api.openai.com/v1', apiKey: KEY, model: 'gpt-4.1' });

    const summary = await service.chat('You are a concise summarization assistant.', 'Summarize: 42');
    expect(summary).toBe('Concise summary text');

    const call = captured.find((c) => String(c.url).endsWith('/chat/completions'))!;
    expect(call.url).toBe('https://api.openai.com/v1/chat/completions');
    const body = call.body as { model: string; messages: Array<{ role: string; content: string }> };
    expect(body.model).toBe('gpt-4.1'); // используется выбранная модель
    expect(body.messages[0].content).toBe('You are a concise summarization assistant.');
    expect(body.messages[1].content).toContain('Summarize: 42');
    const authHeader = Object.entries(call.headers ?? {}).find(([k]) => k.toLowerCase() === 'authorization');
    expect(authHeader?.[1]).toBe(`Bearer ${KEY}`);
    rmSync(dir, { recursive: true, force: true });
  });

  it('chat without LLM configuration returns a clear error', async () => {
    const { service, dir } = makeService(async () => json(200, {}));
    const err = await errCode(service.chat('system', 'data'));
    expect(err).toBe('LLM_NOT_CONFIGURED');
    rmSync(dir, { recursive: true, force: true });
  });

  it('check connection performs real GET /models with provided key (no save)', async () => {
    const urls: string[] = [];
    const { service, dir } = makeService(async (url, init) => {
      urls.push(String(url));
      const headers = init?.headers as Record<string, string>;
      expect(Object.values(headers).some((h) => h.includes('sk-check-key'))).toBe(true);
      return json(200, { data: [{ id: 'gpt-4.1' }] });
    });
    const result = await service.checkConnection({ apiUrl: 'https://api.openai.com/v1', apiKey: 'sk-check-key' });
    expect(result.ok).toBe(true);
    expect(result.status).toBe('connected');
    expect(urls.some((u) => u === 'https://api.openai.com/v1/models')).toBe(true);
    // ключ из check не сохранился
    expect(service.getPublic().configured).toBe(false);
    rmSync(dir, { recursive: true, force: true });
  });

  it('invalid key (401) is reported without leaking the key', async () => {
    const { service, dir } = makeService(async () => json(401, { error: { message: 'bad token' } }));
    const result = await service.checkConnection({ apiUrl: 'https://api.openai.com/v1', apiKey: KEY });
    expect(result.ok).toBe(false);
    expect(result.message).toContain('401');
    expect(result.message).not.toContain(KEY);
    rmSync(dir, { recursive: true, force: true });
  });

  it('handles 403 / 404 / 429 / 500 distinctly', async () => {
    const cases: Array<[number, string]> = [
      [403, 'unauthorized'],
      [404, 'Endpoint not found'],
      [429, 'rate limit'],
      [500, 'server error'],
    ];
    for (const [status, expected] of cases) {
      const { service, dir } = makeService(async () => json(status, { error: { message: 'x' } }, { 'retry-after': '10' }));
      const result = await service.checkConnection({ apiUrl: 'https://api.openai.com/v1', apiKey: KEY });
      expect(result.ok).toBe(false);
      expect(result.message.toLowerCase()).toContain(expected.toLowerCase());
      expect(result.message).not.toContain(KEY);
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it('handles timeout', async () => {
    const dir = mkdtempSync(path.join(os.tmpdir(), 'mcp-gw-llmtest-'));
    const client = new HttpClient({ fetchImpl: makeTimeoutFetch(), logger: new Logger({ level: 'silent' }), defaultRetries: 0 });
    const service = new LlmService({
      store: new LlmSettingsStore(dir),
      http: client,
      logger: new Logger({ level: 'silent' }),
      getTimeoutMs: () => 60,
    });
    const result = await service.checkConnection({ apiUrl: 'https://api.openai.com/v1', apiKey: KEY });
    expect(result.ok).toBe(false);
    expect(result.message.toLowerCase()).toContain('timed out');
    expect(result.message).not.toContain(KEY);
    rmSync(dir, { recursive: true, force: true });
  }, 10_000);

  it('listModels parses data[].id and rejects missing models list', async () => {
    const { service, dir } = makeService(async () => json(200, { data: [{ id: 'b-model' }, { id: 'a-model' }] }));
    const models = await service.listModels({ apiUrl: 'https://api.openai.com/v1', apiKey: KEY });
    expect(models).toEqual(['a-model', 'b-model']);

    const empty = makeService(async () => json(200, { data: [] }));
    await expect(empty.service.listModels({ apiUrl: 'https://api.openai.com/v1', apiKey: KEY })).rejects.toMatchObject({
      message: expect.stringContaining('data[].id'),
    });
    rmSync(empty.dir, { recursive: true, force: true });
    rmSync(dir, { recursive: true, force: true });
  });

  it('model fetch respects manual/unknown model id (no extra validation)', async () => {
    const { service, dir } = makeService(async (url) => {
      if (String(url).includes('/chat/completions')) {
        return json(200, { choices: [{ message: { content: 'ok' } }] });
      }
      return json(200, { data: [{ id: 'gpt-4.1' }] });
    });
    service.save({ provider: 'openai', apiUrl: 'https://api.openai.com/v1', apiKey: KEY, model: 'my-custom-model' });
    const summary = await service.chat('system', 'data');
    expect(summary).toBe('ok');
    expect(service.getPublic().model).toBe('my-custom-model');
    rmSync(dir, { recursive: true, force: true });
  });

  it('malformed chat response is reported as unexpected response', async () => {
    const { service, dir } = makeService(async () => json(200, { choices: [] }));
    service.save({ provider: 'openai', apiUrl: 'https://api.openai.com/v1', apiKey: KEY, model: 'gpt-4.1' });
    let err: Error | undefined;
    try {
      await service.chat('system', 'data');
    } catch (e) {
      err = e as Error;
    }
    expect(err?.message).toContain('Unexpected chat completion response');
    expect(err?.message).not.toContain(KEY);
    rmSync(dir, { recursive: true, force: true });
  });

  it('timeout is applied to LLM requests (no infinite wait)', async () => {
    const provider = new OpenAIProvider(
      new HttpClient({
        fetchImpl: makeTimeoutFetch(),
        logger: new Logger({ level: 'silent' }),
        defaultRetries: 0,
      }),
      () => 40,
    );
    await expect(
      provider.chat({ provider: 'openai', apiUrl: 'https://api.openai.com/v1', apiKey: KEY, model: 'm' }, { model: 'm', system: 's', user: 'u' }),
    ).rejects.toMatchObject({ kind: 'timeout' });
  }, 10_000);
});