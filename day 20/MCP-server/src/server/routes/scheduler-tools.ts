import type { FastifyInstance } from 'fastify';
import { z } from 'zod';
import { userError } from '../../core/errors.js';
import type { Runtime } from '../runtime.js';

/** PUT /api/scheduler-tools/:toolId — включение/выключение scheduler tool. */
const schedulerToolUpdateSchema = z.object({ enabled: z.boolean() }).strict();

function jsonError(code: string, message: string): { error: { code: string; message: string } } {
  return { error: { code, message } };
}

/**
 * REST API настройки scheduler tools (тулы, которые работают с задачами).
 * Включение/выключение персистентно в config/scheduler-tools.json;
 * отключённые тулы не объявляются MCP-клиенту и не вызываются.
 */
export function registerSchedulerToolsRoutes(app: FastifyInstance, runtime: Runtime): void {
  const { gateway } = runtime;

  app.get('/api/scheduler-tools', async () => {
    const items = gateway.listSchedulerToolsState();
    return { items, total: items.length };
  });

  app.put<{ Params: { toolId: string } }>('/api/scheduler-tools/:toolId', async (request, reply) => {
    const parsed = schedulerToolUpdateSchema.safeParse(request.body);
    if (!parsed.success) {
      throw userError('Invalid scheduler tool update: body must be {"enabled": boolean}', 'INVALID_REQUEST');
    }
    try {
      gateway.setSchedulerToolEnabled(request.params.toolId, parsed.data.enabled);
    } catch (err) {
      if (err instanceof Error && 'code' in err && (err as { code: string }).code === 'UNKNOWN_TOOL') {
        return reply.code(404).send(jsonError('NOT_FOUND', `Scheduler tool "${request.params.toolId}" not found`));
      }
      throw err;
    }
    const item = gateway.listSchedulerToolsState().find((t) => t.name === request.params.toolId);
    return item ?? jsonError('NOT_FOUND', `Scheduler tool "${request.params.toolId}" not found`);
  });
}