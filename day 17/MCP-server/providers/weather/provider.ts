import { z } from 'zod';
import type { ProviderConfig, ProviderToolConfig } from '../../src/core/types.js';
import type { ProviderHealth, ToolDefinition } from '../../src/core/providers/types.js';
import { BaseProvider } from '../../src/core/providers/base-provider.js';
import { userError } from '../../src/core/errors.js';
import { WEATHER_TOOLS } from './tools.js';
import {
  currentInputSchema,
  forecastInputSchema,
  WEATHER_CONFIG_SCHEMA,
  WEATHER_BASE_URL,
  weatherCodeDescription,
} from './schema.js';

interface OpenMeteoCurrent {
  current?: Record<string, unknown>;
  current_units?: Record<string, string>;
  latitude?: number;
  longitude?: number;
  timezone?: string;
  elevation?: number;
}

interface OpenMeteoDaily {
  daily?: {
    time?: string[];
    weather_code?: number[];
    temperature_2m_max?: number[];
    temperature_2m_min?: number[];
    precipitation_sum?: number[];
    wind_speed_10m_max?: number[];
    sunrise?: string[];
    sunset?: string[];
  };
}

/**
 * Weather Provider: Open-Meteo (без API key).
 * Демонстрирует минимальный провайдер: схема конфигурации, tools, валидация,
 * HTTP-запрос через общий HttpClient и преобразование ответа.
 */
export class WeatherProvider extends BaseProvider {
  constructor(http: ConstructorParameters<typeof BaseProvider>[0]['http']) {
    super({
      id: 'weather',
      name: 'Open-Meteo',
      description: 'Open-Meteo weather data (no API key required). Tools: weather_current, weather_forecast.',
      version: '1.0.0',
      http,
      defaultBaseUrl: WEATHER_BASE_URL,
    });
  }

  override getConfigSchema() {
    return WEATHER_CONFIG_SCHEMA;
  }

  override getDefaultConfig(): ProviderConfig {
    return {
      id: this.id,
      enabled: true,
      name: this.name,
      baseUrl: this.defaultBaseUrl ?? WEATHER_BASE_URL,
      credentials: {},
      settings: { timeout: 10000 },
    };
  }

  getTools(): ToolDefinition[] {
    return WEATHER_TOOLS;
  }

  async healthCheck(): Promise<ProviderHealth> {
    try {
      const res = await this.http.get<OpenMeteoCurrent>(this.tryUrl('/v1/forecast'), {
        query: { latitude: 52.52, longitude: 13.405, current: 'temperature_2m,weather_code', timezone: 'auto' },
        timeoutMs: this.getTimeoutMs(),
        log: { provider: this.id, providerName: this.name, direction: 'health' },
      });
      return this.health('ok', `Connected to Open-Meteo API (HTTP ${res.status})`, res.status);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      return this.health('error', message);
    }
  }

  override validateConfig(): void {
    super.validateConfig();
    const timeout = this.settings.timeout;
    if (timeout !== undefined && (typeof timeout !== 'number' || timeout <= 0)) {
      throw userError('weather: settings.timeout must be a positive number', 'INVALID_SETTINGS');
    }
  }

  async executeTool(toolName: string, input: unknown, _toolConfig: ProviderToolConfig): Promise<unknown> {
    switch (toolName) {
      case 'weather_current':
        return this.current(input);
      case 'weather_forecast':
        return this.forecast(input);
      default:
        throw userError(`Unknown tool: ${toolName}`, 'UNKNOWN_TOOL');
    }
  }

  private async current(input: unknown): Promise<Record<string, unknown>> {
    const args = this.parse(currentInputSchema, input);
    const res = await this.http.get<OpenMeteoCurrent>(this.url('/v1/forecast'), {
      query: {
        latitude: args.latitude,
        longitude: args.longitude,
        current:
          'temperature_2m,relative_humidity_2m,apparent_temperature,is_day,precipitation,weather_code,wind_speed_10m,wind_direction_10m',
        timezone: args.timezone ?? 'auto',
      },
      timeoutMs: this.getTimeoutMs(),
      log: { provider: this.id, providerName: this.name, tool: 'weather_current', direction: 'mcp' },
    });

    const data = res.data;
    const current = data.current ?? {};
    const weatherCode = Number(current.weather_code);
    return {
      location: {
        latitude: data.latitude ?? args.latitude,
        longitude: data.longitude ?? args.longitude,
        timezone: data.timezone ?? args.timezone ?? 'auto',
        elevationMeters: data.elevation ?? null,
      },
      observationTime: current.time ?? null,
      weather: {
        code: weatherCode,
        description: Number.isFinite(weatherCode) ? weatherCodeDescription(weatherCode) : null,
        temperatureC: current.temperature_2m ?? null,
        apparentTemperatureC: current.apparent_temperature ?? null,
        relativeHumidityPct: current.relative_humidity_2m ?? null,
        precipitationMm: current.precipitation ?? null,
        windSpeedKmh: current.wind_speed_10m ?? null,
        windDirectionDeg: current.wind_direction_10m ?? null,
        isDay: current.is_day === 1,
      },
      units: {
        temperature: (data.current_units ?? {})?.temperature_2m ?? '°C',
        windSpeed: (data.current_units ?? {})?.wind_speed_10m ?? 'km/h',
        precipitation: (data.current_units ?? {})?.precipitation ?? 'mm',
      },
    };
  }

  private async forecast(input: unknown): Promise<Record<string, unknown>> {
    const args = this.parse(forecastInputSchema, input);
    const days = args.days ?? 3;
    const res = await this.http.get<OpenMeteoCurrent & OpenMeteoDaily>(this.url('/v1/forecast'), {
      query: {
        latitude: args.latitude,
        longitude: args.longitude,
        daily: 'weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max,sunrise,sunset',
        timezone: args.timezone ?? 'auto',
        forecast_days: days,
      },
      timeoutMs: this.getTimeoutMs(),
      log: { provider: this.id, providerName: this.name, tool: 'weather_forecast', direction: 'mcp' },
    });

    const data = res.data;
    const daily = data.daily ?? {};
    const times = daily.time ?? [];
    const daysOut = times.map((date, i) => {
      const code = daily.weather_code?.[i] ?? -1;
      return {
        date,
        weatherCode: code,
        description: code >= 0 ? weatherCodeDescription(code) : null,
        temperatureMaxC: daily.temperature_2m_max?.[i] ?? null,
        temperatureMinC: daily.temperature_2m_min?.[i] ?? null,
        precipitationSumMm: daily.precipitation_sum?.[i] ?? null,
        windSpeedMaxKmh: daily.wind_speed_10m_max?.[i] ?? null,
        sunrise: daily.sunrise?.[i] ?? null,
        sunset: daily.sunset?.[i] ?? null,
      };
    });

    return {
      location: {
        latitude: data.latitude ?? args.latitude,
        longitude: data.longitude ?? args.longitude,
        timezone: data.timezone ?? args.timezone ?? 'auto',
      },
      requestedDays: days,
      forecast: daysOut,
    };
  }

  private parse<T>(schema: z.ZodType<T>, input: unknown): T {
    const result = schema.safeParse(input);
    if (!result.success) {
      const issues = result.error.issues.map((i) => `${i.path.join('.') || 'input'}: ${i.message}`).join('; ');
      throw userError(`Invalid input: ${issues}`, 'INVALID_TOOL_INPUT', result.error.issues);
    }
    return result.data;
  }

  /** url(), но не бросает при отсутствии baseUrl — health check до инициализации. */
  private tryUrl(path: string): string {
    try {
      return this.url(path);
    } catch {
      return `${WEATHER_BASE_URL}${path}`;
    }
  }
}