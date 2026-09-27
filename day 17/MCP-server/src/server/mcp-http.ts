import { randomUUID } from 'node:crypto';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { Logger } from '../core/logging/logger.js';
import type { McpGateway } from './mcp-server.js';

interface McpSession {
  transport: StreamableHTTPServerTransport;
  lastActive: number;
}

const SESSION_TTL_MS = 60 * 60 * 1000; // 1 час без активности
const SWEEP_INTERVAL_MS = 10 * 60 * 1000;

/**
 * Регистрирует MCP endpoint по Streamable HTTP transport (спецификация MCP):
 *   POST   /mcp  — JSON-RPC запросы (initialize, tools/list, tools/call, ...)
 *   GET    /mcp  — SSE-поток для resumable-сессий
 *   DELETE /mcp  — закрытие сессии
 *
 * В SDK транспорт держит ОДНУ сессию на экземпляр, поэтому на каждый новый
 * handshake (initialize без Mcp-Session-Id) создаётся отдельный transport + Server,
 * а последующие запросы того же клиента направляются в сохранённую сессию.
 * Все Server'ы делегируют в общий McpGateway, поэтому hot reload config
 * мгновенно виден всем клиентам.
 */
export function registerMcpHttpRoute(app: FastifyInstance, gateway: McpGateway, logger: Logger): void {
  const sessions = new Map<string, McpSession>();

  const createSessionServer = async (): Promise<StreamableHTTPServerTransport> => {
    const transport = new StreamableHTTPServerTransport({
      sessionIdGenerator: () => randomUUID(),
      onsessioninitialized: (sessionId) => {
        sessions.set(sessionId, { transport, lastActive: Date.now() });
        logger.info(`[mcp] session initialized: ${sessionId}`);
      },
      onsessionclosed: (sessionId) => {
        sessions.delete(sessionId);
        logger.info(`[mcp] session closed: ${sessionId}`);
      },
    });
    const mcpServer = gateway.createSessionServer();
    await mcpServer.connect(transport);
    return transport;
  };

  const handle = async (req: FastifyRequest, reply: FastifyReply): Promise<void> => {
    reply.hijack();
    const sessionId =
      typeof req.headers['mcp-session-id'] === 'string' ? req.headers['mcp-session-id'] : undefined;

    let transport: StreamableHTTPServerTransport;
    if (sessionId) {
      const session = sessions.get(sessionId);
      if (!session) {
        reply.raw.statusCode = 404;
        reply.raw.setHeader('content-type', 'application/json');
        reply.raw.end('{"jsonrpc":"2.0","error":{"code":-32001,"message":"Session not found"},"id":null}');
        return;
      }
      session.lastActive = Date.now();
      transport = session.transport;
    } else {
      try {
        transport = await createSessionServer();
      } catch (err) {
        logger.error('[mcp] cannot create session server', { error: err instanceof Error ? err.message : String(err) });
        reply.raw.statusCode = 500;
        reply.raw.end('{"jsonrpc":"2.0","error":{"code":-32603,"message":"Internal MCP server error"},"id":null}');
        return;
      }
    }

    try {
      await transport.handleRequest(req.raw, reply.raw, req.body);
    } catch (err) {
      logger.error('[mcp] handleRequest failed', { error: err instanceof Error ? err.message : String(err) });
      if (!reply.raw.headersSent) {
        reply.raw.statusCode = 500;
        reply.raw.end('{"jsonrpc":"2.0","error":{"code":-32603,"message":"Internal MCP server error"},"id":null}');
      } else {
        reply.raw.end();
      }
    }
  };

  app.post('/mcp', handle);
  app.get('/mcp', handle);
  app.delete('/mcp', handle);

  // Периодическая очистка простаивающих сессий
  const sweeper = setInterval(() => {
    const now = Date.now();
    for (const [id, session] of sessions) {
      if (now - session.lastActive > SESSION_TTL_MS) {
        logger.info(`[mcp] closing idle session: ${id}`);
        sessions.delete(id);
        void session.transport.close().catch(() => undefined);
      }
    }
  }, SWEEP_INTERVAL_MS);
  sweeper.unref();

  app.addHook('onClose', async () => {
    clearInterval(sweeper);
    for (const [, session] of sessions) {
      await session.transport.close().catch(() => undefined);
    }
    sessions.clear();
  });
}