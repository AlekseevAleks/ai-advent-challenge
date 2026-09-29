import { describe, expect, it, afterEach } from 'vitest';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js';
import { Logger } from '../../src/core/logging/logger.js';
import { McpGateway } from '../../src/server/mcp-server.js';
import { createSchedulerHarness, weatherOk, type SchedulerHarness } from './helpers.js';

let h: SchedulerHarness | undefined;
afterEach(() => h?.cleanup());

async function connectGateway(): Promise<Client> {
  const gateway = new McpGateway(h!.harness.registry, new Logger({ level: 'silent' }), {
    taskManager: h!.manager,
    configManager: h!.harness.configManager,
  });
  const server = gateway.createSessionServer();
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  await server.connect(serverTransport);
  const client = new Client({ name: 'sched-tools-test', version: '1.0.0' });
  await client.connect(clientTransport);
  return client;
}

const TOOL = 'create_scheduled_task';

describe('Scheduler Tools (включение/выключение для MCP)', () => {
  it('enabled by default and listed for the agent', async () => {
    h = await createSchedulerHarness({ onFetch: weatherOk });
    const client = await connectGateway();
    const { tools } = await client.listTools();
    expect(tools.some((t) => t.name === TOOL)).toBe(true);
    await client.close();
  });

  it('disabled tool disappears from tools/list and cannot be called', async () => {
    h = await createSchedulerHarness({ onFetch: weatherOk });
    h.harness.configManager.updateSchedulerToolConfig(TOOL, false);

    const client = await connectGateway();
    const { tools } = await client.listTools();
    expect(tools.some((t) => t.name === TOOL)).toBe(false);

    const call = await client.callTool({ name: TOOL, arguments: { name: 'x' } });
    expect(call.isError).toBe(true);
    const text = (call.content as Array<{ text?: string }>)[0]?.text ?? '';
    expect(text.toLowerCase()).toContain('disabled');
    await client.close();
  });

  it('state persists in config/scheduler-tools.json and can be re-enabled', async () => {
    h = await createSchedulerHarness({ onFetch: weatherOk });
    expect(h.harness.configManager.isSchedulerToolEnabled(TOOL)).toBe(true);

    h.harness.configManager.updateSchedulerToolConfig(TOOL, false);
    expect(h.harness.configManager.isSchedulerToolEnabled(TOOL)).toBe(false);
    const saved = h.harness.configManager.loadSchedulerToolsConfig();
    expect(saved[TOOL]?.enabled).toBe(false);

    h.harness.configManager.updateSchedulerToolConfig(TOOL, true);
    expect(h.harness.configManager.isSchedulerToolEnabled(TOOL)).toBe(true);
  });
});