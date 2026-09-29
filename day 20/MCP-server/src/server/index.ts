import path from 'node:path';
import { buildRuntime } from './runtime.js';
import { buildApp } from './app.js';
import { APP_NAME, APP_VERSION } from '../core/version.js';

/**
 * Точка входа MCP Gateway (HTTP): REST API + Web UI + MCP endpoint http://127.0.0.1:3000/mcp.
 * Порт можно передать аргументом: `npm start -- 4000` (по умолчанию 3000 из config/server.json).
 */
function parseCliPort(argv: string[]): number | undefined {
  const raw = argv[2];
  if (raw === undefined || raw === '') return undefined;
  const n = Number(raw);
  if (Number.isInteger(n) && n >= 1 && n <= 65535) return n;
  return undefined; // невалидный аргумент игнорируем — используется порт из конфигурации
}

async function main(): Promise<void> {
  const runtime = await buildRuntime();
  const webDistDir = process.env.MCP_WEB_DIST ?? path.resolve(process.cwd(), 'web', 'dist');

  // CLI-аргумент порта имеет приоритет над config/server.json и env (MCP_PORT)
  const cliPort = parseCliPort(process.argv);
  if (cliPort !== undefined) {
    runtime.settings.port = cliPort;
  }

  const app = await buildApp(runtime, webDistDir);

  const shutdown = async (signal: string): Promise<void> => {
    runtime.logger.info(`[server] shutting down (${signal})`);
    try {
      await runtime.scheduler.stop(); // больше никаких новых запусков, дожидаемся текущего
      await app.close();
    } finally {
      await runtime.registry.disposeAll();
      runtime.taskStorage.close();
      process.exit(0);
    }
  };
  process.on('SIGINT', () => void shutdown('SIGINT'));
  process.on('SIGTERM', () => void shutdown('SIGTERM'));

  app.addHook('onClose', async () => {
    await runtime.scheduler.stop();
    await runtime.registry.disposeAll();
    runtime.taskStorage.close();
  });

  const { host, port } = runtime.settings;
  await app.listen({ host, port });

  // Scheduler стартует вместе с сервером
  runtime.scheduler.start();

  const displayHost = host === '0.0.0.0' || host === '::' ? '127.0.0.1' : host;
  const providers = runtime.registry.getProviderIds().join(', ');
  const tools = runtime.registry.getMcpTools().length;
  const schedulerTools = runtime.gateway.getSchedulerToolCount();
  runtime.logger.info(`${APP_NAME} v${APP_VERSION} is running`);
  runtime.logger.info(`  Web UI:       http://${displayHost}:${port}`);
  runtime.logger.info(`  MCP endpoint: http://${displayHost}:${port}/mcp`);
  runtime.logger.info(`  Providers:    ${providers || '(none)'} (${tools} provider tools + ${schedulerTools} scheduler tools)`);
}

main().catch((err) => {
  // eslint-disable-next-line no-console
  console.error(`[server] fatal: ${err instanceof Error ? err.message : String(err)}`);
  process.exit(1);
});