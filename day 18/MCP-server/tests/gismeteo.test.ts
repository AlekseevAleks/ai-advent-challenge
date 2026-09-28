import { describe, expect, it, afterEach } from 'vitest';
import { AppError } from '../src/core/errors.js';
import { createHarness } from './helpers.js';
import type { Harness } from './helpers.js';

let harness: Harness | undefined;
afterEach(() => harness?.cleanup());

const CURRENT_PAYLOAD = {
  meta: { code: '200' },
  response: {
    kind: 'fact',
    date: { UTC: '2026-09-27T12:00:00Z', unix: 1_784_390_400, local: '2026-09-27T15:00:00+03:00', time_zone_offset: 180 },
    temperature: { air: { C: 18.4, F: 65.1 }, comfort: { C: 16.2, F: 61.2 }, water: { C: null, F: null } },
    description: { full: 'Облачно с прояснениями' },
    humidity: { percent: 62 },
    pressure: { mm_hg_atm: 745, in_hg: 29.3, h_pa: 993 },
    cloudiness: { percent: 60, type: 2 },
    storm: false,
    precipitation: { type: 0, amount: 0, intensity: 0, type_ext: 0, correction: null, duration: 0 },
    phenomenon: 5,
    icon: '/static/img/icons/ovc.svg',
    gm: 0,
    wind: { direction: { scale_8: 3, degree: 90 }, speed: { km_h: 13, mi_h: 8, m_s: 3 } },
    radiation: { UVB: 2, uvb_index: 2 },
    city: 4368,
  },
};

const FORECAST_PAYLOAD = {
  meta: { code: '200' },
  response: [
    {
      kind: null,
      date: { UTC: '2026-09-27T00:00:00Z', unix: 1, local: '2026-09-27T03:00:00+03:00', time_zone_offset: 180 },
      temperature: { air: { min: { C: 8.1 }, max: { C: 18.4 }, avg: { C: 13.2 } } },
      description: { full: 'Облачно с прояснениями' },
      humidity: { percent: { min: 45, max: 80, avg: 63 } },
      pressure: { mm_hg_atm: { min: 742, max: 748 } },
      cloudiness: { percent: 60, type: 2 },
      storm: false,
      precipitation: { type: 0, amount: 0.2, intensity: 0 },
      icon: '/static/img/icons/ovc.svg',
      wind: { speed: { min: { km_h: 8 }, max: { km_h: 20 }, avg: { km_h: 13 } } },
      radiation: { max: 3, max_index: 3 },
      city: 4368,
    },
    {
      date: { UTC: '2026-09-28T00:00:00Z', unix: 2, local: '2026-09-28T03:00:00+03:00', time_zone_offset: 180 },
      temperature: { air: { min: { C: 10.0 }, max: { C: 15.1 }, avg: { C: 12.4 } } },
      description: { full: 'Пасмурно, небольшой дождь' },
      humidity: { percent: { min: 60, max: 90, avg: 75 } },
      precipitation: { type: 1, amount: 2.4, intensity: 1 },
      wind: { speed: { avg: { km_h: 9 } } },
      city: 4368,
    },
  ],
};

const SEARCH_PAYLOAD = {
  meta: { code: '200' },
  response: [
    {
      id: 4368,
      name: 'Москва',
      nameP: 'в Москве',
      url: '/weather-moscow-4368/',
      kind: 'T',
      rate: 1,
      weight: 100,
      country: { code: 'RU', name: 'Россия', nameP: 'России' },
      district: { name: 'Москва', nameP: 'Москве' },
      subDistrict: { name: null, nameP: null },
    },
  ],
};

function gismeteoHarness(handler: (url: string, init?: RequestInit) => Response, token = 'gmt_secret_token_123456'): Harness {
  return createHarness({
    providerConfigs: { gismeteo: { id: 'gismeteo', enabled: true, credentials: { token } } },
    onFetch: handler,
  });
}

describe('Gismeteo provider', () => {
  it('requires a token to execute tools', async () => {
    harness = gismeteoHarness(() => new Response('{}', { status: 200 }), '');
    await harness.registry.loadProviders();
    await harness.registry.initializeAll();

    const err = await harness.registry
      .executeTool('gismeteo_current', { cityId: 4368 })
      .then(() => undefined)
      .catch((e: AppError) => e);
    expect(err?.kind).toBe('auth');
    expect(err?.message).toContain('Gismeteo API requires a token');
  });

  it('validates input: cityId or coordinates required', async () => {
    harness = gismeteoHarness(() => new Response('{}', { status: 200 }));
    await harness.registry.loadProviders();
    await harness.registry.initializeAll();

    await expect(harness.registry.executeTool('gismeteo_current', {})).rejects.toMatchObject({
      kind: 'user',
      message: expect.stringContaining('Invalid input'),
    });
    await expect(harness.registry.executeTool('gismeteo_current', { latitude: 55.7 })).rejects.toMatchObject({ kind: 'user' });
  });

  it('sends X-Gismeteo-Token header', async () => {
    const captured: Array<RequestInit | undefined> = [];
    harness = gismeteoHarness((_url, init) => {
      captured.push(init);
      return new Response(JSON.stringify(CURRENT_PAYLOAD), { status: 200 });
    }, 'gmt_secret_token_123456');
    await harness.registry.loadProviders();
    await harness.registry.initializeAll();

    await harness.registry.executeTool('gismeteo_current', { cityId: 4368 });
    const headers = captured[0]?.headers as Record<string, string>;
    const tokenHeader = Object.entries(headers).find(([k]) => k.toLowerCase() === 'x-gismeteo-token');
    expect(tokenHeader?.[1]).toBe('gmt_secret_token_123456');
  });

  it('parses current weather into a friendly result', async () => {
    harness = gismeteoHarness(() => new Response(JSON.stringify(CURRENT_PAYLOAD), { status: 200 }));
    await harness.registry.loadProviders();
    await harness.registry.initializeAll();

    const result = (await harness.registry.executeTool('gismeteo_current', { cityId: 4368 })) as Record<string, unknown>;
    expect(result.temperatureC).toBe(18.4);
    expect(result.feelsLikeC).toBe(16.2);
    expect(result.description).toBe('Облачно с прояснениями');
    expect(result.humidityPct).toBe(62);
    expect(result.pressureMmHg).toBe(745);
    expect(result.cloudiness).toBe('Облачно с прояснениями');
    expect((result.precipitation as Record<string, unknown>).typeLabel).toBe('Нет осадков');
    expect((result.wind as Record<string, unknown>).speedKmh).toBe(13);
    expect((result.wind as Record<string, unknown>).direction).toBe('Восточный');
    expect(result.cityId).toBe(4368);
  });

  it('parses aggregated forecast into daily summaries', async () => {
    harness = gismeteoHarness(() => new Response(JSON.stringify(FORECAST_PAYLOAD), { status: 200 }));
    await harness.registry.loadProviders();
    await harness.registry.initializeAll();

    const result = (await harness.registry.executeTool('gismeteo_forecast', { latitude: 55.75, longitude: 37.61, days: 5 })) as {
      days: Array<Record<string, unknown>>;
    };
    expect(result.days).toHaveLength(2);
    const day = result.days[0];
    expect((day.temperatureC as Record<string, unknown>).min).toBe(8.1);
    expect((day.temperatureC as Record<string, unknown>).max).toBe(18.4);
    expect((day.humidityPct as Record<string, unknown>).avg).toBe(63);
    expect((day.windSpeedKmh as Record<string, unknown>).max).toBe(20);
    expect(day.description).toBe('Облачно с прояснениями');
    expect(result.days[1].dateLocal).toBe('2026-09-28T03:00:00+03:00');
  });

  it('parses city search results', async () => {
    harness = gismeteoHarness(() => new Response(JSON.stringify(SEARCH_PAYLOAD), { status: 200 }));
    await harness.registry.loadProviders();
    await harness.registry.initializeAll();

    const result = (await harness.registry.executeTool('gismeteo_search_city', { query: 'Москва' })) as {
      items: Array<Record<string, unknown>>;
    };
    expect(result.items).toHaveLength(1);
    expect(result.items[0].id).toBe(4368);
    expect(result.items[0].name).toBe('Москва');
    expect(result.items[0].countryName).toBe('Россия');
    expect(result.items[0].kindLabel).toBe('Город');
  });

  it('maps 401 (invalid token) to an authentication error with readable message', async () => {
    harness = gismeteoHarness(
      () =>
        new Response(JSON.stringify({ meta: { status_code: 401 }, errors: [{ title: 'Unauthorized', detail: 'Invalid token.' }] }), {
          status: 401,
        }),
      'gmt_bad_token',
    );
    await harness.registry.loadProviders();
    await harness.registry.initializeAll();

    const err = await harness.registry
      .executeTool('gismeteo_current', { cityId: 4368 })
      .then(() => undefined)
      .catch((e: AppError) => e);
    expect(err?.kind).toBe('auth');
    expect(err?.status).toBe(401);
    expect(err?.message).toContain('Invalid token');
    expect(err?.message).not.toContain('at ');
  });

  it('health check without a token reports a clear error', async () => {
    harness = gismeteoHarness(() => new Response('{}', { status: 200 }), '');
    await harness.registry.loadProviders();
    await harness.registry.initializeAll();

    const health = await harness.registry.testConnection('gismeteo');
    expect(health.status).toBe('error');
    expect(health.message).toContain('Token is not configured');
  });

  it('health check with token hits the API and reports ok', async () => {
    harness = gismeteoHarness(() => new Response(JSON.stringify(SEARCH_PAYLOAD), { status: 200 }), 'gmt_ok_token');
    await harness.registry.loadProviders();
    await harness.registry.initializeAll();

    const health = await harness.registry.testConnection('gismeteo');
    expect(health.status).toBe('ok');
    expect(health.checkedAt).toBeTruthy();
  });
});