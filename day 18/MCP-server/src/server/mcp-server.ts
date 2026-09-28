import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { CallToolRequestSchema, ListToolsRequestSchema } from '@modelcontextprotocol/sdk/types.js';
import type { CallToolResult, Tool } from '@modelcontextprotocol/sdk/types.js';
import { ProviderRegistry } from '../core/registry/provider-registry.js';
import { Logger } from '../core/logging/logger.js';
import { AppError, errorKindName, internalError, userError } from '../core/errors.js';
import { redactText } from '../core/util/redact.js';
import { APP_NAME, APP_VERSION } from '../core/version.js';
import type { TaskManager } from '../core/scheduler/task-manager.js';
import type { ConfigManager } from '../core/config/config-manager.js';
import { SCHEDULER_TOOL_DEFINITIONS, SCHEDULER_TOOL_NAMES, handleSchedulerTool } from './mcp-scheduler-tools.js';
import type { ToolDefinition } from '../core/providers/types.js';

const MAX_RESULT_CHARS = 200_000;

export interface McpGatewayOptions {
  /** Необязательный TaskManager: добавляет scheduler tools в MCP. */
  taskManager?: TaskManager;
  /** Нужен для чтения config/scheduler-tools.json (включение/выключение scheduler tools). */
  configManager?: ConfigManager;
}

/**
 * MCP Gateway: единая логика MCP-сервера поверх ProviderRegistry (+ Scheduler).
 * На каждый transport (HTTP-сессия или stdio) создаётся свой экземпляр Server,
 * но все они делегируют в один и тот же McpGateway — поэтому изменения
 * конфигурации (hot reload) сразу видны всем подключённым клиентам.
 */
export class McpGateway {
  private readonly taskManager?: TaskManager;
  private readonly configManager?: ConfigManager;
  private readonly schedulerTools: typeof SCHEDULER_TOOL_DEFINITIONS;

  constructor(
    private readonly registry: ProviderRegistry,
    private readonly logger: Logger,
    opts: McpGatewayOptions = {},
  ) {
    this.taskManager = opts.taskManager;
    this.configManager = opts.configManager;
    this.schedulerTools = opts.taskManager ? SCHEDULER_TOOL_DEFINITIONS : [];
  }

  /** Количество scheduler tools (для бутстрапа). */
  getSchedulerToolCount(): number {
    return this.schedulerTools.length;
  }

  /** Состояние scheduler tools для REST/UI: name, description, inputSchema, enabled. */
  listSchedulerToolsState(): Array<ToolDefinition & { enabled: boolean }> {
    return this.schedulerTools.map((tool) => ({ ...tool, enabled: this.isSchedulerToolEnabled(tool.name) }));
  }

  /** Включить/выключить scheduler tool (персистентно в config/scheduler-tools.json). */
  setSchedulerToolEnabled(toolId: string, enabled: boolean): void {
    if (!SCHEDULER_TOOL_NAMES.has(toolId)) {
      throw userError(`Unknown scheduler tool: ${toolId}`, 'UNKNOWN_TOOL');
    }
    if (!this.configManager) {
      throw internalError('Scheduler tools config is unavailable', 'NO_CONFIG_MANAGER');
    }
    this.configManager.updateSchedulerToolConfig(toolId, enabled);
  }

  isSchedulerToolEnabled(name: string): boolean {
    return this.configManager ? this.configManager.isSchedulerToolEnabled(name) : true;
  }

  createSessionServer(): Server {
    const server = new Server(
      { name: APP_NAME, version: APP_VERSION },
      { capabilities: { tools: {} } },
    );

    server.setRequestHandler(ListToolsRequestSchema, async () => ({
      tools: [...this.registry.getMcpTools(), ...this.schedulerTools.filter((t) => this.isSchedulerToolEnabled(t.name))] as Tool[],
    }));

    server.setRequestHandler(CallToolRequestSchema, async (request) => {
      const { name, arguments: args } = request.params;
      return this.handleCallTool(name, args);
    });

    server.onerror = (err) => {
      this.logger.error('[mcp] server error', { message: redactText(err instanceof Error ? err.message : String(err)) });
    };

    return server;
  }

  private async handleCallTool(name: string, args: unknown): Promise<CallToolResult> {
    try {
      if (this.taskManager && SCHEDULER_TOOL_NAMES.has(name)) {
        if (!this.isSchedulerToolEnabled(name)) {
          throw userError(`Scheduler tool "${name}" is disabled`, 'UNKNOWN_TOOL');
        }
        const result = await handleSchedulerTool(this.taskManager, name, args);
        this.logger.info(`[mcp] scheduler tool "${name}" ok`);
        return { content: [{ type: 'text', text: formatToolResult(result) }], isError: false };
      }
      if (!this.registry.isToolEnabled(name)) {
        throw userError(`Tool "${name}" is unknown or disabled`, 'UNKNOWN_TOOL');
      }
      const result = await this.registry.executeTool(name, args ?? {});
      this.logger.info(`[mcp] tool "${name}" ok`);
      return { content: [{ type: 'text', text: formatToolResult(result) }], isError: false };
    } catch (err) {
      if (err instanceof AppError) {
        if (err.kind === 'internal') {
          this.logger.error(`[mcp] tool "${name}" failed`, { stack: err.cause instanceof Error ? err.cause.stack : undefined });
        } else {
          this.logger.warn(`[mcp] tool "${name}" failed`, { kind: err.kind, message: err.message, status: err.status, retryAfter: err.retryAfter });
        }
        const message = redactText(err.message);
        return {
          content: [{ type: 'text', text: `${errorKindName(err.kind)}: ${message}` }],
          isError: true,
        };
      }
      const unwrapped = err instanceof Error ? internalError('Internal server error', 'INTERNAL_ERROR', err) : err;
      this.logger.error(`[mcp] tool "${name}" crashed`, { stack: err instanceof Error ? err.stack : undefined });
      return { content: [{ type: 'text', text: 'Internal error: unexpected failure' }], isError: true };
    }
  }
}

/** Результат tool → текст для MCP (никогда не содержит секретов). */
function formatToolResult(result: unknown): string {
  let text: string;
  if (typeof result === 'string') text = result;
  else text = formatJson(result, 2);
  if (text.length > MAX_RESULT_CHARS) {
    text = `${text.slice(0, MAX_RESULT_CHARS)}\n[Result truncated]`;
  }
  return text;
}

/** JSON.stringify с красивым форматированием и защитой от циклических ссылок. */
function formatJson(value: unknown, indent?: number): string {
  const seen = new WeakSet<object>();
  try {
    return JSON.stringify(
      value,
      (_key, val) => {
        if (val !== null && typeof val === 'object') {
          if (seen.has(val)) return '[Circular]';
          seen.add(val);
        }
        return val;
      },
      indent,
    );
  } catch {
    return String(value);
  }
}