import { chmodSync, existsSync, mkdirSync, readFileSync, readdirSync, renameSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { z } from 'zod';
import { configError } from '../errors.js';
import {
  credentialsStoreSchema,
  LOG_LEVELS,
  PROVIDER_ID_RE,
  providerConfigFileSchema,
  serverConfigSchema,
} from './schemas.js';
import type { ProviderConfig, ServerSettings } from '../types.js';

export interface ConfigManagerOptions {
  configDir: string;
  dataDir: string;
  env?: NodeJS.ProcessEnv;
}

function formatZodError(err: z.ZodError): string {
  return err.issues
    .map((issue) => `${issue.path.join('.') || '<root>'}: ${issue.message}`)
    .join('; ');
}

/**
 * Единственный компонент, читающий и пишущий JSON-конфигурацию.
 * Весь остальной код (включая Web UI) работает через REST API.
 * Защищён от path traversal: id провайдера проверяется строгим regex.
 */
export class ConfigManager {
  readonly configDir: string;
  readonly providersDir: string;
  readonly dataDir: string;
  readonly logsDir: string;
  /** Отдельный файл секретов config/credentials.json (не попадает в git). */
  readonly credentialsFile: string;
  private readonly env: NodeJS.ProcessEnv;

  constructor(opts: ConfigManagerOptions) {
    this.configDir = path.resolve(opts.configDir);
    this.providersDir = path.join(this.configDir, 'providers');
    this.dataDir = path.resolve(opts.dataDir);
    this.logsDir = path.join(this.dataDir, 'logs');
    this.credentialsFile = path.join(this.configDir, 'credentials.json');
    this.env = opts.env ?? process.env;
    for (const dir of [this.configDir, this.providersDir, this.dataDir, this.logsDir]) {
      mkdirSync(dir, { recursive: true });
    }
  }

  /** Безопасное разрешение пути к файлу конфигурации провайдера. */
  resolveProviderPath(id: string): string {
    if (typeof id !== 'string' || !PROVIDER_ID_RE.test(id)) {
      throw configError(`Invalid provider id: ${JSON.stringify(id)}`, 'INVALID_PROVIDER_ID');
    }
    const file = path.resolve(this.providersDir, `${id}.json`);
    const root = this.providersDir + path.sep;
    if (!file.startsWith(root)) {
      throw configError(`Provider path escapes config dir: ${file}`, 'INVALID_PROVIDER_ID');
    }
    return file;
  }

  readJsonFile(file: string): unknown {
    if (!existsSync(file)) return null;
    let raw: string;
    try {
      raw = readFileSync(file, 'utf8');
    } catch (err) {
      throw configError(`Cannot read ${path.basename(file)}`, 'CONFIG_READ_ERROR', err);
    }
    try {
      return JSON.parse(raw);
    } catch (err) {
      throw configError(`Invalid JSON in ${path.basename(file)}`, 'INVALID_JSON', {
        file: path.basename(file),
        error: err instanceof Error ? err.message : String(err),
      });
    }
  }

  // ---------------------------------------------------------------- server

  loadServerConfig(): ServerSettings {
    const data = this.readJsonFile(path.join(this.configDir, 'server.json')) ?? {};
    let parsed: ServerSettings;
    try {
      parsed = serverConfigSchema.parse(data) as ServerSettings;
    } catch (err) {
      const message = err instanceof z.ZodError ? formatZodError(err) : String(err);
      throw configError(`Invalid server config: ${message}`, 'INVALID_SERVER_CONFIG', err);
    }
    return this.applyServerEnvOverrides(parsed);
  }

  /** Критические параметры можно переопределить через environment variables. */
  private applyServerEnvOverrides(cfg: ServerSettings): ServerSettings {
    const e = this.env;
    const out: ServerSettings = { ...cfg };
    const num = (key: string, min: number, max: number): number | undefined => {
      const raw = e[key];
      if (raw === undefined || raw === '') return undefined;
      const n = Number(raw);
      if (!Number.isInteger(n) || n < min || n > max) {
        throw configError(`Invalid ${key}: ${raw}`, 'INVALID_ENV_OVERRIDE');
      }
      return n;
    };
    if (e.MCP_HOST !== undefined && e.MCP_HOST !== '') out.host = e.MCP_HOST;
    const port = num('MCP_PORT', 1, 65535);
    if (port !== undefined) out.port = port;
    if (e.MCP_LOG_LEVEL !== undefined && e.MCP_LOG_LEVEL !== '') {
      if (!(LOG_LEVELS as readonly string[]).includes(e.MCP_LOG_LEVEL)) {
        throw configError(`Invalid MCP_LOG_LEVEL: ${e.MCP_LOG_LEVEL}`, 'INVALID_ENV_OVERRIDE');
      }
      out.logLevel = e.MCP_LOG_LEVEL as ServerSettings['logLevel'];
    }
    const retention = num('MCP_LOG_RETENTION_DAYS', 0, 365);
    if (retention !== undefined) out.logRetentionDays = retention;
    const maxLog = num('MCP_MAX_RESPONSE_LOG_SIZE', 1024, 10 * 1024 * 1024);
    if (maxLog !== undefined) out.maxResponseLogSize = maxLog;
    const timeout = num('MCP_REQUEST_TIMEOUT_MS', 100, 120_000);
    if (timeout !== undefined) out.requestTimeoutMs = timeout;
    const retries = num('MCP_DEFAULT_RETRY_COUNT', 0, 10);
    if (retries !== undefined) out.defaultRetryCount = retries;
    if (e.MCP_DEBUG === '1' || e.MCP_DEBUG === 'true') out.debug = true;
    return out;
  }

  saveServerConfig(patch: Partial<ServerSettings>): ServerSettings {
    const current = this.loadServerConfig();
    const nextRaw = { ...current, ...patch };
    let parsed: ServerSettings;
    try {
      parsed = serverConfigSchema.parse(nextRaw) as ServerSettings;
    } catch (err) {
      const message = err instanceof z.ZodError ? formatZodError(err) : String(err);
      throw configError(`Invalid server settings: ${message}`, 'INVALID_SERVER_CONFIG', err);
    }
    this.writeJsonAtomic(path.join(this.configDir, 'server.json'), parsed);
    return parsed;
  }

  // -------------------------------------------------------------- providers

  listProviderIds(): string[] {
    try {
      return readdirSync(this.providersDir)
        .filter((f) => f.endsWith('.json') && PROVIDER_ID_RE.test(f.slice(0, -5)))
        .map((f) => f.slice(0, -5))
        .sort();
    } catch {
      return [];
    }
  }

  getProviderConfig(id: string): ProviderConfig | null {
    const parsed = this.parseProviderFile(id);
    if (!parsed) return null;
    const stored = this.getCredentialsFor(id);
    // Секреты берутся из отдельного файла credentials.json; legacy-credentials
    // внутри файла провайдера используются только как fallback до миграции.
    const credentials = stored && Object.keys(stored).length > 0 ? stored : parsed.credentials;
    return { ...parsed, credentials };
  }

  /** Прочитать и проверить ТОЛЬКО файл провайдера config/providers/<id>.json. */
  private parseProviderFile(id: string): ProviderConfig | null {
    const file = this.resolveProviderPath(id);
    if (!existsSync(file)) return null;
    const data = this.readJsonFile(file);
    if (data === null) return null;
    let parsed;
    try {
      parsed = providerConfigFileSchema.parse(data);
    } catch (err) {
      const message = err instanceof z.ZodError ? formatZodError(err) : String(err);
      throw configError(`Invalid config for provider "${id}": ${message}`, 'INVALID_PROVIDER_CONFIG', err);
    }
    if (parsed.id !== id) {
      throw configError(`Provider id mismatch: file ${id}.json contains id "${parsed.id}"`, 'PROVIDER_ID_MISMATCH');
    }
    return parsed as ProviderConfig;
  }

  hasProviderConfig(id: string): boolean {
    return existsSync(this.resolveProviderPath(id));
  }

  writeProviderConfig(id: string, config: ProviderConfig): void {
    this.writeJsonAtomic(this.resolveProviderPath(id), config);
  }

  writeProviderConfigIfMissing(id: string, config: ProviderConfig): void {
    if (!this.hasProviderConfig(id)) this.writeProviderConfig(id, config);
  }

  /**
   * Обновить конфигурацию провайдера.
   * Секреты: значения credentials передаются только как новые значения (или пустая
   * строка для удаления) — маскированные значения никогда не пишутся обратно.
   * Credentials сохраняются в ОТДЕЛЬНЫЙ файл config/credentials.json.
   */
  updateProviderConfig(id: string, patch: Partial<ProviderConfig>): ProviderConfig {
    const current = this.getProviderConfig(id);
    if (!current) throw configError(`Provider "${id}" has no config file`, 'PROVIDER_NOT_CONFIGURED');

    const credentials = { ...(current.credentials ?? {}) };
    for (const [key, value] of Object.entries(patch.credentials ?? {})) {
      if (value === '' || value === undefined) delete credentials[key];
      else credentials[key] = value;
    }

    const next: ProviderConfig = {
      id,
      name: patch.name !== undefined ? patch.name : current.name,
      enabled: patch.enabled ?? current.enabled,
      baseUrl: patch.baseUrl !== undefined ? patch.baseUrl : current.baseUrl,
      settings: { ...(current.settings ?? {}), ...(patch.settings ?? {}) },
      tools: { ...(current.tools ?? {}), ...(patch.tools ?? {}) },
    };

    // В файл провайдера секреты не пишутся никогда
    this.writeProviderConfig(id, next);
    if (patch.credentials !== undefined) {
      this.saveProviderCredentials(id, credentials);
    }
    return { ...next, credentials };
  }

  // -------------------------------------------------------- credentials store

  /** Загрузить все секреты из config/credentials.json (файл не попадает в git). */
  loadCredentials(): Record<string, Record<string, string>> {
    const data = this.readJsonFile(this.credentialsFile);
    if (data === null) return {};
    try {
      return credentialsStoreSchema.parse(data);
    } catch (err) {
      const message = err instanceof z.ZodError ? formatZodError(err) : String(err);
      throw configError(
        `Invalid credentials file (${path.basename(this.credentialsFile)}): ${message}`,
        'INVALID_CREDENTIALS',
        err,
      );
    }
  }

  getCredentialsFor(id: string): Record<string, string> {
    return this.loadCredentials()[id] ?? {};
  }

  saveProviderCredentials(id: string, credentials: Record<string, string>): void {
    const all = this.loadCredentials();
    this.writeSecretAtomic(this.credentialsFile, { ...all, [id]: credentials });
  }

  /**
   * Перенести credentials из файлов провайдеров в отдельный config/credentials.json.
   * Вызывается при старте для конфигов, созданных до введения хранилища секретов.
   * Возвращает число перенесённых провайдеров.
   */
  migrateLegacyCredentials(): number {
    let moved = 0;
    for (const id of this.listProviderIds()) {
      const raw = this.parseProviderFile(id);
      const legacy = raw?.credentials;
      if (!legacy || Object.keys(legacy).length === 0) continue;
      const merged = { ...this.getCredentialsFor(id), ...legacy };
      this.saveProviderCredentials(id, merged);
      const { credentials: _dropped, ...clean } = raw as ProviderConfig & { credentials?: Record<string, string> };
      void _dropped;
      this.writeProviderConfig(
        id,
        clean as ProviderConfig,
      );
      moved++;
    }
    return moved;
  }

  // ---------------------------------------------------------------- helpers

  writeJsonAtomic(file: string, data: unknown): void {
    try {
      mkdirSync(path.dirname(file), { recursive: true });
      const tmp = `${file}.${process.pid}.tmp`;
      writeFileSync(tmp, `${JSON.stringify(data, null, 2)}\n`, 'utf8');
      renameSync(tmp, file);
    } catch (err) {
      throw configError(`Cannot write ${path.basename(file)}`, 'CONFIG_WRITE_ERROR', err);
    }
  }

  /** Атомарная запись секретов с правами 0600 (читает только владелец). */
  writeSecretAtomic(file: string, data: unknown): void {
    try {
      mkdirSync(path.dirname(file), { recursive: true });
      const tmp = `${file}.${process.pid}.tmp`;
      writeFileSync(tmp, `${JSON.stringify(data, null, 2)}\n`, { encoding: 'utf8', mode: 0o600 });
      renameSync(tmp, file);
      chmodSync(file, 0o600);
    } catch (err) {
      throw configError(`Cannot write ${path.basename(file)}`, 'SECRETS_WRITE_ERROR', err);
    }
  }

  /** Значение credential из env (если задано и непустое). */
  getEnvCredential(envName: string): string | undefined {
    const value = this.env[envName];
    if (value === undefined || value === null || value.trim() === '') return undefined;
    return value;
  }
}