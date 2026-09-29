import { describe, expect, it, afterEach } from 'vitest';
import { AppError } from '../src/core/errors.js';
import { createHarness, FakeProvider } from './helpers.js';
import type { Harness } from './helpers.js';

let harness: Harness | undefined;
afterEach(() => harness?.cleanup());

describe('ProviderRegistry', () => {
  it('registers providers and creates default config files when missing', async () => {
    harness = createHarness({ providerConfigs: {} });
    await harness.registry.loadProviders();
    expect(harness.registry.getProviderIds().sort()).toEqual(['gismeteo', 'github', 'weather']);
    expect(harness.configManager.getProviderConfig('weather')).not.toBeNull();
    expect(harness.configManager.getProviderConfig('github')).not.toBeNull();
    expect(harness.configManager.getProviderConfig('gismeteo')).not.toBeNull();
  });

  it('loads config and initializes only enabled providers', async () => {
    harness = createHarness({
      providerConfigs: {
        weather: { id: 'weather', enabled: true },
        github: { id: 'github', enabled: false },
      },
    });
    await harness.registry.loadProviders();
    await harness.registry.initializeAll();
    expect(harness.registry.isInitialized('weather')).toBe(true);
    expect(harness.registry.isInitialized('github')).toBe(false);
    // github tools недоступны
    const names = harness.registry.getMcpTools().map((t) => t.name);
    expect(names).toContain('weather_current');
    expect(names).not.toContain('github_get_repository');
  });

  it('discovers tools of all active providers', async () => {
    harness = createHarness({
      providerConfigs: {
        weather: { id: 'weather', enabled: true },
        github: { id: 'github', enabled: true },
        gismeteo: { id: 'gismeteo', enabled: false },
      },
    });
    await harness.registry.loadProviders();
    await harness.registry.initializeAll();
    const names = harness.registry.getMcpTools().map((t) => t.name).sort();
    expect(names).toEqual(
      ['weather_current', 'weather_forecast', 'github_get_repository', 'github_list_issues', 'github_get_issue', 'github_list_pull_requests', 'github_search_repositories', 'github_get_file'].sort(),
    );
  });

  it('supports disabling individual tools via config', async () => {
    harness = createHarness({
      providerConfigs: {
        weather: {
          id: 'weather',
          enabled: true,
          tools: { weather_forecast: { enabled: false } },
        },
      },
    });
    await harness.registry.loadProviders();
    await harness.registry.initializeAll();

    const names = harness.registry.getMcpTools().map((t) => t.name);
    expect(names).toContain('weather_current');
    expect(names).not.toContain('weather_forecast');
    expect(harness.registry.isToolEnabled('weather_forecast')).toBe(false);

    const state = harness.registry.getProviderRuntimeState('weather')!;
    expect(state.toolsCount).toBe(2);
    expect(state.enabledToolsCount).toBe(1);
  });

  it('updateToolConfig persists tool enabled flag and applies immediately (hot reload)', async () => {
    harness = createHarness({ providerConfigs: { weather: { id: 'weather', enabled: true } } });
    await harness.registry.loadProviders();
    await harness.registry.initializeAll();
    expect(harness.registry.isToolEnabled('weather_forecast')).toBe(true);

    await harness.registry.updateToolConfig('weather', 'weather_forecast', { enabled: false });
    expect(harness.registry.isToolEnabled('weather_forecast')).toBe(false);
    const saved = harness.configManager.getProviderConfig('weather')!;
    expect(saved.tools?.['weather_forecast']?.enabled).toBe(false);
  });

  it('enable/disable provider adds/removes its tools', async () => {
    harness = createHarness({
      providerConfigs: {
        weather: { id: 'weather', enabled: false },
        github: { id: 'github', enabled: true },
        gismeteo: { id: 'gismeteo', enabled: false },
      },
    });
    await harness.registry.loadProviders();
    await harness.registry.initializeAll();
    expect(harness.registry.getMcpTools().length).toBe(6);

    await harness.registry.setProviderEnabled('github', false);
    expect(harness.registry.isInitialized('github')).toBe(false);
    expect(harness.registry.getMcpTools().length).toBe(0);

    await harness.registry.setProviderEnabled('github', true);
    expect(harness.registry.isInitialized('github')).toBe(true);
    expect(harness.registry.getMcpTools().length).toBe(6);
  });

  it('routes executeTool to the right provider and rejects unknown tools', async () => {
    harness = createHarness({
      providerConfigs: { weather: { id: 'weather', enabled: true } },
      onFetch: (url) => {
        if (String(url).includes('/v1/forecast')) {
          return jsonOk.current();
        }
        return jsonBase.notFound();
      },
    });
    await harness.registry.loadProviders();
    await harness.registry.initializeAll();

    const result = (await harness.registry.executeTool('weather_current', { latitude: 52.52, longitude: 13.405 })) as Record<string, unknown>;
    expect((result.weather as Record<string, unknown>).temperatureC).toBe(20.5);

    let userErr: AppError | undefined;
    try {
      await harness.registry.executeTool('nope_tool', {});
    } catch (err) {
      userErr = err as AppError;
    }
    expect(userErr?.kind).toBe('user');
    expect(userErr?.message).toContain('Unknown or disabled tool');
  });

  it('masks credentials in runtime state and never exposes full token', async () => {
    harness = createHarness({
      providerConfigs: {
        github: { id: 'github', enabled: true, credentials: { token: 'ghp_supersecrettoken1234567890' } },
      },
    });
    await harness.registry.loadProviders();
    await harness.registry.initializeAll();
    const state = harness.registry.getProviderRuntimeState('github')!;
    expect(state.credentials.token.value).toContain('*');
    expect(state.credentials.token.value).not.toContain('ghp_supersecrettoken');
    expect(state.credentials.token.set).toBe(true);
  });

  it('custom provider classes can be registered (plugin architecture)', async () => {
    harness = createHarness({
      providers: [FakeProvider],
      providerConfigs: { fake: { id: 'fake', enabled: true } },
    });
    await harness.registry.loadProviders();
    await harness.registry.initializeAll();
    const names = harness.registry.getMcpTools().map((t) => t.name);
    expect(names).toContain('fake_echo');
    const result = await harness.registry.executeTool('fake_echo', { text: 'hello' });
    expect(result).toEqual({ echoed: 'hello' });
  });

  it('env credential override wins over file value and is marked overridden', async () => {
    harness = createHarness({
      providerConfigs: {
        fake: { id: 'fake', enabled: true, credentials: { api_key: 'file-value' } },
      },
      providers: [FakeProvider],
    });
    process.env.FAKE_API_KEY = 'env-secret-123456';
    try {
      await harness.registry.loadProviders();
      await harness.registry.initializeAll();
      const state = harness.registry.getProviderRuntimeState('fake')!;
      expect(state.credentials.api_key.overridden).toBe(true);
      expect(state.credentials.api_key.env).toBe('FAKE_API_KEY');
      expect(state.credentials.api_key.value).not.toContain('env-secret');
    } finally {
      delete process.env.FAKE_API_KEY;
    }
  });
});

// Небольшие фабрики ответов, чтобы тесты не раздувались
const jsonOk = {
  current: () =>
    json(200, {
      latitude: 52.52,
      longitude: 13.405,
      timezone: 'auto',
      current_weather: false,
      current: {
        time: '2026-09-27T10:00',
        temperature_2m: 20.5,
        apparent_temperature: 19.9,
        relative_humidity_2m: 55,
        precipitation: 0,
        weather_code: 2,
        wind_speed_10m: 11.2,
        wind_direction_10m: 220,
        is_day: 1,
      },
      current_units: { temperature_2m: '°C', wind_speed_10m: 'km/h', precipitation: 'mm' },
    }),
};

const jsonBase = {
  notFound: () => json(404, { message: 'Not Found' }),
};

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}