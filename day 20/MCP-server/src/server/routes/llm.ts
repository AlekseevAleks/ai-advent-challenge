import type { FastifyInstance } from 'fastify';
import { z } from 'zod';
import { userError } from '../../core/errors.js';
import { llmConfigError } from '../../core/llm/openai-provider.js';
import type { LlmSettingsPatch } from '../../core/llm/llm-service.js';
import type { Runtime } from '../runtime.js';

const llmPatchSchema = z
  .object({
    apiUrl: z.string().min(1).optional(),
    apiKey: z.string().optional(),
    model: z.string().min(1).optional(),
  })
  .strict();

function parsePatch(body: unknown): LlmSettingsPatch {
  const parsed = llmPatchSchema.safeParse(body ?? {});
  if (!parsed.success) {
    throw userError('Invalid LLM settings payload', 'INVALID_REQUEST');
  }
  if (parsed.data.apiUrl) {
    try {
      new URL(parsed.data.apiUrl);
    } catch {
      throw userError('Invalid API URL', 'INVALID_API_URL');
    }
  }
  return parsed.data as LlmSettingsPatch;
}

/**
 * REST API настройки LLM.
 * API key: принимается на backend, хранится в data/llm.json и НИКОГДА не возвращается
 * через GET-эндпоинты. Проверка подключения и список моделей выполняются backend'ом.
 */
export function registerLlmRoutes(app: FastifyInstance, runtime: Runtime): void {
  const { llm } = runtime;

  app.get('/api/settings/llm', async () => llm.getPublic());

  app.post('/api/settings/llm/check', async (request) => llm.checkConnection(parsePatch(request.body)));

  app.post('/api/settings/llm/models', async (request) => ({
    models: await llm.listModels(parsePatch(request.body)),
  }));

  app.put('/api/settings/llm', async (request) => {
    const patch = parsePatch(request.body);
    const current = llm.getSettings();
    const apiUrl = patch.apiUrl?.trim() || current.apiUrl;
    const apiKey = patch.apiKey !== undefined && patch.apiKey.trim() !== '' ? patch.apiKey.trim() : current.apiKey;
    const model = patch.model?.trim() || current.model;

    if (!apiUrl) throw userError('API URL is required', 'LLM_API_URL_REQUIRED');
    if (!apiKey) throw userError('API key is required', 'LLM_API_KEY_REQUIRED');
    if (!model) throw userError('Model is required', 'LLM_MODEL_REQUIRED');

    const saved = llm.save({ provider: 'openai', apiUrl, apiKey, model });
    return { success: true, configured: saved.configured, provider: saved.provider, model: saved.model };
  });
}

export { llmConfigError };