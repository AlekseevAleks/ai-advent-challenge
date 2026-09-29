import { describe, expect, it, afterEach } from 'vitest';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js';
import { Logger } from '../../src/core/logging/logger.js';
import { HttpClient } from '../../src/core/http/http-client.js';
import { LlmSettingsStore } from '../../src/core/llm/llm-settings-store.js';
import { LlmService } from '../../src/core/llm/llm-service.js';
import { OutputFileService } from '../../src/core/files/output-file.js';
import { McpGateway } from '../../src/server/mcp-server.js';
import { createHarness } from '../helpers.js';

const KEY = 'sk-test-key-1234567890';
let tmpDirs: string[] = [];

function cleanup(): void {
  for (const dir of tmpDirs) rmSync(dir, { recursive: true, force: true });
  tmpDirs = [];
}
afterEach(cleanup);

async function connectGateway(opts: { llmService?: LlmService; fileService?: OutputFileService }) {
  const harness = createHarness({});
  await harness.registry.loadProviders();
  await harness.registry.initializeAll();
  const gateway = new McpGateway(harness.registry, new Logger({ level: 'silent' }), {
    llmService: opts.llmService,
    fileService: opts.fileService,
  });
  const server = gateway.createSessionServer();
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  await server.connect(serverTransport);
  const client = new Client({ name: 'core-tools-test', version: '1.0.0' });
  await client.connect(clientTransport);
  return { client, harness };
}

describe('summarize / saveToFile core tools', () => {
  it('summarize is listed and produces {summary} using the configured model', async () => {
    const llmDir = mkdtempSync(path.join(os.tmpdir(), 'mcp-gw-sum-'));
    tmpDirs.push(llmDir);
    const captured: Array<{ body: { model: string; messages: Array<{ role: string; content: string }> } }> = [];
    const llm = new LlmService({
      store: new LlmSettingsStore(llmDir),
      http: new HttpClient({
        fetchImpl: (async (_url: string, init?: RequestInit) => {
          captured.push({ body: JSON.parse(String(init?.body)) });
          return new Response(JSON.stringify({ choices: [{ message: { content: 'Сводка: 3 issues' } }] }), { status: 200 });
        }) as unknown as typeof fetch,
        logger: new Logger({ level: 'silent' }),
        defaultRetries: 0,
      }),
      logger: new Logger({ level: 'silent' }),
      getTimeoutMs: () => 5000,
    });
    llm.save({ provider: 'openai', apiUrl: 'https://api.openai.com/v1', apiKey: KEY, model: 'gpt-4.1' });

    const { client } = await connectGateway({ llmService: llm });
    const { tools } = await client.listTools();
    expect(tools.some((t) => t.name === 'summarize')).toBe(true);

    const result = await client.callTool({
      name: 'summarize',
      arguments: { data: { items: [{ title: 'a' }, { title: 'b' }] } },
    });
    expect(result.isError).toBeFalsy();
    const parsed = JSON.parse((result.content as Array<{ text: string }>)[0].text);
    expect(parsed.summary).toBe('Сводка: 3 issues');
    expect(captured[0].body.model).toBe('gpt-4.1');
    expect(captured[0].body.messages[0].content).toBe('You are a concise summarization assistant.');
    expect(captured[0].body.messages[1].content).toContain('"title"');
    await client.close();
  });

  it('summarize without LLM configuration returns a clear error', async () => {
    const { client } = await connectGateway({});
    const result = await client.callTool({ name: 'summarize', arguments: { data: 'x' } });
    expect(result.isError).toBe(true);
    const text = (result.content as Array<{ text: string }>)[0].text;
    expect(text).toContain('LLM is not configured');
    expect(text.toLowerCase()).toContain('settings');
    await client.close();
  });

  it('saveToFile writes into data/output and blocks path traversal', async () => {
    const outDir = mkdtempSync(path.join(os.tmpdir(), 'mcp-gw-out-'));
    tmpDirs.push(outDir);
    const files = new OutputFileService(outDir);

    const ok = files.write('reports/x.txt', 'hello');
    expect(ok.path).toBe(path.join('reports', 'x.txt').replace(/\\/g, '/'));
    expect(readFileSync(path.join(outDir, 'reports', 'x.txt'), 'utf8')).toBe('hello');

    expect(() => files.write('../escape.txt', 'x')).toThrow(/path traversal/);
    expect(() => files.write('/abs/path.txt', 'x')).toThrow(/path traversal/);
    expect(() => files.write('a/../../b.txt', 'x')).toThrow(/path traversal/);
    expect(() => files.write('C:\\windows.txt', 'x')).toThrow(/absolute/);
  });

  it('saveToFile tool through MCP works and rejects traversal', async () => {
    const outDir = mkdtempSync(path.join(os.tmpdir(), 'mcp-gw-out2-'));
    tmpDirs.push(outDir);
    const { client } = await connectGateway({ fileService: new OutputFileService(outDir) });

    const ok = await client.callTool({ name: 'saveToFile', arguments: { filename: 'summary.txt', content: 'text' } });
    expect(ok.isError).toBeFalsy();
    expect(JSON.parse((ok.content as Array<{ text: string }>)[0].text).path).toBe('summary.txt');
    expect(readFileSync(path.join(outDir, 'summary.txt'), 'utf8')).toBe('text');

    const bad = await client.callTool({ name: 'saveToFile', arguments: { filename: '../evil.txt', content: 'x' } });
    expect(bad.isError).toBe(true);
    await client.close();
  });
});