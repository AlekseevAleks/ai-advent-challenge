import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { buildRuntime } from './runtime.js';

/**
 * MCP Gateway по stdio-транспорту (для Claude Desktop и других MCP-клиентов,
 * поддерживающих stdio-подключение к локальному процессу).
 *
 * Запуск: npm run mcp-stdio  (или node dist/src/server/mcp-stdio.js после сборки)
 */
async function main(): Promise<void> {
  const runtime = await buildRuntime({ consoleOutput: false });
  const transport = new StdioServerTransport();
  const server = runtime.gateway.createSessionServer();
  await server.connect(transport);
  // Scheduler продолжает работать, пока живой процесс stdio
  runtime.scheduler.start();
  process.on('exit', () => runtime.taskStorage.close());
  runtime.logger.info(
    `[mcp] stdio server started (${runtime.registry.getMcpTools().length} provider tools + ${runtime.gateway.getSchedulerToolCount()} scheduler tools)`,
  );
}

main().catch((err) => {
  // stdout занят протоколом MCP — пишем только в stderr
  process.stderr.write(`[mcp-stdio] fatal: ${err instanceof Error ? err.message : String(err)}\n`);
  process.exit(1);
});