import { z } from 'zod';
import { userError } from '../core/errors.js';
import type { ToolDefinition } from '../core/providers/types.js';
import type { PipelineExecutor } from '../core/pipeline/pipeline-executor.js';
import type { PipelineRegistry } from '../core/pipeline/pipeline-registry.js';

const prop = (description: string, type: string): Record<string, unknown> => ({ type, description });

export const runPipelineToolDefinition: ToolDefinition = {
  name: 'run_pipeline',
  description:
    'Запускает pipeline: выполняет шаги по порядку (github_list_issues → summarize → saveToFile и т.п.), передавая output одного шага следующему через шаблоны {{steps.<id>.output}}. Возвращает статусы шагов и executionId.',
  inputSchema: {
    type: 'object',
    properties: {
      pipeline: prop('ID pipeline (например, github-summary)', 'string'),
      input: prop('Объект с входными данными для шаблонов {{input.*}}', 'object'),
    },
    required: ['pipeline'],
    additionalProperties: false,
  },
};

export const listPipelinesToolDefinition: ToolDefinition = {
  name: 'list_pipelines',
  description: 'Список всех зарегистрированных pipelines (id, name, description, шаги, время последнего запуска).',
  inputSchema: { type: 'object', properties: {}, additionalProperties: false },
};

export const deletePipelineToolDefinition: ToolDefinition = {
  name: 'delete_pipeline',
  description: 'Удаляет pipeline вместе с историей его выполнений.',
  inputSchema: {
    type: 'object',
    properties: { pipeline: prop('ID pipeline', 'string') },
    required: ['pipeline'],
    additionalProperties: false,
  },
};

export const PIPELINE_TOOL_DEFINITIONS: ToolDefinition[] = [
  runPipelineToolDefinition,
  listPipelinesToolDefinition,
  deletePipelineToolDefinition,
];

export const PIPELINE_TOOL_NAMES = new Set(PIPELINE_TOOL_DEFINITIONS.map((t) => t.name));

const runPipelineSchema = z
  .object({ pipeline: z.string().min(1).max(100), input: z.record(z.string(), z.unknown()).optional() })
  .passthrough();
const idSchema = z.object({ pipeline: z.string().min(1).max(100) }).passthrough();

export interface PipelineToolDeps {
  registry?: PipelineRegistry;
  executor?: PipelineExecutor;
}

/** Выполнение pipeline-тула через PipelineRegistry/PipelineExecutor (общая логика для MCP). */
export async function handlePipelineTool(deps: PipelineToolDeps, name: string, args: unknown): Promise<unknown> {
  switch (name) {
    case 'run_pipeline': {
      if (!deps.executor) throw userError('Pipelines are unavailable', 'PIPELINES_UNAVAILABLE');
      const parsed = parse(runPipelineSchema, args);
      const result = await deps.executor.run(parsed.pipeline, parsed.input ?? {});
      return { ...result, message: `Pipeline "${result.pipelineId}" ${result.status}` };
    }
    case 'list_pipelines': {
      if (!deps.registry) throw userError('Pipelines registry is unavailable', 'PIPELINES_UNAVAILABLE');
      return { items: deps.registry.list(), total: deps.registry.list().length };
    }
    case 'delete_pipeline': {
      if (!deps.registry) throw userError('Pipelines registry is unavailable', 'PIPELINES_UNAVAILABLE');
      const parsed = parse(idSchema, args);
      return deps.registry.delete(parsed.pipeline);
    }
    default:
      throw userError(`Unknown pipeline tool: ${name}`, 'UNKNOWN_TOOL');
  }
}

function parse<T>(schema: z.ZodType<T>, args: unknown): T {
  const result = schema.safeParse(args ?? {});
  if (!result.success) {
    const msg = result.error.issues.map((i) => `${i.path.join('.') || 'input'}: ${i.message}`).join('; ');
    throw userError(`Invalid pipeline tool input: ${msg}`, 'INVALID_TOOL_INPUT');
  }
  return result.data;
}