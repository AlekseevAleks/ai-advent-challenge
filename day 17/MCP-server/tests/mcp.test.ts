import { describe, expect, it, afterEach } from 'vitest';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js';
import { Logger } from '../src/core/logging/logger.js';
import { McpGateway } from '../src/server/mcp-server.js';
import { createHarness } from './helpers.js';
import type { Harness } from './helpers.js';

let harness: Harness | undefined;
afterEach(() => harness?.cleanup());

const goodWeather = (): Response =>
  new Response(
    JSON.stringify({
      latitude: 52.52,
      longitude: 13.405,
      timezone: 'auto',
      current: { time: '2026-09-27T10:00', temperature_2m: 21.1, weather_code: 0, wind_speed_10m: 5 },
      current_units: { temperature_2m: '°C', wind_speed_10m: 'km/h' },
    }),
    { status: 200 },
  );

async function setup(opts: { providerConfigs: Record<string, unknown>; onFetch?: (url: string) => Response }) {
  harness = createHarness({ providerConfigs: opts.providerConfigs, onFetch: opts.onFetch });
  await harness.registry.loadProviders();
  await harness.registry.initializeAll();
  const gateway = new McpGateway(harness.registry, new Logger({ level: 'silent' }));
  const server = gateway.createSessionServer();
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  await server.connect(serverTransport);
  const client = new Client({ name: 'test-client', version: '1.0.0' });
  await client.connect(clientTransport);
  return { client };
}

describe('MCP server (tools/list, tools/call)', () => {
  it('exposes enabled tools and hides disabled ones', async () => {
    const { client } = await setup({
      providerConfigs: {
        weather: {
          id: 'weather',
          enabled: true,
          tools: { weather_forecast: { enabled: false } },
        },
        github: {
          id: 'github',
          enabled: true,
          tools: { github_search_repositories: { enabled: false } },
        },
        gismeteo: { id: 'gismeteo', enabled: false },
      },
      onFetch: goodWeather,
    });

    const { tools } = await client.listTools();
    const names = tools.map((t) => t.name).sort();
    expect(names).toEqual(
      ['weather_current', 'github_get_repository', 'github_list_issues', 'github_get_issue', 'github_list_pull_requests', 'github_get_file'].sort(),
    );
    expect(names).not.toContain('weather_forecast');
    expect(names).not.toContain('github_search_repositories');

    // Описания и inputSchema передаются клиенту
    const repo = tools.find((t) => t.name === 'github_get_repository')!;
    expect(repo.description).toContain('репозитори');
    expect((repo.inputSchema as { required?: string[] }).required).toEqual(['owner', 'repo']);
    await client.close();
  });

  it('executes a real weather tool through MCP and returns text content', async () => {
    const { client } = await setup({
      providerConfigs: { weather: { id: 'weather', enabled: true } },
      onFetch: goodWeather,
    });

    const result = await client.callTool({
      name: 'weather_current',
      arguments: { latitude: 52.52, longitude: 13.405 },
    });

    expect(result.isError).toBeFalsy();
    const text = (result.content as Array<{ type: string; text?: string }>)[0]?.text ?? '';
    expect(text).toContain('temperatureC');
    expect(text).toContain('21.1');
    await client.close();
  });

  it('returns isError=true for disabled tools (not exposed to agent)', async () => {
    const { client } = await setup({
      providerConfigs: { weather: { id: 'weather', enabled: true, tools: { weather_current: { enabled: false } } } },
      onFetch: goodWeather,
    });

    const result = await client.callTool({ name: 'weather_current', arguments: { latitude: 1, longitude: 1 } });
    expect(result.isError).toBe(true);
    const text = (result.content as Array<{ type: string; text?: string }>)[0]?.text ?? '';
    expect(text.toLowerCase()).toContain('unknown or disabled');
    await client.close();
  });

  it('returns isError=true with sanitized message for API errors (no stack traces)', async () => {
    const { client } = await setup({
      providerConfigs: { weather: { id: 'weather', enabled: true } },
      onFetch: () => new Response(JSON.stringify({ error: true, reason: 'Example error' }), { status: 500 }),
    });

    const result = await client.callTool({ name: 'weather_current', arguments: { latitude: 52.52, longitude: 13.405 } });
    expect(result.isError).toBe(true);
    const text = (result.content as Array<{ type: string; text?: string }>)[0]?.text ?? '';
    expect(text).toContain('External API error');
    expect(text).not.toContain('at Object');
    expect(text).not.toContain('provider.ts');
    await client.close();
  });

  it('returns isError=true for invalid tool input', async () => {
    const { client } = await setup({
      providerConfigs: { weather: { id: 'weather', enabled: true } },
      onFetch: goodWeather,
    });

    const result = await client.callTool({ name: 'weather_current', arguments: { latitude: 'not-a-number', longitude: 13.405 } });
    expect(result.isError).toBe(true);
    const text = (result.content as Array<{ type: string; text?: string }>)[0]?.text ?? '';
    expect(text).toContain('Invalid input');
    await client.close();
  });

  it('re-exposes tools after they are enabled/disabled at runtime (hot reload)', async () => {
    const { client } = await setup({
      providerConfigs: { weather: { id: 'weather', enabled: true } },
      onFetch: goodWeather,
    });

    const before = (await client.listTools()).tools.map((t) => t.name);
    expect(before).toContain('weather_forecast');

    await harness!.registry.updateToolConfig('weather', 'weather_forecast', { enabled: false });
    const after = (await client.listTools()).tools.map((t) => t.name);
    expect(after).not.toContain('weather_forecast');

    // и снова включаем — tool возвращается
    await harness!.registry.updateToolConfig('weather', 'weather_forecast', { enabled: true });
    const again = (await client.listTools()).tools.map((t) => t.name);
    expect(again).toContain('weather_forecast');
    await client.close();
  });
});