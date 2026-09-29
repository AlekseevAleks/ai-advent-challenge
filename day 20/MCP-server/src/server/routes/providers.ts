import type { FastifyInstance } from 'fastify';
import { z } from 'zod';
import { userError } from '../../core/errors.js';
import type { Runtime } from '../runtime.js';
import { formatZodMessage, providerUpdateSchema, toolUpdateSchema } from '../validation.js';

function jsonError(code: string, message: string): { error: { code: string; message: string } } {
  return { error: { code, message } };
}

/**
 * REST API управления провайдерами. Backend — единственный компонент,
 * читающий и изменяющий JSON-конфигурацию; Web UI работает только через эти маршруты.
 */
export function registerProviderRoutes(app: FastifyInstance, runtime: Runtime): void {
  const { registry } = runtime;

  app.get('/api/providers', async () => registry.getRuntimeState());

  app.get<{ Params: { id: string } }>('/api/providers/:id', async (request, reply) => {
    const state = registry.getProviderRuntimeState(request.params.id);
    if (!state) return reply.code(404).send(jsonError('NOT_FOUND', `Provider "${request.params.id}" not found`));
    return state;
  });

  app.put<{ Params: { id: string } }>('/api/providers/:id', async (request, reply) => {
    const id = request.params.id;
    if (!registry.hasProvider(id)) {
      return reply.code(404).send(jsonError('NOT_FOUND', `Provider "${id}" not found`));
    }
    const parsed = providerUpdateSchema.safeParse(request.body);
    if (!parsed.success) {
      throw userError(`Invalid provider update: ${formatZodMessage(parsed.error)}`, 'INVALID_REQUEST');
    }
    await registry.updateProviderConfig(id, parsed.data);
    const state = registry.getProviderRuntimeState(id);
    return state;
  });

  app.post<{ Params: { id: string } }>('/api/providers/:id/enable', async (request, reply) => {
    const id = request.params.id;
    if (!registry.hasProvider(id)) return reply.code(404).send(jsonError('NOT_FOUND', `Provider "${id}" not found`));
    await registry.setProviderEnabled(id, true);
    return registry.getProviderRuntimeState(id);
  });

  app.post<{ Params: { id: string } }>('/api/providers/:id/disable', async (request, reply) => {
    const id = request.params.id;
    if (!registry.hasProvider(id)) return reply.code(404).send(jsonError('NOT_FOUND', `Provider "${id}" not found`));
    await registry.setProviderEnabled(id, false);
    return registry.getProviderRuntimeState(id);
  });

  app.post<{ Params: { id: string } }>('/api/providers/:id/test', async (request, reply) => {
    const id = request.params.id;
    if (!registry.hasProvider(id)) return reply.code(404).send(jsonError('NOT_FOUND', `Provider "${id}" not found`));
    const health = await registry.testConnection(id);
    return { ...health, ok: health.status === 'ok' };
  });

  app.get<{ Params: { id: string } }>('/api/providers/:id/tools', async (request, reply) => {
    const state = registry.getProviderRuntimeState(request.params.id);
    if (!state) return reply.code(404).send(jsonError('NOT_FOUND', `Provider "${request.params.id}" not found`));
    return state.tools;
  });

  app.put<{ Params: { id: string; toolId: string } }>('/api/providers/:id/tools/:toolId', async (request, reply) => {
    const { id, toolId } = request.params;
    if (!registry.hasProvider(id)) return reply.code(404).send(jsonError('NOT_FOUND', `Provider "${id}" not found`));
    const parsed = toolUpdateSchema.safeParse(request.body);
    if (!parsed.success) {
      throw userError(`Invalid tool update: ${formatZodMessage(parsed.error)}`, 'INVALID_REQUEST');
    }
    return registry.updateToolConfig(id, toolId, parsed.data);
  });
}

// Ниже — типы только для ясности (Fastify парсит params через generic-интерфейс).
export interface ProviderParams {
  id: string;
  toolId: string;
}

export const providerParams = z.object({ id: z.string(), toolId: z.string() });