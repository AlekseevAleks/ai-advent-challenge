import { describe, expect, it, afterEach } from 'vitest';
import { AppError } from '../src/core/errors.js';
import { createHarness } from './helpers.js';
import type { Harness } from './helpers.js';

let harness: Harness | undefined;
afterEach(() => harness?.cleanup());

const currentPayload = {
  latitude: 52.52,
  longitude: 13.405,
  timezone: 'auto',
  current_weather: true,
  current: {
    time: '2026-09-27T10:00',
    temperature_2m: 12.3,
    apparent_temperature: 10.1,
    relative_humidity_2m: 61,
    precipitation: 0.4,
    weather_code: 61,
    wind_speed_10m: 9.8,
    wind_direction_10m: 200,
    is_day: 1,
  },
  current_units: { temperature_2m: '°C', wind_speed_10m: 'km/h', precipitation: 'mm' },
};

const forecastPayload = {
  latitude: 52.52,
  longitude: 13.405,
  timezone: 'auto',
  daily: {
    time: ['2026-09-27', '2026-09-28', '2026-09-29'],
    weather_code: [2, 61, 80],
    temperature_2m_max: [18.1, 16.4, 15.2],
    temperature_2m_min: [9.2, 10.5, 11.0],
    precipitation_sum: [0, 3.2, 1.1],
    wind_speed_10m_max: [12.0, 21.4, 17.8],
    sunrise: ['06:00', '06:02', '06:04'],
    sunset: ['18:10', '18:08', '18:05'],
  },
};

function makeHarness(handler: (url: string) => Response): Harness {
  return createHarness({
    providerConfigs: { weather: { id: 'weather', enabled: true } },
    onFetch: (url) => handler(String(url)),
  });
}

describe('Weather provider', () => {
  it('validates tool input (missing/invalid latitude)', async () => {
    harness = makeHarness(() => new Response('{}', { status: 200 }));
    await harness.registry.loadProviders();
    await harness.registry.initializeAll();

    await expect(harness.registry.executeTool('weather_current', { longitude: 13 })).rejects.toMatchObject({
      kind: 'user',
      message: expect.stringContaining('Invalid input'),
    });
    await expect(harness.registry.executeTool('weather_current', { latitude: 999, longitude: 13 })).rejects.toMatchObject({
      kind: 'user',
    });
  });

  it('validates forecast days range', async () => {
    harness = makeHarness(() => new Response('{}', { status: 200 }));
    await harness.registry.loadProviders();
    await harness.registry.initializeAll();

    await expect(
      harness.registry.executeTool('weather_forecast', { latitude: 52.52, longitude: 13.405, days: 100 }),
    ).rejects.toMatchObject({ kind: 'user' });
  });

  it('parses current weather response into a friendly result', async () => {
    harness = makeHarness(() => new Response(JSON.stringify(currentPayload), { status: 200 }));
    await harness.registry.loadProviders();
    await harness.registry.initializeAll();

    const result = (await harness.registry.executeTool('weather_current', { latitude: 52.52, longitude: 13.405 })) as Record<string, unknown>;
    const weather = result.weather as Record<string, unknown>;
    expect(weather.temperatureC).toBe(12.3);
    expect(weather.relativeHumidityPct).toBe(61);
    expect(weather.description).toBe('Slight rain');
    expect(weather.isDay).toBe(true);
    expect((result.location as Record<string, unknown>).timezone).toBe('auto');
  });

  it('parses forecast response with per-day summaries', async () => {
    harness = makeHarness(() => new Response(JSON.stringify(forecastPayload), { status: 200 }));
    await harness.registry.loadProviders();
    await harness.registry.initializeAll();

    const result = (await harness.registry.executeTool('weather_forecast', { latitude: 52.52, longitude: 13.405, days: 3 })) as {
      requestedDays: number;
      forecast: Array<Record<string, unknown>>;
    };
    expect(result.requestedDays).toBe(3);
    expect(result.forecast).toHaveLength(3);
    expect(result.forecast[0].temperatureMaxC).toBe(18.1);
    expect(result.forecast[1].description).toBe('Slight rain');
    expect(result.forecast[0].sunrise).toBe('06:00');
  });

  it('maps external API errors (500) to a sanitized external error', async () => {
    harness = makeHarness(() => new Response(JSON.stringify({ error: true, reason: 'Example error' }), { status: 500 }));
    await harness.registry.loadProviders();
    await harness.registry.initializeAll();

    let err: AppError | undefined;
    try {
      await harness.registry.executeTool('weather_current', { latitude: 52.52, longitude: 13.405 });
    } catch (caught) {
      err = caught as AppError;
    }
    expect(err?.kind).toBe('external');
    expect(err?.status).toBe(500);
    expect(err?.message).not.toContain('at Object');
  });

  it('maps HTTP 429 to a rate limit error', async () => {
    harness = makeHarness(() => new Response('Too many requests', { status: 429, headers: { 'retry-after': '30' } }));
    await harness.registry.loadProviders();
    await harness.registry.initializeAll();

    const err = await harness.registry
      .executeTool('weather_current', { latitude: 52.52, longitude: 13.405 })
      .then(() => undefined)
      .catch((e: AppError) => e);
    expect(err?.kind).toBe('rate_limit');
    expect(err?.retryAfter).toBe(30);
  });

  it('health check hits Open-Meteo and reports ok', async () => {
    harness = makeHarness(() => new Response(JSON.stringify(currentPayload), { status: 200 }));
    await harness.registry.loadProviders();
    await harness.registry.initializeAll();

    const health = await harness.registry.testConnection('weather');
    expect(health.status).toBe('ok');
    expect(health.checkedAt).toBeTruthy();
  });
});