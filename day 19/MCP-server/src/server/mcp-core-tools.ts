import { z } from 'zod';
import { outputFileSchema, summarizeInputSchema } from './core-tool-schemas.js';
import { userError } from '../core/errors.js';
import type { ToolDefinition } from '../core/providers/types.js';
import type { LlmService } from '../core/llm/llm-service.js';
import type { OutputFileService } from '../core/files/output-file.js';

const prop = (description: string, type: string, extra: Record<string, unknown> = {}): Record<string, unknown> => ({
  type,
  description,
  ...extra,
});

const SUMMARIZE_SYSTEM = 'You are a concise summarization assistant.';

/**
 * Core MCP tools, которые живут в самом Gateway (не у провайдеров):
 * - summarize  — через LLMService (настроенный OpenAI и др.);
 * - saveToFile — безопасная запись в data/output/.
 */

export const summarizeToolDefinition: ToolDefinition = {
  name: 'summarize',
  description:
    'Summarizes provided data using the configured LLM (OpenAI). Returns {summary}. Требует настройки LLM в Settings → LLM.',
  inputSchema: {
    type: 'object',
    properties: {
      data: prop('Данные для сводки: любой JSON/объект/строка', 'object'),
      instruction: prop('Опциональная инструкция к сводке', 'string'),
    },
    required: ['data'],
    additionalProperties: false,
  },
};

export const saveToFileToolDefinition: ToolDefinition = {
  name: 'saveToFile',
  description:
    'Saves text content into data/output/ (защищено от path traversal; максимум 1 МиБ). Returns {path, size}.',
  inputSchema: {
    type: 'object',
    properties: {
      filename: prop('Имя файла относительно data/output/ (например, summary.txt)', 'string'),
      content: prop('Содержимое файла', 'string'),
    },
    required: ['filename', 'content'],
    additionalProperties: false,
  },
};

export const CORE_TOOL_DEFINITIONS: ToolDefinition[] = [summarizeToolDefinition, saveToFileToolDefinition];
export const CORE_TOOL_NAMES = new Set(CORE_TOOL_DEFINITIONS.map((t) => t.name));

export interface CoreToolDeps {
  llmService?: LlmService;
  fileService?: OutputFileService;
}

/** Выполнение core tool (общая логика для MCP и Pipeline-диспетчера). */
export async function handleCoreTool(name: string, args: unknown, deps: CoreToolDeps): Promise<unknown> {
  switch (name) {
    case 'summarize': {
      const parsed = summarizeInputSchema.safeParse(args ?? {});
      if (!parsed.success) throw userError(`Invalid summarize input: ${zodMsg(parsed.error)}`, 'INVALID_TOOL_INPUT');
      if (!deps.llmService) {
        throw userError('LLM is not configured. Configure OpenAI in Settings → LLM.', 'LLM_NOT_CONFIGURED');
      }
      const { data, instruction } = parsed.data;
      const dataText = typeof data === 'string' ? data : safeJson(data);
      const user = instruction
        ? `${instruction}\n\nSummarize the following data:\n\n<DATA>\n${dataText}`
        : `Summarize the following data:\n\n<DATA>\n${dataText}`;
      const summary = await deps.llmService.chat(SUMMARIZE_SYSTEM, user);
      return { summary };
    }
    case 'saveToFile': {
      const parsed = outputFileSchema.safeParse(args ?? {});
      if (!parsed.success) throw userError(`Invalid saveToFile input: ${zodMsg(parsed.error)}`, 'INVALID_TOOL_INPUT');
      if (!deps.fileService) throw userError('File output is unavailable', 'FILE_OUTPUT_UNAVAILABLE');
      const result = deps.fileService.write(parsed.data.filename, parsed.data.content);
      return { ...result, message: `Saved to data/output/${result.path}` };
    }
    default:
      throw userError(`Unknown core tool: ${name}`, 'UNKNOWN_TOOL');
  }
}

function safeJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function zodMsg(err: z.ZodError): string {
  return err.issues.map((i) => `${i.path.join('.') || 'input'}: ${i.message}`).join('; ');
}