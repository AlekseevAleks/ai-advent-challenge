import { WeatherProvider } from './weather/provider.js';
import { GitHubProvider } from './github/provider.js';
import { GismeteoProvider } from './gismeteo/provider.js';

/**
 * Список встроенных провайдеров. Добавление нового API:
 *   1. создайте папку providers/my_api/ (provider.ts, tools.ts, schema.ts);
 *   2. импортируйте класс и добавьте его в этот массив — больше ничего не нужно.
 * Registry сам создаст дефолтный конфиг, зарегистрирует tools в MCP и покажет
 * провайдера в Web UI / REST API.
 *
 * Для будущих внешних plugins (slack, notion, jira, ...) интерфейс тот же:
 * registry.registerProviderClass(Класс) — регистрация возможна в рантайме.
 */
export const BUILTIN_PROVIDERS = [WeatherProvider, GitHubProvider, GismeteoProvider] as const;