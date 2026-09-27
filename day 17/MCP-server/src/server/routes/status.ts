import type { FastifyInstance } from 'fastify';
import type { Runtime } from '../runtime.js';
import { APP_NAME, APP_VERSION } from '../../core/version.js';
import { userError } from '../../core/errors.js';
import { formatZodMessage, serverSettingsUpdateSchema } from '../validation.js';

/** Статус сервера и статистика для Dashboard. */
export function registerStatusRoutes(app: FastifyInstance, runtime: Runtime): void {
  const { settings } = runtime;

  app.get('/api/health', async () => ({
    ok: true,
    name: APP_NAME,
    version: APP_VERSION,
    uptimeSeconds: Math.round((Date.now() - runtime.startedAt) / 1000),
  }));

  app.get('/api/server/status', async () => {
    const stats = await runtime.requestLogger.stats();
    const providers = runtime.registry.getRuntimeState();
    const enabledProviders = providers.filter((p) => p.enabled).length;
    const tools = runtime.registry.getTools();
    const enabledTools = tools.filter((t) => t.enabled).length;
    return {
      ok: true,
      name: APP_NAME,
      version: APP_VERSION,
      running: true,
      host: settings.host,
      port: settings.port,
      mcpEndpoint: displayUrl(settings.host, settings.port, '/mcp'),
      webUi: displayUrl(settings.host, settings.port, '/'),
      uptimeSeconds: Math.round((Date.now() - runtime.startedAt) / 1000),
      providers: { total: providers.length, enabled: enabledProviders, disabled: providers.length - enabledProviders },
      tools: { total: tools.length, enabled: enabledTools },
      requests: {
        today: stats.today,
        errorsToday: stats.errorsToday,
        avgLatencyMs: stats.avgLatencyMs,
      },
      lastRequests: stats.last,
    };
  });

  app.get('/api/server/settings', async () => settings);

  app.put('/api/server/settings', async (request, reply) => {
    const parsed = serverSettingsUpdateSchema.safeParse(request.body);
    if (!parsed.success) {
      throw userError(`Invalid settings: ${formatZodMessage(parsed.error)}`, 'INVALID_REQUEST');
    }
    const patch = parsed.data;
    const previous = { ...settings };
    const saved = runtime.configManager.saveServerConfig(patch);
    // Живые настройки без перезапуска
    runtime.settings = saved;
    runtime.logger.setLevel(saved.logLevel);
    runtime.requestLogger.setSettings({
      maxResponseLogSize: saved.maxResponseLogSize,
      retentionDays: saved.logRetentionDays,
    });
    const restartRequired = (['host', 'port'] as const).filter((k) => saved[k] !== previous[k]);
    return { ...saved, restartRequired };
  });
}

/** Хост вида 0.0.0.0 / :: для отображения заменяем на 127.0.0.1. */
function displayUrl(host: string, port: number, path: string): string {
  const display = host === '0.0.0.0' || host === '::' || host === '' ? '127.0.0.1' : host;
  const needsBrackets = display.includes(':') && !display.startsWith('[');
  return `http://${needsBrackets ? `[${display}]` : display}:${port}${path}`;
}