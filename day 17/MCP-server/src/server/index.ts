import path from 'node:path';
import { buildRuntime } from './runtime.js';
import { buildApp } from './app.js';
import { APP_NAME, APP_VERSION } from '../core/version.js';

/**
 * Точка входа MCP Gateway (HTTP): REST API + Web UI + MCP endpoint http://127.0.0.1:3000/mcp.
 */
async function main(): Promise<void> {
  const runtime = await buildRuntime();
  const webDistDir = process.env.MCP_WEB_DIST ?? path.resolve(process.cwd(), 'web', 'dist');
  const app = await buildApp(runtime, webDistDir);

  const shutdown = async (signal: string): Promise<void> => {
    runtime.logger.info(`[server] shutting down (${signal})`);
    try {
      await app.close();
    } finally {
      await runtime.registry.disposeAll();
      process.exit(0);
    }
  };
  process.on('SIGINT', () => void shutdown('SIGINT'));
  process.on('SIGTERM', () => void shutdown('SIGTERM'));

  app.addHook('onClose', async () => {
    await runtime.registry.disposeAll();
  });

  const { host, port } = runtime.settings;
  await app.listen({ host, port });

  const displayHost = host === '0.0.0.0' || host === '::' ? '127.0.0.1' : host;
  const providers = runtime.registry.getProviderIds().join(', ');
  const tools = runtime.registry.getMcpTools().length;
  runtime.logger.info(`${APP_NAME} v${APP_VERSION} is running`);
  runtime.logger.info(`  Web UI:       http://${displayHost}:${port}`);
  runtime.logger.info(`  MCP endpoint: http://${displayHost}:${port}/mcp`);
  runtime.logger.info(`  Providers:    ${providers || '(none)'} (${tools} enabled MCP tools)`);
}

main().catch((err) => {
  // eslint-disable-next-line no-console
  console.error(`[server] fatal: ${err instanceof Error ? err.message : String(err)}`);
  process.exit(1);
});