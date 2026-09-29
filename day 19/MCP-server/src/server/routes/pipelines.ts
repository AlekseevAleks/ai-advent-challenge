import type { FastifyInstance } from 'fastify';
import { z } from 'zod';
import { userError } from '../../core/errors.js';
import type { PipelineInput } from '../../core/pipeline/types.js';
import type { Runtime } from '../runtime.js';

const stepSchema = z.object({
  id: z.string().min(1).max(100),
  tool: z.string().min(1).max(200),
  input: z.unknown().optional(),
});

const pipelineInputBodySchema = z
  .object({
    id: z.string().regex(/^[a-zA-Z0-9_-]{1,64}$/).optional(),
    name: z.string().min(1).max(120),
    description: z.string().max(500).optional(),
    enabled: z.boolean().optional(),
    steps: z.array(stepSchema).min(1),
  })
  .strict();

const runBodySchema = z.object({ input: z.record(z.string(), z.unknown()).optional() }).strict();

const historyQuerySchema = z.object({
  offset: z.coerce.number().int().min(0).default(0),
  limit: z.coerce.number().int().min(1).max(500).default(20),
});

function parsePipelineBody(body: unknown): PipelineInput {
  const parsed = pipelineInputBodySchema.safeParse(body ?? {});
  if (!parsed.success) {
    const msg = parsed.error.issues.map((i) => `${i.path.join('.') || 'body'}: ${i.message}`).join('; ');
    throw userError(`Invalid pipeline: ${msg}`, 'INVALID_PIPELINE');
  }
  return parsed.data as PipelineInput;
}

/**
 * REST API Pipelines. Поддерживает create/update/delete/run/history/execution-detail.
 * История не содержит output'ов и raw-входов (только статусы шагов и безопасные ошибки).
 */
export function registerPipelineRoutes(app: FastifyInstance, runtime: Runtime): void {
  const { pipelineRegistry, pipelineExecutor } = runtime;

  app.get('/api/pipelines', async () => {
    const items = pipelineRegistry.list();
    return { items, total: items.length };
  });

  app.get<{ Params: { id: string } }>('/api/pipelines/:id', async (request) => pipelineRegistry.getEntity(request.params.id));

  app.post('/api/pipelines', async (request) => pipelineRegistry.create(parsePipelineBody(request.body)));

  app.post('/api/pipelines/demo', async () => ({ created: await pipelineRegistry.seedDemo() }));

  app.put<{ Params: { id: string } }>('/api/pipelines/:id', async (request) => {
    const parsed = pipelineInputBodySchema.partial({ name: true, description: true }).safeParse(request.body ?? {});
    if (!parsed.success) {
      const msg = parsed.error.issues.map((i) => `${i.path.join('.') || 'body'}: ${i.message}`).join('; ');
      throw userError(`Invalid pipeline update: ${msg}`, 'INVALID_PIPELINE');
    }
    const patch = parsed.data as Partial<PipelineInput>;
    if (patch.steps !== undefined && patch.steps.length === 0) {
      throw userError('Pipeline must have at least one step', 'PIPELINE_NO_STEPS');
    }
    return pipelineRegistry.update(request.params.id, patch);
  });

  app.delete<{ Params: { id: string } }>('/api/pipelines/:id', async (request) => pipelineRegistry.delete(request.params.id));

  app.post<{ Params: { id: string } }>('/api/pipelines/:id/run', async (request) => {
    const parsed = runBodySchema.safeParse(request.body ?? {});
    if (!parsed.success) throw userError('Invalid run input: {"input": {...}}', 'INVALID_REQUEST');
    return pipelineExecutor.run(request.params.id, parsed.data.input ?? {});
  });

  app.get<{ Params: { id: string } }>('/api/pipelines/:id/history', async (request) => {
    const query = historyQuerySchema.parse(request.query);
    return pipelineRegistry.listExecutions(request.params.id, query.offset, query.limit);
  });

  app.get<{ Params: { executionId: string } }>('/api/pipeline-executions/:executionId', async (request) =>
    pipelineRegistry.getExecution(request.params.executionId),
  );
}