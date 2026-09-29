import type { ProviderRegistry } from '../core/registry/provider-registry.js';
import type { PipelineToolRunner } from '../core/pipeline/pipeline-executor.js';
import { CORE_TOOL_NAMES, handleCoreTool, type CoreToolDeps } from './mcp-core-tools.js';

/**
 * Единый диспетчер вызова tools для PipelineExecutor:
 * core tools (summarize/saveToFile) + provider tools через ProviderRegistry.
 * Тот же путь, что используют MCP-вызовы, — scheduler/pipeline не создают
 * собственных HTTP-клиентов.
 */
export function createPipelineToolRunner(registry: ProviderRegistry, deps: CoreToolDeps): PipelineToolRunner {
  return async (tool: string, args: unknown) => {
    if (CORE_TOOL_NAMES.has(tool)) {
      return handleCoreTool(tool, args, deps);
    }
    return registry.executeTool(tool, args);
  };
}