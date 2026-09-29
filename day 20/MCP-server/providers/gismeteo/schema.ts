import { z } from 'zod';
import type { ConfigSchema, ToolInputSchema } from '../../src/core/providers/types.js';

export const GISMETEO_BASE_URL = 'https://api.gismeteo.net';
export const GISMETEO_TOKEN_ENV = 'GISMETEO_TOKEN';

export const GISMETEO_LANGS = ['ru', 'en', 'ua', 'lt', 'lv', 'pl', 'ro'] as const;

export const GISMETEO_CONFIG_SCHEMA: ConfigSchema = {
  fields: [
    {
      key: 'baseUrl',
      label: 'Base URL',
      type: 'string',
      required: true,
      default: GISMETEO_BASE_URL,
      description: 'Базовый URL Gismeteo Weather Forecast API v2.',
    },
  ],
  settingsFields: [
    { key: 'timeout', label: 'Timeout', type: 'number', unit: 'ms', default: 10000, description: 'Таймаут HTTP-запроса.' },
  ],
  credentialFields: [
    {
      key: 'token',
      label: 'API Token',
      type: 'string',
      secret: true,
      env: GISMETEO_TOKEN_ENV,
      placeholder: 'X-Gismeteo-Token',
      description:
        'Токен Gismeteo API (header X-Gismeteo-Token). Выдаётся по запросу https://docs.gismeteo.net — можно задать через env GISMETEO_TOKEN.',
    },
  ],
};

// ------------------------------------------------------------- входные схемы

const cityOrCoords = <T extends { cityId?: unknown; latitude?: unknown; longitude?: unknown }>(v: T, ctx: z.RefinementCtx) => {
  const hasCity = v.cityId !== undefined;
  const hasCoords = v.latitude !== undefined && v.longitude !== undefined;
  if (!hasCity && !hasCoords) {
    ctx.addIssue({ code: z.ZodIssueCode.custom, message: 'Provide either "cityId" or "latitude" and "longitude"' });
  }
  if (hasCoords && (v.latitude === undefined || v.longitude === undefined)) {
    ctx.addIssue({ code: z.ZodIssueCode.custom, message: '"latitude" and "longitude" must be set together' });
  }
};

const lang = z.enum(GISMETEO_LANGS).optional();

export const currentInputSchema = z
  .object({
    cityId: z.number().int().min(1).optional(),
    latitude: z.number().min(-90).max(90).optional(),
    longitude: z.number().min(-180).max(180).optional(),
    lang,
  })
  .superRefine(cityOrCoords);

export const forecastInputSchema = z
  .object({
    cityId: z.number().int().min(1).optional(),
    latitude: z.number().min(-90).max(90).optional(),
    longitude: z.number().min(-180).max(180).optional(),
    days: z.number().int().min(3).max(10).optional(),
    lang,
  })
  .superRefine(cityOrCoords);

export const searchCitySchema = z
  .object({
    query: z.string().min(1).max(100).optional(),
    latitude: z.number().min(-90).max(90).optional(),
    longitude: z.number().min(-180).max(180).optional(),
    limit: z.number().int().min(1).max(10).optional(),
    lang,
  })
  .superRefine((v, ctx) => {
    if (v.query === undefined && (v.latitude === undefined || v.longitude === undefined)) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, message: 'Provide either "query" or "latitude" and "longitude"' });
    }
  });

// ------------------------------------------------------- JSON Schema для MCP

const prop = (description: string, type: string, extra: Record<string, unknown> = {}): Record<string, unknown> => ({
  type,
  description,
  ...extra,
});

export const currentToolSchema: ToolInputSchema = {
  type: 'object',
  properties: {
    cityId: prop('ID населённого пункта (можно получить gismeteo_search_city), например 4368', 'number'),
    latitude: prop('Широта (например, 55.755798)', 'number'),
    longitude: prop('Долгота (например, 37.617599)', 'number'),
    lang: prop('Язык описания: ru (по умолчанию), en, ua, lt, lv, pl, ro', 'string'),
  },
  required: [],
  additionalProperties: false,
};

export const forecastToolSchema: ToolInputSchema = {
  type: 'object',
  properties: {
    cityId: prop('ID населённого пункта (например, 4368)', 'number'),
    latitude: prop('Широта (например, 55.755798)', 'number'),
    longitude: prop('Долгота (например, 37.617599)', 'number'),
    days: prop('Количество дней прогноза, 3–10 (по умолчанию 3)', 'number'),
    lang: prop('Язык описания: ru (по умолчанию), en, ua, lt, lv, pl, ro', 'string'),
  },
  required: [],
  additionalProperties: false,
};

export const searchCityToolSchema: ToolInputSchema = {
  type: 'object',
  properties: {
    query: prop('Название населённого пункта (например, Москва)', 'string'),
    latitude: prop('Широта для поиска по координатам', 'number'),
    longitude: prop('Долгота для поиска по координатам', 'number'),
    limit: prop('Лимит результатов по координатам, 1–10', 'number'),
    lang: prop('Язык: ru (по умолчанию), en, ua, lt, lv, pl, ro', 'string'),
  },
  required: [],
  additionalProperties: false,
};

// ------------------------------------------------------------- справочники

/** Типы осадков (Gismeteo Precipitation.type). */
export const PRECIPITATION_TYPES: Record<number, string> = {
  0: 'Нет осадков',
  1: 'Дождь',
  2: 'Снег',
  3: 'Смешанные осадки',
};

/** Интенсивность осадков (Gismeteo Precipitation.intensity). */
export const PRECIPITATION_INTENSITY: Record<number, string> = {
  0: 'Нет осадков',
  1: 'Небольшой',
  2: 'Умеренный',
  3: 'Сильный',
};

/** Облачность (Gismeteo Cloudiness.type): 0..3. */
export const CLOUDINESS_TYPES: Record<number, string> = {
  0: 'Ясно',
  1: 'Малооблачно',
  2: 'Облачно с прояснениями',
  3: 'Пасмурно',
};

/** Направление ветра по шкале 0..8 (0 — штиль, 1..8 — румбы от севера). */
export const WIND_DIRECTION_SCALE_8: Record<number, string> = {
  0: 'Штиль',
  1: 'Северный',
  2: 'Северо-восточный',
  3: 'Восточный',
  4: 'Юго-восточный',
  5: 'Южный',
  6: 'Юго-западный',
  7: 'Западный',
  8: 'Северо-западный',
};

export const CITY_KIND: Record<string, string> = {
  T: 'Город',
  C: 'Мегаполис',
  A: 'Аэропорт',
  M: 'Метеостанция',
};

export const cityKindLabel = (kind: string): string | null => CITY_KIND[kind] ?? null;

export const precipitationTypeLabel = (type: unknown): string => {
  const t = Number(type);
  return Number.isInteger(t) && PRECIPITATION_TYPES[t] ? PRECIPITATION_TYPES[t] : `Тип осадков ${type}`;
};

export const cloudinessLabel = (type: unknown): string => {
  const t = Number(type);
  return Number.isInteger(t) && CLOUDINESS_TYPES[t] ? CLOUDINESS_TYPES[t] : `Облачность (тип ${type})`;
};

export const windDirectionLabel = (scale: unknown): string => {
  const t = Number(scale);
  return Number.isInteger(t) && WIND_DIRECTION_SCALE_8[t] ? WIND_DIRECTION_SCALE_8[t] : `Румб ${scale}`;
};