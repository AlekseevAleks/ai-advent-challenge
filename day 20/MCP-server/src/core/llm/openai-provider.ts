import { authError, configError, externalApiError, rateLimitError, timeoutError } from '../errors.js';
import { redactText } from '../util/redact.js';
import type { HttpClient } from '../http/http-client.js';
import type { LlmChatRequest, LlmSettings, LLMProvider } from './llm-types.js';

interface ModelsResponse {
  data?: Array<{ id?: string }>;
  error?: { message?: string; type?: string };
}

interface ChatResponse {
  choices?: Array<{ message?: { content?: string | null } }>;
  error?: { message?: string; type?: string };
}

/** Корректная склейка base URL и endpoint (без дублей слешей и без жёсткого /chat/completions в настройках). */
function joinUrl(base: string, pathPart: string): string {
  return `${base.replace(/\/+$/, '')}/${pathPart.replace(/^\/+/, '')}`;
}

/**
 * OpenAIProvider — реализация LLMProvider для OpenAI / OpenAI-compatible API.
 * Не хардкодит URL/key/model: всё берётся из LlmSettings.
 * Endpoint формируется на уровне провайдера: {apiUrl}/models и {apiUrl}/chat/completions.
 */
export class OpenAIProvider implements LLMProvider {
  readonly id = 'openai';
  readonly name = 'OpenAI';

  constructor(private readonly http: HttpClient, private readonly getTimeoutMs: () => number = () => 15_000) {}

  async checkConnection(settings: LlmSettings): Promise<void> {
    await this.http.get<ModelsResponse>(joinUrl(settings.apiUrl, 'models'), {
      headers: this.bearer(settings),
      timeoutMs: this.getTimeoutMs(),
      log: { provider: 'llm', providerName: 'OpenAI', tool: 'models', direction: 'test' },
      errorMessageExtractor: () => null,
    });
  }

  async listModels(settings: LlmSettings): Promise<string[]> {
    const res = await this.http.get<ModelsResponse>(joinUrl(settings.apiUrl, 'models'), {
      headers: this.bearer(settings),
      timeoutMs: this.getTimeoutMs(),
      log: { provider: 'llm', providerName: 'OpenAI', tool: 'models', direction: 'test' },
      errorMessageExtractor: () => null,
    });
    const models = (res.data.data ?? []).map((m) => m.id).filter((id): id is string => typeof id === 'string');
    if (models.length === 0) {
      throw externalApiError('Unexpected /models response: "data[].id" not found', 200);
    }
    return models.sort((a, b) => a.localeCompare(b));
  }

  async chat(settings: LlmSettings, request: LlmChatRequest): Promise<string> {
    const body = {
      model: request.model,
      messages: [
        { role: 'system', content: request.system },
        { role: 'user', content: request.user },
      ],
      temperature: 0.3,
    };
    const res = await this.http.post<ChatResponse>(joinUrl(settings.apiUrl, 'chat/completions'), {
      headers: this.bearer(settings),
      body,
      timeoutMs: request.timeoutMs ?? this.getTimeoutMs(),
      log: { provider: 'llm', providerName: 'OpenAI', tool: 'chat/completions', direction: 'mcp' },
      errorMessageExtractor: () => null,
    });
    const content = res.data?.choices?.[0]?.message?.content;
    if (typeof content !== 'string') {
      throw externalApiError('Unexpected chat completion response: choices[0].message.content missing', res.status);
    }
    return content;
  }

  private bearer(settings: LlmSettings): Record<string, string> {
    return { authorization: `Bearer ${settings.apiKey}`, accept: 'application/json' };
  }
}

/** Сопоставить HTTP-ошибку OpenAI с понятной ошибкой AppError (без секретов). */
export function mapLlmHttpError(err: unknown, context: string): ReturnType<typeof externalApiError> {
  const status = (err as { status?: number }).status;
  const kind = (err as { kind?: string }).kind;
  const message = err instanceof Error ? err.message : String(err);

  if (status === 401 || status === 403) {
    return authError(`Invalid API key or unauthorized (HTTP ${status})`, 'LLM_UNAUTHORIZED', status);
  }
  if (status === 404) {
    return externalApiError(
      `Endpoint not found (HTTP 404) — check that the API URL points to an OpenAI-compatible base (expected "${context}")`,
      status,
    );
  }
  if (status === 429) {
    return rateLimitError('LLM API rate limit exceeded (HTTP 429)', (err as { retryAfter?: number }).retryAfter);
  }
  if (status && status >= 500) {
    return externalApiError(`LLM API server error (HTTP ${status})`, status);
  }
  if (kind === 'timeout' || message.toLowerCase().includes('timed out')) {
    return timeoutError('LLM request timed out', 'LLM_TIMEOUT', err);
  }
  // Сетевые/прочие: режем потенциальные секреты и стектрейсы
  return externalApiError(`LLM request failed: ${redactText(message).slice(0, 300)}`, status, undefined, 'LLM_ERROR');
}

export const llmConfigError = (message: string, code = 'LLM_NOT_CONFIGURED') => configError(message, code);