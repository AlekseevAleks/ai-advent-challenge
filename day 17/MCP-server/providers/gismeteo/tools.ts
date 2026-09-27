import type { ToolDefinition } from '../../src/core/providers/types.js';
import { currentToolSchema, forecastToolSchema, searchCityToolSchema } from './schema.js';

export const GISMETEO_TOOLS: ToolDefinition[] = [
  {
    name: 'gismeteo_current',
    description:
      'Текущая погода по Gismeteo: температура, ощущается как, влажность, давление, ветер, облачность, осадки, УФ-индекс. Требуется cityId или координаты, а также API token провайдера.',
    inputSchema: currentToolSchema,
  },
  {
    name: 'gismeteo_forecast',
    description:
      'Прогноз погоды по Gismeteo на 3–10 дней (суточное агрегирование): мин./макс./средняя температура, влажность, давление, осадки, ветер. Требуется cityId или координаты и API token провайдера.',
    inputSchema: forecastToolSchema,
  },
  {
    name: 'gismeteo_search_city',
    description:
      'Поиск населённого пункта Gismeteo по названию или координатам. Возвращает id города для gismeteo_current/gismeteo_forecast. Требуется API token провайдера.',
    inputSchema: searchCityToolSchema,
  },
];