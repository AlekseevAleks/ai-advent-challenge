import path from 'node:path';
import { ConfigManager } from '../core/config/config-manager.js';
import type { ServerSettings } from '../core/types.js';
import { HttpClient } from '../core/http/http-client.js';
import { Logger } from '../core/logging/logger.js';
import { RequestLogger } from '../core/logging/request-logger.js';
import { ProviderRegistry } from '../core/registry/provider-registry.js';
import { BUILTIN_PROVIDERS } from '../../providers/index.js';
import { McpGateway } from './mcp-server.js';

export interface Runtime {
  settings: ServerSettings;
  configDir: string;
  dataDir: string;
  logger: Logger;
  requestLogger: RequestLogger;
  httpClient: HttpClient;
  configManager: ConfigManager;
  registry: ProviderRegistry;
  gateway: McpGateway;
  startedAt: number;
}

export interface BuildRuntimeOptions {
  configDir?: string;
  dataDir?: string;
  /** false — не писать в stdout/stderr (нужно для stdio MCP-режима). */
  consoleOutput?: boolean;
}

/** Поднять всё runtime-окружение: конфиг → логи → HTTP → registry → MCP. */
export async function buildRuntime(opts: BuildRuntimeOptions = {}): Promise<Runtime> {
  const configDir = opts.configDir ?? process.env.MCP_CONFIG_DIR ?? path.resolve(process.cwd(), 'config');
  const dataDir = opts.dataDir ?? process.env.MCP_DATA_DIR ?? path.resolve(process.cwd(), 'data');

  const configManager = new ConfigManager({ configDir, dataDir });
  const settings = configManager.loadServerConfig();

  const logger = new Logger({
    level: settings.logLevel,
    file: path.join(dataDir, 'logs', 'server.log'),
    scope: 'gateway',
    consoleOutput: opts.consoleOutput ?? true,
  });

  const migrated = configManager.migrateLegacyCredentials();
  if (migrated > 0) {
    logger.info(`[runtime] migrated credentials of ${migrated} provider(s) into ${path.basename(configManager.credentialsFile)}`);
  }

  const requestLogger = new RequestLogger({
    logsDir: path.join(dataDir, 'logs'),
    maxResponseLogSize: settings.maxResponseLogSize,
    retentionDays: settings.logRetentionDays,
    logger: logger.child('logs'),
  });

  const pruned = requestLogger.prune();
  if (pruned > 0) logger.info(`[runtime] pruned ${pruned} old log file(s)`);

  const httpClient = new HttpClient({
    requestLogger,
    logger: logger.child('http'),
    defaultTimeoutMs: settings.requestTimeoutMs,
    defaultRetries: settings.defaultRetryCount,
    defaultRetryBackoffMs: settings.retryBackoffMs,
  });

  const registry = new ProviderRegistry({ configManager, httpClient, logger: logger.child('registry') });
  for (const cls of BUILTIN_PROVIDERS) registry.registerProviderClass(cls);

  await registry.loadProviders();
  await registry.initializeAll();

  const gateway = new McpGateway(registry, logger.child('mcp'));

  return { settings, configDir, dataDir, logger, requestLogger, httpClient, configManager, registry, gateway, startedAt: Date.now() };
}