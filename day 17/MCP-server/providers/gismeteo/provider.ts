import type { ProviderConfig, ProviderToolConfig } from '../../src/core/types.js';
import type { ProviderHealth, ToolDefinition } from '../../src/core/providers/types.js';
import { BaseProvider } from '../../src/core/providers/base-provider.js';
import { authError, userError } from '../../src/core/errors.js';
import { GISMETEO_TOOLS } from './tools.js';
import {
  cityKindLabel,
  cloudinessLabel,
  currentInputSchema,
  forecastInputSchema,
  GISMETEO_BASE_URL,
  GISMETEO_CONFIG_SCHEMA,
  GISMETEO_TOKEN_ENV,
  precipitationTypeLabel,
  searchCitySchema,
  windDirectionLabel,
} from './schema.js';
import type { z } from 'zod';
import type { HttpLogContext } from '../../src/core/http/http-client.js';

/** Ответы Gismeteo оборачиваются в {meta, response}. */
interface GismeteoEnvelope<T> {
  meta?: { message?: string; code?: string; status_code?: number };
  errors?: Array<{ title?: string; detail?: string }>;
  response?: T;
}

interface GismeteoWeather {
  kind?: string;
  city?: number;
  date?: Record<string, unknown>;
  temperature?: {
    air?: { C?: number; F?: number };
    comfort?: { C?: number; F?: number };
    water?: { C?: number; F?: number };
  };
  description?: { full?: string };
  humidity?: { percent?: number };
  pressure?: { mm_hg_atm?: number; h_pa?: number; in_hg?: number };
  cloudiness?: { percent?: number; type?: number };
  storm?: boolean;
  precipitation?: { type?: number; amount?: number; intensity?: number };
  phenomenon?: number;
  icon?: string;
  gm?: number;
  wind?: {
    direction?: { scale_8?: number; degree?: number };
    speed?: { km_h?: number; mi_h?: number; m_s?: number };
  };
  radiation?: { UVB?: number; uvb_index?: number };
}

interface GismeteoAggregated {
  date?: Record<string, unknown>;
  temperature?: {
    air?: {
      min?: { C?: number };
      max?: { C?: number };
      avg?: { C?: number };
    };
  };
  description?: { full?: string };
  humidity?: { percent?: { min?: number; max?: number; avg?: number } };
  pressure?: { mm_hg_atm?: { min?: number; max?: number } };
  precipitation?: { type?: number; amount?: number; intensity?: number };
  wind?: { speed?: { min?: { km_h?: number }; max?: { km_h?: number }; avg?: { km_h?: number } } };
  radiation?: { max?: number; max_index?: number };
  city?: number;
}

interface GismeteoLocation {
  id?: number;
  name?: string;
  nameP?: string;
  kind?: string;
  url?: string;
  country?: { code?: string; name?: string };
  district?: { name?: string } | null;
  subDistrict?: { name?: string } | null;
}

const LANGS = ['ru', 'en', 'ua', 'lt', 'lv', 'pl', 'ro'] as const;

/**
 * Gismeteo Weather Forecast API v2 (https://docs.gismeteo.net/v2/weather).
 * Все запросы требуют токен в заголовке X-Gismeteo-Token:
 * задаётся в Web UI (Credentials) или через env GISMETEO_TOKEN.
 */
export class GismeteoProvider extends BaseProvider {
  constructor(http: ConstructorParameters<typeof BaseProvider>[0]['http']) {
    super({
      id: 'gismeteo',
      name: 'Gismeteo',
      description:
        'Gismeteo Weather API (v2): текущая погода, суточный прогноз и поиск городов по названию/координатам. Требуется API token.',
      version: '1.0.0',
      http,
      defaultBaseUrl: GISMETEO_BASE_URL,
    });
  }

  override getConfigSchema() {
    return GISMETEO_CONFIG_SCHEMA;
  }

  override getDefaultConfig(): ProviderConfig {
    return {
      id: this.id,
      enabled: true,
      name: this.name,
      baseUrl: this.defaultBaseUrl ?? GISMETEO_BASE_URL,
      credentials: { token: '' },
      settings: { timeout: 10000 },
    };
  }

  override getCredentialEnv(): Record<string, string> {
    return { token: GISMETEO_TOKEN_ENV };
  }

  getTools(): ToolDefinition[] {
    return GISMETEO_TOOLS;
  }

  private get token(): string {
    return this.config.credentials?.token ?? '';
  }

  /** Gismeteo токен обязателен для любых запросов. */
  private requireToken(): void {
    if (!this.token) {
      throw authError(
        'Gismeteo API requires a token. Set the GISMETEO_TOKEN environment variable or fill Credentials → API Token in the Web UI.',
        'GISMETEO_TOKEN_REQUIRED',
      );
    }
  }

  private apiHeaders(): Record<string, string> {
    return { 'X-Gismeteo-Token': this.token, accept: 'application/json' };
  }

  private gismeteoErrorExtractor = (status: number, body: unknown): string | null => {
    const envelope = body as GismeteoEnvelope<never>;
    const error = envelope?.errors?.[0];
    if (error?.title || error?.detail) {
      return `Gismeteo API returned HTTP ${status}: ${[error.title, error.detail].filter(Boolean).join(': ')}`;
    }
    if (typeof envelope?.meta?.message === 'string' && envelope.meta.message) {
      return `Gismeteo API returned HTTP ${status}: ${envelope.meta.message}`;
    }
    return null;
  };

  private logCtx(tool: string, direction: 'mcp' | 'health' = 'mcp'): HttpLogContext {
    return { provider: this.id, providerName: this.name, tool, direction };
  }

  async healthCheck(): Promise<ProviderHealth> {
    if (!this.token) {
      return this.health('error', 'Token is not configured. Set GISMETEO_TOKEN env or fill Credentials in Web UI.');
    }
    try {
      const res = await this.http.get<GismeteoEnvelope<GismeteoLocation[]>>(this.url('/v2/search/cities/'), {
        query: { query: 'Москва', limit: 1, lang: 'ru' },
        headers: this.apiHeaders(),
        timeoutMs: this.getTimeoutMs(),
        log: this.logCtx('health_check', 'health'),
        errorMessageExtractor: this.gismeteoErrorExtractor,
      });
      return this.health('ok', `Connected to Gismeteo API (HTTP ${res.status})`, res.status);
    } catch (err) {
      return this.health('error', err instanceof Error ? err.message : String(err));
    }
  }

  async executeTool(toolName: string, input: unknown, _toolConfig: ProviderToolConfig): Promise<unknown> {
    this.requireToken();
    switch (toolName) {
      case 'gismeteo_current':
        return this.current(input);
      case 'gismeteo_forecast':
        return this.forecast(input);
      case 'gismeteo_search_city':
        return this.searchCity(input);
      default:
        throw userError(`Unknown tool: ${toolName}`, 'UNKNOWN_TOOL');
    }
  }

  // ------------------------------------------------------------ implementation

  private async current(input: unknown): Promise<Record<string, unknown>> {
    const args = this.parse(currentInputSchema, input);
    const res = await this.http.get<GismeteoEnvelope<GismeteoWeather>>(this.weatherUrl('current', args), {
      query: this.langParams(args),
      headers: this.apiHeaders(),
      timeoutMs: this.getTimeoutMs(),
      log: this.logCtx('gismeteo_current'),
      errorMessageExtractor: this.gismeteoErrorExtractor,
    });
    return this.mapCurrent(res.data.response as GismeteoWeather);
  }

  private async forecast(input: unknown): Promise<Record<string, unknown>> {
    const args = this.parse(forecastInputSchema, input);
    const res = await this.http.get<GismeteoEnvelope<GismeteoAggregated[]>>(this.weatherUrl('forecast/aggregate', args), {
      query: { days: args.days ?? 3, lang: args.lang ?? 'ru' },
      headers: this.apiHeaders(),
      timeoutMs: this.getTimeoutMs(),
      log: this.logCtx('gismeteo_forecast'),
      errorMessageExtractor: this.gismeteoErrorExtractor,
    });
    const list = asArray<GismeteoAggregated>(res.data.response as unknown);
    return {
      days: list.map((day) => this.mapForecastDay(day)),
    };
  }

  private async searchCity(input: unknown): Promise<Record<string, unknown>> {
    const args = this.parse(searchCitySchema, input);
    const query: Record<string, string | number> = { lang: args.lang ?? 'ru' };
    if (args.query !== undefined) query.query = args.query;
    if (args.latitude !== undefined && args.longitude !== undefined) {
      query.latitude = args.latitude;
      query.longitude = args.longitude;
      query.limit = args.limit ?? 10;
    }
    const res = await this.http.get<GismeteoEnvelope<GismeteoLocation[]>>(this.url('/v2/search/cities/'), {
      query,
      headers: this.apiHeaders(),
      timeoutMs: this.getTimeoutMs(),
      log: this.logCtx('gismeteo_search_city'),
      errorMessageExtractor: this.gismeteoErrorExtractor,
    });
    const items = asArray<GismeteoLocation>(res.data.response as unknown).map((loc) => ({
      id: loc.id ?? null,
      name: loc.name ?? null,
      namePrepositional: loc.nameP ?? null,
      kind: loc.kind ?? null,
      kindLabel: loc.kind ? cityKindLabel(loc.kind) : null,
      countryCode: loc.country?.code ?? null,
      countryName: loc.country?.name ?? null,
      districtName: loc.district?.name ?? null,
      url: loc.url ?? null,
    }));
    return { query: args.query ?? `${args.latitude},${args.longitude}`, count: items.length, items };
  }

  // ------------------------------------------------------------ transform

  private mapCurrent(w: GismeteoWeather | undefined): Record<string, unknown> {
    const weather = w ?? {};
    return {
      cityId: weather.city ?? null,
      kind: weather.kind ?? null,
      observedAtUtc: (weather.date as Record<string, unknown> | undefined)?.UTC ?? null,
      observedAtLocal: (weather.date as Record<string, unknown> | undefined)?.local ?? null,
      temperatureC: numOrNull(weather.temperature?.air?.C),
      feelsLikeC: numOrNull(weather.temperature?.comfort?.C),
      waterTemperatureC: numOrNull(weather.temperature?.water?.C),
      description: weather.description?.full ?? null,
      humidityPct: weather.humidity?.percent ?? null,
      pressureMmHg: weather.pressure?.mm_hg_atm ?? null,
      pressureHPa: weather.pressure?.h_pa ?? null,
      cloudinessPct: weather.cloudiness?.percent ?? null,
      cloudiness: cloudinessLabel(weather.cloudiness?.type),
      stormRisk: weather.storm ?? null,
      phenomenon: weather.phenomenon ?? null,
      precipitation: {
        type: weather.precipitation?.type ?? null,
        typeLabel: precipitationTypeLabel(weather.precipitation?.type),
        amountMm: weather.precipitation?.amount ?? null,
        intensityLabel: precipitationTypeLabelIntensity(weather.precipitation?.intensity),
      },
      wind: {
        directionDeg: weather.wind?.direction?.degree ?? null,
        direction: windDirectionLabel(weather.wind?.direction?.scale_8),
        speedKmh: weather.wind?.speed?.km_h ?? null,
        speedMs: weather.wind?.speed?.m_s ?? null,
      },
      uvbIndex: weather.radiation?.UVB ?? weather.radiation?.uvb_index ?? null,
      icon: weather.icon ?? null,
    };
  }

  private mapForecastDay(day: GismeteoAggregated | undefined): Record<string, unknown> {
    const d = day ?? {};
    return {
      dateUtc: (d.date as Record<string, unknown> | undefined)?.UTC ?? null,
      dateLocal: (d.date as Record<string, unknown> | undefined)?.local ?? null,
      description: d.description?.full ?? null,
      temperatureC: {
        min: numOrNull(d.temperature?.air?.min?.C),
        max: numOrNull(d.temperature?.air?.max?.C),
        avg: numOrNull(d.temperature?.air?.avg?.C),
      },
      humidityPct: {
        min: d.humidity?.percent?.min ?? null,
        max: d.humidity?.percent?.max ?? null,
        avg: d.humidity?.percent?.avg ?? null,
      },
      pressureMmHg: {
        min: d.pressure?.mm_hg_atm?.min ?? null,
        max: d.pressure?.mm_hg_atm?.max ?? null,
      },
      precipitation: {
        typeLabel: precipitationTypeLabel(d.precipitation?.type),
        amountMm: d.precipitation?.amount ?? null,
      },
      windSpeedKmh: {
        min: d.wind?.speed?.min?.km_h ?? null,
        max: d.wind?.speed?.max?.km_h ?? null,
        avg: d.wind?.speed?.avg?.km_h ?? null,
      },
      uvbIndexMax: d.radiation?.max ?? d.radiation?.max_index ?? null,
    };
  }

  // ------------------------------------------------------------ helpers

  /** URL для weather/current или weather/forecast/aggregate: по id города или координатам. */
  private weatherUrl(
    kind: 'current' | 'forecast/aggregate',
    args: { cityId?: number; latitude?: number; longitude?: number },
  ): string {
    if (args.cityId !== undefined) {
      return this.url(`/v2/weather/${kind}/${args.cityId}/`);
    }
    return this.url(`/v2/weather/${kind}/`);
  }

  private langParams(args: { lang?: (typeof LANGS)[number] }): Record<string, string> {
    return { lang: args.lang ?? 'ru' };
  }

  private parse<T>(schema: z.ZodType<T>, input: unknown): T {
    const result = schema.safeParse(input);
    if (!result.success) {
      const issues = result.error.issues.map((i) => `${i.path.join('.') || 'input'}: ${i.message}`).join('; ');
      throw userError(`Invalid input: ${issues}`, 'INVALID_TOOL_INPUT', result.error.issues);
    }
    return result.data;
  }
}

function precipitationTypeLabelIntensity(intensity: unknown): string | null {
  if (intensity === undefined || intensity === null) return null;
  const t = Number(intensity);
  const labels: Record<number, string> = { 0: 'Нет осадков', 1: 'Небольшие', 2: 'Умеренные', 3: 'Сильные' };
  return Number.isInteger(t) && labels[t] ? labels[t] : String(intensity);
}

function asArray<T>(value: unknown): T[] {
  if (Array.isArray(value)) return value as T[];
  if (value && typeof value === 'object') {
    const candidate = (value as Record<string, unknown>).items;
    if (Array.isArray(candidate)) return candidate as T[];
  }
  return [];
}

function numOrNull(value: unknown): number | null {
  if (value === undefined || value === null) return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}