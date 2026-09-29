import type { ToolDefinition } from '../../src/core/providers/types.js';
import { currentToolSchema, forecastToolSchema } from './schema.js';

export const WEATHER_TOOLS: ToolDefinition[] = [
  {
    name: 'weather_current',
    description: 'Текущая погода (температура, влажность, ветер, осадки) для заданных координат через Open-Meteo.',
    inputSchema: currentToolSchema,
  },
  {
    name: 'weather_forecast',
    description: 'Прогноз погоды на несколько дней (макс./мин. температура, осадки, ветер, восход/закат) для заданных координат через Open-Meteo.',
    inputSchema: forecastToolSchema,
  },
];