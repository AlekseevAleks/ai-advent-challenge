import type { FastifyInstance } from 'fastify';
import { z } from 'zod';
import { userError } from '../../core/errors.js';
import type { Runtime } from '../runtime.js';

/** PUT /api/pipeline-tools/:toolId — включение/выключение pipeline tool. */
const pipelineToolUpdateSchema = z.object({ enabled: z.boolean() }).strict();

function jsonError(code: string, message: string): { error: { code: string; message: string } } {
  return { error: { code, message } };
}

/**
 * REST API настройки pipeline tools (тулы, которые работают с пайплайнами:
 * run_pipeline, list_pipelines, delete_pipeline). Отключённые тулы не объявляются
 * MCP-клиенту и не вызываются; настройка персистентна в config/pipeline-tools.json.
 */
export function registerPipelineToolsRoutes(app: FastifyInstance, runtime: Runtime): void {
  const { gateway } = runtime;

  app.get('/api/pipeline-tools', async () => {
    const items = gateway.listPipelineToolsState();
    return { items, total: items.length };
  });

  app.put<{ Params: { toolId: string } }>('/api/pipeline-tools/:toolId', async (request, reply) => {
    const parsed = pipelineToolUpdateSchema.safeParse(request.body);
    if (!parsed.success) {
      throw userError('Invalid pipeline tool update: body must be {"enabled": boolean}', 'INVALID_REQUEST');
    }
    try {
      gateway.setPipelineToolEnabled(request.params.toolId, parsed.data.enabled);
    } catch (err) {
      if (err instanceof Error && 'code' in err && (err as { code: string }).code === 'UNKNOWN_TOOL') {
        return reply.code(404).send(jsonError('NOT_FOUND', `Pipeline tool "${request.params.toolId}" not found`));
      }
      throw err;
    }
    const item = gateway.listPipelineToolsState().find((t) => t.name === request.params.toolId);
    return item ?? jsonError('NOT_FOUND', `Pipeline tool "${request.params.toolId}" not found`);
  });
}