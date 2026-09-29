import type { FastifyInstance } from 'fastify';
import { userError } from '../../core/errors.js';
import type { Runtime } from '../runtime.js';
import { clearLogsSchema, formatZodMessage, logsQuerySchema } from '../validation.js';

function jsonError(code: string, message: string): { error: { code: string; message: string } } {
  return { error: { code, message } };
}

/** REST API логов запросов MCP → API (JSONL-файлы, секреты уже удалены при записи). */
export function registerLogsRoutes(app: FastifyInstance, runtime: Runtime): void {
  const { requestLogger } = runtime;

  app.get('/api/logs', async (request) => {
    const parsed = logsQuerySchema.safeParse(request.query);
    if (!parsed.success) {
      throw userError(`Invalid log query: ${formatZodMessage(parsed.error)}`, 'INVALID_REQUEST');
    }
    const { search, provider, tool, status, result, from, to, offset, limit } = parsed.data;
    return requestLogger.list({ search, provider, tool, status, result, from, to, offset, limit });
  });

  app.get<{ Params: { id: string } }>('/api/logs/:id', async (request, reply) => {
    const entry = await requestLogger.get(request.params.id);
    if (!entry) return reply.code(404).send(jsonError('NOT_FOUND', 'Log entry not found'));
    return entry;
  });

  app.delete('/api/logs', async (request, reply) => {
    const parsed = clearLogsSchema.safeParse(request.body);
    if (!parsed.success) {
      throw userError('To clear logs, send {"confirm": true}', 'CONFIRMATION_REQUIRED');
    }
    const deleted = await requestLogger.clear();
    return { deleted, message: `Deleted ${deleted} log file(s)` };
  });
}