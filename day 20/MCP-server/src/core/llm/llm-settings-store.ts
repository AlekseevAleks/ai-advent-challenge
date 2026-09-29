import { chmodSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { z } from 'zod';
import { configError } from '../errors.js';
import type { LlmSettings, PublicLlmSettings } from './llm-types.js';

const llmSettingsSchema = z.object({
  provider: z.literal('openai').default('openai'),
  apiUrl: z.string().url().default('https://api.openai.com/v1'),
  apiKey: z.string().default(''),
  model: z.string().default(''),
});

export type LlmSettingsFile = z.infer<typeof llmSettingsSchema>;

/**
 * Хранение LLM-конфигурации в отдельном файле data/llm.json.
 * Файл с реальным API key добавлен в .gitignore; шаблон — data/llm.example.json.
 * Права файла: 0600 (читает только владелец).
 */
export class LlmSettingsStore {
  readonly filePath: string;

  constructor(dataDir: string) {
    this.filePath = path.join(dataDir, 'llm.json');
  }

  load(): LlmSettings {
    let raw: string;
    try {
      raw = readFileSync(this.filePath, 'utf8');
    } catch {
      return { provider: 'openai', apiUrl: 'https://api.openai.com/v1', apiKey: '', model: '' };
    }
    try {
      const parsed = llmSettingsSchema.parse(JSON.parse(raw));
      return { provider: parsed.provider, apiUrl: parsed.apiUrl, apiKey: parsed.apiKey ?? '', model: parsed.model ?? '' };
    } catch (err) {
      throw configError(`Invalid LLM settings file (llm.json): ${err instanceof Error ? err.message : String(err)}`, 'INVALID_LLM_SETTINGS', err);
    }
  }

  save(settings: LlmSettings): void {
    try {
      mkdirSync(path.dirname(this.filePath), { recursive: true });
      const tmp = `${this.filePath}.${process.pid}.tmp`;
      writeFileSync(tmp, `${JSON.stringify(settings, null, 2)}\n`, { encoding: 'utf8', mode: 0o600 });
      renameSync(tmp, this.filePath);
      chmodSync(this.filePath, 0o600);
    } catch (err) {
      throw configError(`Cannot write LLM settings: ${err instanceof Error ? err.message : String(err)}`, 'LLM_SETTINGS_WRITE_ERROR', err);
    }
  }

  isConfigured(): boolean {
    const s = this.load();
    return !!s.apiUrl && !!s.apiKey && !!s.model;
  }

  /** Безопасные настройки для REST/UI: никогда без apiKey. */
  getPublic(): PublicLlmSettings {
    const s = this.load();
    return {
      provider: s.provider,
      apiUrl: s.apiUrl,
      model: s.model,
      configured: !!s.apiUrl && !!s.apiKey && !!s.model,
    };
  }
}