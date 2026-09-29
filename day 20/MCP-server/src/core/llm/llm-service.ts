import type { HttpClient } from '../http/http-client.js';
import type { Logger } from '../logging/logger.js';
import { redactText } from '../util/redact.js';
import type { LlmChatRequest, LlmSettings, LlmSettingsStoreLike, PublicLlmSettings } from './llm-types.js';
import type { LLMProvider } from './llm-types.js';
import { llmConfigError, mapLlmHttpError, OpenAIProvider } from './openai-provider.js';

export interface LlmServiceOptions {
  store: LlmSettingsStoreLike;
  http: HttpClient;
  logger: Logger;
  getTimeoutMs: () => number;
  /** Для тестов можно подменить провайдера. */
  provider?: LLMProvider;
}

/** Входные значения из UI: частичный набор, где apiKey может быть пустым (не менять). */
export interface LlmSettingsPatch {
  apiUrl?: string;
  apiKey?: string;
  model?: string;
}

/**
 * LLMService — единый фасад над LLM для summarize/pipelines.
 * Выполняет чек/получение моделей через провайдера (настоящие HTTP-запросы на backend),
 * хранит настройки и никогда не возвращает API key наружу.
 */
export class LlmService {
  private readonly store: LlmSettingsStoreLike;
  private readonly logger: Logger;
  private readonly provider: LLMProvider;

  constructor(opts: LlmServiceOptions) {
    this.store = opts.store;
    this.logger = opts.logger;
    this.provider = opts.provider ?? new OpenAIProvider(opts.http, opts.getTimeoutMs);
  }

  getProviderId(): string {
    return this.provider.id;
  }

  /** Безопасные настройки (без ключа). */
  getPublic(): PublicLlmSettings {
    return this.store.getPublic();
  }

  /** Текущие полные настройки (используется только внутри backend). */
  getSettings(): LlmSettings {
    return this.store.load();
  }

  isConfigured(): boolean {
    return this.store.isConfigured();
  }

  /** Проверка подключения с учётом «пробного» ключа из формы (не сохраняет). */
  async checkConnection(patch?: LlmSettingsPatch): Promise<{ ok: boolean; status: 'connected' | 'error'; message: string }> {
    const settings = this.effective(patch);
    if (!settings.apiKey) {
      return { ok: false, status: 'error', message: 'API key is required' };
    }
    const started = Date.now();
    this.logger.info(`[LLM] provider=${this.provider.id} check started`);
    try {
      await this.provider.checkConnection(settings);
      this.logger.info(`[LLM] provider=${this.provider.id} check completed duration=${Date.now() - started}ms`);
      return { ok: true, status: 'connected', message: 'Connected' };
    } catch (err) {
      const mapped = mapLlmHttpError(err, `${settings.apiUrl}/models`);
      this.logger.warn(`[LLM] provider=${this.provider.id} check failed`, { code: mapped.code, message: redactText(mapped.message) });
      return { ok: false, status: 'error', message: redactText(mapped.message) };
    }
  }

  /** Список моделей через {apiUrl}/models с текущими/пробными настройками. */
  async listModels(patch?: LlmSettingsPatch): Promise<string[]> {
    const settings = this.effective(patch);
    if (!settings.apiKey) throw llmConfigError('API key is required', 'LLM_API_KEY_REQUIRED');
    try {
      return await this.provider.listModels(settings);
    } catch (err) {
      throw mapLlmHttpError(err, `${settings.apiUrl}/models`);
    }
  }

  /** Сохранить настройки: пустой apiKey в patch = оставить существующий. */
  save(settings: LlmSettings): PublicLlmSettings {
    this.store.save(settings);
    const pub = this.store.getPublic();
    this.logger.info(`[LLM] provider=${pub.provider} settings saved, configured=${pub.configured}`);
    return pub;
  }

  /** chat-запрос с моделью из настроек; НЕ логирует prompt/ответ (могут содержать чувствительные данные). */
  async chat(system: string, user: string): Promise<string> {
    const settings = this.ensureConfigured();
    const request: LlmChatRequest = { model: settings.model, system, user };
    const started = Date.now();
    this.logger.info(`[LLM] provider=${this.provider.id} model=${settings.model} request started`);
    try {
      const content = await this.provider.chat(settings, request);
      this.logger.info(`[LLM] provider=${this.provider.id} model=${settings.model} request completed duration=${Date.now() - started}ms`);
      return content.trim();
    } catch (err) {
      this.logger.warn(`[LLM] provider=${this.provider.id} model=${settings.model} request failed duration=${Date.now() - started}ms`, {
        message: redactText(mapLlmHttpError(err, `${settings.apiUrl}/chat/completions`).message),
      });
      throw err;
    }
  }

  ensureConfigured(): LlmSettings {
    const settings = this.store.load();
    if (!settings.apiUrl || !settings.apiKey || !settings.model) {
      throw llmConfigError('LLM is not configured. Configure OpenAI in Settings → LLM.');
    }
    return settings;
  }

  /** Слить сохранённые настройки с частичным патчем формы (пустой key = не менять). */
  private effective(patch?: LlmSettingsPatch): LlmSettings {
    const stored = this.store.load();
    return {
      provider: 'openai',
      apiUrl: patch?.apiUrl?.trim() || stored.apiUrl,
      apiKey: patch?.apiKey ? patch.apiKey.trim() : stored.apiKey,
      model: patch?.model?.trim() || stored.model,
    };
  }
}