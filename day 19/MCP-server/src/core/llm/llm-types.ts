import type { HttpClient } from '../http/http-client.js';
import type { Logger } from '../logging/logger.js';

/** Настройки LLM, хранимые локально в data/llm.json (секрет! не попадает в git). */
export interface LlmSettings {
  provider: 'openai';
  apiUrl: string;
  apiKey: string;
  model: string;
}

/** Безопасное представление для frontend (API key никогда не возвращается). */
export interface PublicLlmSettings {
  provider: 'openai';
  apiUrl: string;
  model: string;
  configured: boolean;
}

export interface LlmChatRequest {
  model: string;
  system: string;
  user: string;
  timeoutMs?: number;
}

/** Абстракция LLM-провайдера — позволяет добавить Anthropic/Ollama и др. */
export interface LLMProvider {
  readonly id: string;
  readonly name: string;
  /** Реальная проверка: GET {apiUrl}/models с Bearer-ключом. */
  checkConnection(settings: LlmSettings): Promise<void>;
  /** Список моделей через API (не хардкодим). */
  listModels(settings: LlmSettings): Promise<string[]>;
  /** Один chat-запрос, возвращает текстовый ответ. */
  chat(settings: LlmSettings, request: LlmChatRequest): Promise<string>;
}

export interface LlmDeps {
  store: LlmSettingsStoreLike;
  http: HttpClient;
  logger: Logger;
  /** Таймаут LLM-запросов (берём из существующих настроек сервера). */
  getTimeoutMs: () => number;
}

export interface LlmSettingsStoreLike {
  load(): LlmSettings;
  save(settings: LlmSettings): void;
  getPublic(): PublicLlmSettings;
  isConfigured(): boolean;
}