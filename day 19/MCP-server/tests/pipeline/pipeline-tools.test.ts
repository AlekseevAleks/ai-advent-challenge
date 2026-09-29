import { describe, expect, it, afterEach } from 'vitest';
import { mkdtempSync, rmSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js';
import { Logger } from '../../src/core/logging/logger.js';
import { PipelineStorage } from '../../src/core/pipeline/pipeline-storage.js';
import { PipelineRegistry } from '../../src/core/pipeline/pipeline-registry.js';
import { McpGateway } from '../../src/server/mcp-server.js';
import { createHarness, type Harness } from '../helpers.js';

let tmpDirs: string[] = [];
let harness: Harness | undefined;
afterEach(() => {
  harness?.cleanup();
  harness = undefined;
  for (const d of tmpDirs) rmSync(d, { recursive: true, force: true });
  tmpDirs = [];
});

async function connect(pipelineRegistry: PipelineRegistry, existing?: Harness) {
  harness = existing ?? createHarness({});
  await harness.registry.loadProviders();
  await harness.registry.initializeAll();
  const gateway = new McpGateway(harness.registry, new Logger({ level: 'silent' }), {
    configManager: harness.configManager,
    pipelineRegistry,
  });
  const server = gateway.createSessionServer();
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  await server.connect(serverTransport);
  const client = new Client({ name: 'pipeline-tools-test', version: '1.0.0' });
  await client.connect(clientTransport);
  return { client };
}

function makeRegistry(): PipelineRegistry {
  const dir = mkdtempSync(path.join(os.tmpdir(), 'mcp-gw-ptool-'));
  tmpDirs.push(dir);
  return new PipelineRegistry(new PipelineStorage(path.join(dir, 'pipelines.db')));
}

describe('Pipeline Tools (list_pipelines / delete_pipeline / enable-disable для MCP)', () => {
  it('registers pipeline tools and lists pipelines', async () => {
    const registry = makeRegistry();
    await registry.seedDemo();
    const { client } = await connect(registry);
    const { tools } = await client.listTools();
    expect(tools.some((t) => t.name === 'list_pipelines')).toBe(true);
    expect(tools.some((t) => t.name === 'delete_pipeline')).toBe(true);
    // run_pipeline не регистрируется без executor
    expect(tools.some((t) => t.name === 'run_pipeline')).toBe(false);

    const result = await client.callTool({ name: 'list_pipelines', arguments: {} });
    expect(result.isError).toBeFalsy();
    const parsed = JSON.parse((result.content as Array<{ text: string }>)[0].text);
    expect(parsed.total).toBe(2);
    expect(parsed.items.map((p: { id: string }) => p.id).sort()).toEqual(['github-summary', 'weather-snapshot']);
    await client.close();
  });

  it('delete_pipeline removes the pipeline', async () => {
    const registry = makeRegistry();
    await registry.seedDemo();
    const { client } = await connect(registry);

    const del = await client.callTool({ name: 'delete_pipeline', arguments: { pipeline: 'weather-snapshot' } });
    expect(del.isError).toBeFalsy();
    expect(JSON.parse((del.content as Array<{ text: string }>)[0].text).deleted).toBe(true);
    expect(registry.get('weather-snapshot')).toBeNull();

    const missing = await client.callTool({ name: 'delete_pipeline', arguments: { pipeline: 'nope' } });
    expect(missing.isError).toBe(true);
    await client.close();
  });

  it('disabled pipeline tools disappear from tools/list and cannot be called', async () => {
    const registry = makeRegistry();
    await registry.seedDemo();
    harness = createHarness({});
    harness.configManager.updatePipelineToolConfig('delete_pipeline', false);

    const { client } = await connect(registry, harness);
    const { tools } = await client.listTools();
    expect(tools.some((t) => t.name === 'delete_pipeline')).toBe(false);
    expect(tools.some((t) => t.name === 'list_pipelines')).toBe(true);

    const call = await client.callTool({ name: 'delete_pipeline', arguments: { pipeline: 'weather-snapshot' } });
    expect(call.isError).toBe(true);
    expect((call.content as Array<{ text: string }>)[0].text.toLowerCase()).toContain('disabled');

    expect(harness.configManager.isPipelineToolEnabled('delete_pipeline')).toBe(false);
    await client.close();
  });
});