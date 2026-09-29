import type { FastifyInstance } from 'fastify';
import { z } from 'zod';
import type { TaskInput, TaskUpdate } from '../../core/scheduler/task-types.js';
import type { Runtime } from '../runtime.js';

const historyQuerySchema = z.object({
  offset: z.coerce.number().int().min(0).default(0),
  limit: z.coerce.number().int().min(1).max(500).default(50),
});

const summaryQuerySchema = z.object({
  window: z.enum(['1h', '24h', '7d', '30d', 'all', 'custom']).optional(),
  from: z.string().optional(),
  to: z.string().optional(),
  strategy: z.string().optional(),
});

/**
 * REST API Scheduled Tasks. Вся бизнес-логика — в TaskManager (тот же,
 * что используют MCP tools): никакой дублирующей логики для Web UI.
 */
export function registerTaskRoutes(app: FastifyInstance, runtime: Runtime): void {
  const { taskManager } = runtime;

  app.get('/api/tasks', async () => {
    const items = taskManager.listTasks();
    return { items, total: items.length };
  });

  app.post('/api/tasks', async (request) => taskManager.create(request.body as TaskInput));

  app.post('/api/tasks/demo', async () => ({ created: await taskManager.createDemoTasks() }));

  app.get<{ Params: { id: string } }>('/api/tasks/:id', async (request) => taskManager.getTask(request.params.id));

  app.put<{ Params: { id: string } }>('/api/tasks/:id', async (request) =>
    taskManager.update(request.params.id, request.body as TaskUpdate),
  );

  app.delete<{ Params: { id: string } }>('/api/tasks/:id', async (request) => taskManager.delete(request.params.id));

  app.post<{ Params: { id: string } }>('/api/tasks/:id/pause', async (request) => taskManager.pause(request.params.id));

  app.post<{ Params: { id: string } }>('/api/tasks/:id/resume', async (request) => taskManager.resume(request.params.id));

  app.post<{ Params: { id: string } }>('/api/tasks/:id/run', async (request) => taskManager.runNow(request.params.id));

  app.get<{ Params: { id: string } }>('/api/tasks/:id/history', async (request) => {
    const query = historyQuerySchema.parse(request.query);
    return taskManager.getHistory(request.params.id, query.offset, query.limit);
  });

  app.get<{ Params: { id: string } }>('/api/tasks/:id/summary', async (request) => {
    const query = summaryQuerySchema.parse(request.query);
    return taskManager.getSummary(request.params.id, {
      window: query.window,
      from: query.from,
      to: query.to,
      strategy: query.strategy as never,
    });
  });
}