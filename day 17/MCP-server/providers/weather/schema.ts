import { z } from 'zod';
import type { ConfigSchema, ToolInputSchema } from '../../src/core/providers/types.js';

export const WEATHER_BASE_URL = 'https://api.open-meteo.com';

export const WEATHER_CONFIG_SCHEMA: ConfigSchema = {
  fields: [
    {
      key: 'baseUrl',
      label: 'Base URL',
      type: 'string',
      required: true,
      default: WEATHER_BASE_URL,
      description: 'Базовый URL Open-Meteo API.',
    },
  ],
  settingsFields: [
    { key: 'timeout', label: 'Timeout', type: 'number', unit: 'ms', default: 10000, description: 'Таймаут HTTP-запроса.' },
  ],
  credentialFields: [],
};

// ------------------------------------------------------------- входные схемы

export const currentInputSchema = z.object({
  latitude: z.number().min(-90).max(90),
  longitude: z.number().min(-180).max(180),
  timezone: z.string().optional(),
});

export const forecastInputSchema = z.object({
  latitude: z.number().min(-90).max(90),
  longitude: z.number().min(-180).max(180),
  days: z.number().int().min(1).max(16).optional(),
  timezone: z.string().optional(),
});

// ------------------------------------------------------- JSON Schema для MCP

export const JSON_SCHEMA_PROP = (description: string, type: string, extra: Record<string, unknown> = {}): Record<string, unknown> => ({
  type,
  description,
  ...extra,
});

export const currentToolSchema: ToolInputSchema = {
  type: 'object',
  properties: {
    latitude: JSON_SCHEMA_PROP('Широта (например, 52.52)', 'number'),
    longitude: JSON_SCHEMA_PROP('Долгота (например, 13.405)', 'number'),
    timezone: JSON_SCHEMA_PROP('IANA-таймзона, например Europe/Berlin (по умолчанию auto)', 'string'),
  },
  required: ['latitude', 'longitude'],
  additionalProperties: false,
};

export const forecastToolSchema: ToolInputSchema = {
  type: 'object',
  properties: {
    latitude: JSON_SCHEMA_PROP('Широта (например, 52.52)', 'number'),
    longitude: JSON_SCHEMA_PROP('Долгота (например, 13.405)', 'number'),
    days: JSON_SCHEMA_PROP('Количество дней прогноза, 1–16 (по умолчанию 3)', 'number'),
    timezone: JSON_SCHEMA_PROP('IANA-таймзона, например Europe/Berlin (по умолчанию auto)', 'string'),
  },
  required: ['latitude', 'longitude'],
  additionalProperties: false,
};

// ------------------------------------------------------------- WMO-коды

export const WMO_DESCRIPTIONS: Record<number, string> = {
  0: 'Clear sky',
  1: 'Mainly clear',
  2: 'Partly cloudy',
  3: 'Overcast',
  45: 'Fog',
  48: 'Depositing rime fog',
  51: 'Light drizzle',
  53: 'Moderate drizzle',
  55: 'Dense drizzle',
  56: 'Light freezing drizzle',
  57: 'Dense freezing drizzle',
  61: 'Slight rain',
  63: 'Moderate rain',
  65: 'Heavy rain',
  66: 'Light freezing rain',
  67: 'Heavy freezing rain',
  71: 'Slight snow fall',
  73: 'Moderate snow fall',
  75: 'Heavy snow fall',
  77: 'Snow grains',
  80: 'Slight rain showers',
  81: 'Moderate rain showers',
  82: 'Violent rain showers',
  85: 'Slight snow showers',
  86: 'Heavy snow showers',
  95: 'Thunderstorm',
  96: 'Thunderstorm with slight hail',
  99: 'Thunderstorm with heavy hail',
};

export const weatherCodeDescription = (code: number): string => WMO_DESCRIPTIONS[code] ?? `Weather code ${code}`;