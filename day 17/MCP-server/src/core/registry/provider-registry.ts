import type { ConfigManager } from '../config/config-manager.js';
import type { HttpClient } from '../http/http-client.js';
import type { Logger } from '../logging/logger.js';
import { configError, userError } from '../errors.js';
import { maskSecret, redactText } from '../util/redact.js';
import type { ProviderConfig, ProviderToolConfig } from '../types.js';
import type {
  ApiProvider,
  ProviderHealth,
  ProviderRuntimeState,
  ProviderRuntimeTool,
  ResolvedTool,
  ToolDefinition,
} from '../providers/types.js';

export type ProviderClass = new (http: HttpClient) => ApiProvider;

export interface ProviderRegistryOptions {
  configManager: ConfigManager;
  httpClient: HttpClient;
  logger: Logger;
}

/**
 * ProviderRegistry — ядро системы провайдеров:
 *  - находит зарегистрированные классы провайдеров (встроенные + будущие plugins);
 *  - загружает их конфигурацию из config/providers/*.json;
 *  - инициализирует enabled-провайдеры;
 *  - собирает tools всех активных провайдеров и маршрутизирует вызовы;
 *  - поддерживает hot reload (enable/disable + отключение отдельных tools без рестарта).
 */
export class ProviderRegistry {
  private readonly classes = new Map<string, ProviderClass>();
  private readonly instances = new Map<string, ApiProvider>();
  private readonly initialized = new Set<string>();
  private readonly health = new Map<string, ProviderHealth>();
  private readonly envOverridden = new Map<string, Record<string, boolean>>();
  private readonly resolver = new Map<string, { providerId: string; tool: ToolDefinition }>();

  constructor(private readonly opts: ProviderRegistryOptions) {}

  /** Регистрация класса провайдера (встроенный или будущий внешний plugin). */
  registerProviderClass(cls: ProviderClass): void {
    const probe = new cls(this.opts.httpClient);
    if (this.classes.has(probe.id)) {
      this.opts.logger.warn(`[registry] provider "${probe.id}" already registered, skipping`);
      return;
    }
    this.classes.set(probe.id, cls);
    this.opts.logger.debug(`[registry] registered provider class "${probe.id}"`);
  }

  getProviderIds(): string[] {
    return [...this.classes.keys()].sort();
  }

  hasProvider(id: string): boolean {
    return this.classes.has(id);
  }

  /** Создать экземпляры, при необходимости записать дефолтные конфиги. */
  async loadProviders(): Promise<void> {
    for (const [id, cls] of this.classes) {
      const cfg = safeGetConfig(() => this.opts.configManager.getProviderConfig(id));
      if (!cfg) {
        const probe = new cls(this.opts.httpClient);
        this.opts.configManager.writeProviderConfigIfMissing(id, probe.getDefaultConfig());
        this.opts.logger.info(`[registry] created default config for provider "${id}"`);
      }
      this.instances.set(id, new cls(this.opts.httpClient));
    }
  }

  /** Инициализировать все enabled-провайдеры и построить индекс tools. */
  async initializeAll(): Promise<void> {
    for (const id of this.instances.keys()) {
      if (this.isEnabled(id)) await this.initProvider(id);
    }
    this.rebuildResolver();
  }

  /** Применить изменения конфигурации без перезапуска сервера (hot reload). */
  async reloadProvider(id: string): Promise<void> {
    const instance = this.instances.get(id);
    if (!instance) throw configError(`Unknown provider "${id}"`, 'UNKNOWN_PROVIDER');
    const enabled = this.isEnabled(id);
    if (enabled) {
      await this.initProvider(id);
      this.opts.logger.info(`[registry] provider "${id}" reloaded`);
    } else {
      if (this.initialized.has(id)) {
        await instance.dispose();
        this.initialized.delete(id);
        this.opts.logger.info(`[registry] provider "${id}" disposed`);
      }
      this.health.delete(id);
    }
    this.rebuildResolver();
  }

  async setProviderEnabled(id: string, enabled: boolean): Promise<void> {
    const cfg = this.opts.configManager.getProviderConfig(id);
    if (!cfg) throw configError(`Provider "${id}" has no config`, 'PROVIDER_NOT_CONFIGURED');
    await this.opts.configManager.updateProviderConfig(id, { enabled });
    await this.reloadProvider(id);
  }

  async updateProviderConfig(id: string, patch: Partial<ProviderConfig>): Promise<void> {
    if (!this.hasProvider(id)) throw configError(`Unknown provider "${id}"`, 'UNKNOWN_PROVIDER');
    this.opts.configManager.updateProviderConfig(id, patch);
    await this.reloadProvider(id);
  }

  /** Изменение enabled/settings конкретного tool; применяется без рестарта. */
  async updateToolConfig(id: string, toolId: string, patch: { enabled?: boolean; settings?: Record<string, unknown> }): Promise<ProviderRuntimeTool> {
    const instance = this.instances.get(id);
    if (!instance) throw configError(`Unknown provider "${id}"`, 'UNKNOWN_PROVIDER');
    const tool = instance.getTools().find((t) => t.name === toolId);
    if (!tool) throw configError(`Tool "${toolId}" not found in provider "${id}"`, 'UNKNOWN_TOOL');

    const cfg = this.opts.configManager.getProviderConfig(id);
    const tools = { ...(cfg?.tools ?? {}) };
    const existing = { ...(tools[toolId] ?? {}) } as ProviderToolConfig;
    tools[toolId] = {
      enabled: patch.enabled ?? existing.enabled,
      settings: { ...(existing.settings ?? {}), ...(patch.settings ?? {}) },
    };
    this.opts.configManager.updateProviderConfig(id, { tools });
    this.rebuildResolver();
    return this.getRuntimeTool(id, tool);
  }

  getProvider(id: string): ApiProvider | undefined {
    return this.instances.get(id);
  }

  isEnabled(id: string): boolean {
    const cfg = this.opts.configManager.getProviderConfig(id);
    return !!cfg?.enabled;
  }

  isInitialized(id: string): boolean {
    return this.initialized.has(id);
  }

  isToolEnabled(toolName: string): boolean {
    return this.resolver.has(toolName);
  }

  /** Все tools активных (enabled) провайдеров с учётом конфигурации. */
  getTools(): ResolvedTool[] {
    const result: ResolvedTool[] = [];
    for (const [id, instance] of this.instances) {
      if (!this.initialized.has(id)) continue;
      const cfg = this.opts.configManager.getProviderConfig(id);
      const toolsCfg = cfg?.tools ?? {};
      for (const tool of instance.getTools()) {
        const tc = toolsCfg[tool.name] ?? {};
        result.push({
          tool,
          providerId: id,
          enabled: tc.enabled !== false,
          settings: tc.settings ?? {},
        });
      }
    }
    return result;
  }

  /** Tools, видимые MCP-клиенту: только enabled. */
  getMcpTools(): Array<{ name: string; description?: string; inputSchema: ToolDefinition['inputSchema'] }> {
    return this.getTools()
      .filter((t) => t.enabled)
      .map((t) => t.tool);
  }

  /** Маршрутизация вызова tool к нужному провайдеру. */
  async executeTool(toolName: string, input: unknown, direction: 'mcp' = 'mcp'): Promise<unknown> {
    const entry = this.resolver.get(toolName);
    if (!entry) throw userError(`Unknown or disabled tool: ${toolName}`, 'UNKNOWN_TOOL');
    const instance = this.instances.get(entry.providerId);
    if (!instance) throw userError(`Provider "${entry.providerId}" is not active`, 'PROVIDER_INACTIVE');
    void direction;
    const cfg = this.opts.configManager.getProviderConfig(entry.providerId);
    const tc = cfg?.tools?.[toolName] ?? {};
    return instance.executeTool(toolName, input ?? {}, { ...tc });
  }

  /** Real health check через провайдера (Test Connection). */
  async testConnection(id: string): Promise<ProviderHealth> {
    const instance = this.instances.get(id);
    if (!instance) throw configError(`Unknown provider "${id}"`, 'UNKNOWN_PROVIDER');
    const startedAt = Date.now();
    let health: ProviderHealth;
    try {
      const result = await instance.healthCheck();
      health = { ...result, checkedAt: new Date().toISOString(), durationMs: Date.now() - startedAt };
    } catch (err) {
      const message = redactText(err instanceof Error ? err.message : String(err));
      health = { status: 'error', message, checkedAt: new Date().toISOString(), durationMs: Date.now() - startedAt };
    }
    this.health.set(id, health);
    return health;
  }

  getHealth(id: string): ProviderHealth | undefined {
    return this.health.get(id);
  }

  getRuntimeState(): ProviderRuntimeState[] {
    return [...this.instances.keys()].sort().map((id) => this.buildRuntimeState(id));
  }

  getProviderRuntimeState(id: string): ProviderRuntimeState | undefined {
    if (!this.instances.has(id)) return undefined;
    return this.buildRuntimeState(id);
  }

  async disposeAll(): Promise<void> {
    for (const [id, instance] of this.instances) {
      if (this.initialized.has(id)) {
        try {
          await instance.dispose();
        } catch (err) {
          this.opts.logger.error(`[registry] dispose failed for "${id}"`, {
            error: err instanceof Error ? err.message : String(err),
          });
        }
      }
    }
    this.initialized.clear();
  }

  // ------------------------------------------------------------ internals

  private async initProvider(id: string): Promise<void> {
    const instance = this.instances.get(id);
    if (!instance) throw configError(`Unknown provider "${id}"`, 'UNKNOWN_PROVIDER');
    const cfg = this.opts.configManager.getProviderConfig(id);
    if (!cfg) throw configError(`Provider "${id}" has no config`, 'PROVIDER_NOT_CONFIGURED');
    const effective = this.applyEnvCredentialOverrides(id, cfg);
    try {
      await instance.initialize(effective);
    } catch (err) {
      this.initialized.delete(id);
      const message = redactText(err instanceof Error ? err.message : String(err));
      throw configError(`Provider "${id}" failed to initialize: ${message}`, 'PROVIDER_INIT_FAILED', err);
    }
    this.initialized.add(id);
    this.health.delete(id);
  }

  /** GITHUB_TOKEN и подобные env-переменные переопределяют credentials из файла. */
  private applyEnvCredentialOverrides(id: string, cfg: ProviderConfig): ProviderConfig {
    const instance = this.instances.get(id);
    if (!instance) return cfg;
    const envMap = instance.getCredentialEnv();
    const overridden: Record<string, boolean> = this.envOverridden.get(id) ?? {};
    let changed = false;
    for (const [key, envName] of Object.entries(envMap)) {
      const value = this.opts.configManager.getEnvCredential(envName);
      if (value !== undefined) {
        overridden[key] = true;
        changed = true;
      } else {
        delete overridden[key];
      }
    }
    this.envOverridden.set(id, overridden);
    if (!changed) return cfg;
    const envCfg: ProviderConfig = {
      ...cfg,
      credentials: {
        ...(cfg.credentials ?? {}),
        ...Object.fromEntries(
          Object.entries(envMap)
            .filter(([key]) => overridden[key])
            .map(([key, envName]) => [key, this.opts.configManager.getEnvCredential(envName) as string]),
        ),
      },
    };
    return envCfg;
  }

  private rebuildResolver(): void {
    this.resolver.clear();
    for (const resolved of this.getTools()) {
      if (!resolved.enabled) continue;
      if (this.resolver.has(resolved.tool.name)) {
        this.opts.logger.warn(
          `[registry] duplicate tool name "${resolved.tool.name}" (${this.resolver.get(resolved.tool.name)?.providerId} and ${resolved.providerId}); keeping the first`,
        );
        continue;
      }
      this.resolver.set(resolved.tool.name, { providerId: resolved.providerId, tool: resolved.tool });
    }
  }

  private getRuntimeTool(id: string, tool: ToolDefinition): ProviderRuntimeTool {
    const cfg = this.opts.configManager.getProviderConfig(id);
    const tc = cfg?.tools?.[tool.name] ?? {};
    return {
      ...tool,
      enabled: tc.enabled !== false,
      settings: tc.settings ?? {},
    };
  }

  private buildRuntimeState(id: string): ProviderRuntimeState {
    const instance = this.instances.get(id);
    if (!instance) throw configError(`Unknown provider "${id}"`, 'UNKNOWN_PROVIDER');
    const cfg = this.opts.configManager.getProviderConfig(id) ?? { id, enabled: false };
    const schema = instance.getConfigSchema();
    const envMap = instance.getCredentialEnv();
    const overriddenKeys = this.envOverridden.get(id) ?? {};

    const credentials: ProviderRuntimeState['credentials'] = {};
    for (const field of schema.credentialFields) {
      const envName = envMap[field.key];
      const envValue = envName ? this.opts.configManager.getEnvCredential(envName) : undefined;
      const overridden = overriddenKeys[field.key] === true;
      const stored = cfg.credentials?.[field.key] ?? '';
      const effective = overridden ? (envValue ?? '') : stored;
      credentials[field.key] = {
        value: maskSecret(effective),
        set: overridden || !!stored,
        overridden,
        env: envName,
      };
    }

    const tools: ProviderRuntimeTool[] = instance.getTools().map((tool) => this.getRuntimeTool(id, tool));
    const toolsCount = tools.length;
    const enabledToolsCount = tools.filter((t) => t.enabled).length;

    return {
      id,
      name: cfg.name ?? instance.name,
      description: instance.description,
      version: instance.version,
      enabled: cfg.enabled !== false,
      baseUrl: cfg.baseUrl || instance.getBaseUrl(),
      configSchema: schema,
      settings: cfg.settings ?? {},
      credentials,
      health: this.health.get(id) ?? { status: 'unknown' },
      tools,
      toolsCount,
      enabledToolsCount,
    };
  }
}

function safeGetConfig<T>(fn: () => T): T | undefined {
  try {
    return fn();
  } catch (err) {
    // Конфигурация сломана — пусть упадёт с понятной ошибкой на уровне провайдера.
    throw err;
  }
}