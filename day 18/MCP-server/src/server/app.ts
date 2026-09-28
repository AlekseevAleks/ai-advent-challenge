import path from 'node:path';
import { existsSync } from 'node:fs';
import Fastify, { type FastifyInstance } from 'fastify';
import fastifyStatic from '@fastify/static';
import { appErrorStatus, AppError } from '../core/errors.js';
import { redactText } from '../core/util/redact.js';
import type { Runtime } from './runtime.js';
import { registerProviderRoutes } from './routes/providers.js';
import { registerLogsRoutes } from './routes/logs.js';
import { registerStatusRoutes } from './routes/status.js';
import { registerTaskRoutes } from './routes/tasks.js';
import { registerSchedulerToolsRoutes } from './routes/scheduler-tools.js';
import { registerMcpHttpRoute } from './mcp-http.js';

const BODY_LIMIT_BYTES = 1024 * 1024; // 1 MiB — ограничение размера тела запроса

/**
 * Fastify-приложение: REST API, MCP endpoint (/mcp) и статика Web UI.
 * По умолчанию слушает только 127.0.0.1; auth не обязательна, но архитектура
 * готова к добавлению middleware аутентификации (пример — в footer и README).
 */
export async function buildApp(runtime: Runtime, webDistDir?: string): Promise<FastifyInstance> {
  const app = Fastify({
    logger: false, // используем собственный Logger + RequestLogger
    bodyLimit: BODY_LIMIT_BYTES,
    trustProxy: false,
  });

  // Толерантный JSON-парсер: пустое тело с Content-Type: application/json
  // (POST enable/disable/test без тела) не должен давать 400.
  app.addContentTypeParser('application/json', { parseAs: 'string' }, (request, body, done) => {
    if (typeof body !== 'string' || body.trim() === '') {
      done(null, undefined);
      return;
    }
    try {
      const parsed = JSON.parse(body);
      done(null, parsed);
    } catch (err) {
      done(err as Error, undefined);
    }
  });

  // ------------------------------------------------------------ security headers
  app.addHook('onSend', async (request, reply, payload) => {
    reply.header('x-content-type-options', 'nosniff');
    reply.header('x-frame-options', 'DENY');
    reply.header('referrer-policy', 'no-referrer');
    reply.header('x-permitted-cross-domain-policies', 'none');
    if (request.url.startsWith('/api')) {
      reply.header('content-security-policy', "default-src 'none'; frame-ancestors 'none'");
      reply.header('cache-control', 'no-store');
    }
    return payload;
  });

  // ------------------------------------------------------------ CORS (настраивается в runtime)
  app.addHook('onRequest', async (request, reply) => {
    const { settings } = runtime;
    const origin = request.headers.origin;
    if (!settings.corsEnabled || typeof origin !== 'string' || !origin) return;

    const isMcp = request.url.startsWith('/mcp');
    const allowed = isMcp ? true : settings.corsOrigins.includes(origin);
    if (!allowed) return;

    reply.header('access-control-allow-origin', origin);
    reply.header('vary', 'Origin');
    reply.header('access-control-allow-methods', 'GET,HEAD,PUT,PATCH,POST,DELETE,OPTIONS');
    reply.header(
      'access-control-allow-headers',
      typeof request.headers['access-control-request-headers'] === 'string'
        ? request.headers['access-control-request-headers']
        : 'content-type, mcp-session-id, accept',
    );
    reply.header('access-control-max-age', '86400');

    if (request.method === 'OPTIONS') {
      reply.code(204).send();
    }
  });

  // ------------------------------------------------------------ REST API
  registerStatusRoutes(app, runtime);
  registerProviderRoutes(app, runtime);
  registerLogsRoutes(app, runtime);
  registerTaskRoutes(app, runtime);
  registerSchedulerToolsRoutes(app, runtime);

  // ------------------------------------------------------------ MCP endpoint
  registerMcpHttpRoute(app, runtime.gateway, runtime.logger);

  // ------------------------------------------------------------ Web UI статика
  let staticServed = false;
  if (webDistDir && existsSync(webDistDir) && existsSync(path.join(webDistDir, 'index.html'))) {
    await app.register(fastifyStatic, { root: webDistDir, prefix: '/', wildcard: false, index: ['index.html'] });
    staticServed = true;
    runtime.logger.info(`[server] serving Web UI from ${webDistDir}`);
  }

  // SPA fallback: несуществующие пути без /api и /mcp отдают index.html
  app.setNotFoundHandler((request, reply) => {
    const url = request.url;
    if (url.startsWith('/api') || url.startsWith('/mcp')) {
      return reply.code(404).send({ error: { code: 'NOT_FOUND', message: 'Not found' } });
    }
    if (staticServed) {
      return reply.sendFile('index.html');
    }
    return reply
      .code(404)
      .type('text/plain')
      .send('Web UI is not built. Run `npm run build:web` (or use `npm run dev` and open http://127.0.0.1:5173).');
  });

  // ------------------------------------------------------------ error handler (санитизация)
  app.setErrorHandler((err, request, reply) => {
    if (request.url.startsWith('/mcp')) {
      const statusCode = (err as { statusCode?: number }).statusCode ?? 500;
      return reply.code(statusCode === 413 ? 413 : 500).send({
        error: { code: 'MCP_INTERNAL', message: 'Internal MCP server error' },
      });
    }

    if (err instanceof AppError) {
      // Позволяем точечно задавать статус (например 404 для TASK_NOT_FOUND)
      const status = err.status ?? appErrorStatus(err);
      if (status >= 500) {
        runtime.logger.error(`[api] ${request.method} ${request.url} -> ${status}`, {
          code: err.code,
          message: err.message,
        });
      } else if (runtime.settings.debug) {
        runtime.logger.debug(`[api] ${request.method} ${request.url} -> ${status}`, { code: err.code, message: err.message });
      }
      return reply.code(status).send({
        error: {
          code: err.code,
          kind: err.kind,
          message: redactText(err.message),
          retryAfter: err.retryAfter,
        },
      });
    }

    // Валидационные ошибки Fastify (route schema, bodyLimit, ...)
    const statusCode = (err as { statusCode?: number }).statusCode ?? 500;
    const message = (err as { message?: string }).message ?? 'Internal server error';
    if (statusCode >= 500) {
      runtime.logger.error(`[api] ${request.method} ${request.url} -> 500`, {
        message,
        stack: (err as { stack?: string }).stack,
      });
    }
    let safeMessage: string;
    if ((err as { validation?: unknown }).validation) {
      safeMessage = `Invalid request: ${message}`;
    } else if (statusCode === 413) {
      safeMessage = 'Request body too large';
    } else if (statusCode >= 500) {
      safeMessage = 'Internal server error';
    } else {
      safeMessage = redactText(message);
    }
    return reply.code(statusCode).send({ error: { code: 'HTTP_ERROR', message: safeMessage } });
  });

  return app;
}