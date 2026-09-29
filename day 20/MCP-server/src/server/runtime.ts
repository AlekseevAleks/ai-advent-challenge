import path from 'node:path';
import { ConfigManager } from '../core/config/config-manager.js';
import type { ServerSettings } from '../core/types.js';
import { HttpClient } from '../core/http/http-client.js';
import { Logger } from '../core/logging/logger.js';
import { RequestLogger } from '../core/logging/request-logger.js';
import { ProviderRegistry } from '../core/registry/provider-registry.js';
import { BUILTIN_PROVIDERS } from '../../providers/index.js';
import { McpGateway } from './mcp-server.js';
import {
  TaskExecutor,
  TaskManager,
  Scheduler,
  TaskStorage,
} from '../core/scheduler/index.js';
import { LlmSettingsStore } from '../core/llm/llm-settings-store.js';
import { LlmService } from '../core/llm/llm-service.js';
import { OutputFileService } from '../core/files/output-file.js';
import {
  PipelineExecutor,
  PipelineRegistry,
  PipelineStorage,
  PipelineValidator,
} from '../core/pipeline/index.js';
import { createPipelineToolRunner } from './pipeline-dispatcher.js';
import { CORE_TOOL_NAMES } from './mcp-core-tools.js';

let runtimeRef: Runtime | undefined;

const schedulerSettingsOf = (): ServerSettings['scheduler'] => runtimeRef?.settings.scheduler!;

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
  taskStorage: TaskStorage;
  taskExecutor: TaskExecutor;
  taskManager: TaskManager;
  scheduler: Scheduler;
  llm: LlmService;
  pipelineStorage: PipelineStorage;
  pipelineRegistry: PipelineRegistry;
  pipelineExecutor: PipelineExecutor;
  startedAt: number;
}

export interface BuildRuntimeOptions {
  configDir?: string;
  dataDir?: string;
  /** false — не писать в stdout/stderr (нужно для stdio MCP-режима). */
  consoleOutput?: boolean;
  /** Переопределение текущего времени (тесты Scheduler). */
  now?: () => number;
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

  // ---------------------------------------------------------- LLM
  const llmStore = new LlmSettingsStore(dataDir);
  const llm = new LlmService({
    store: llmStore,
    http: httpClient,
    logger: logger.child('llm'),
    getTimeoutMs: () => Math.max(settings.requestTimeoutMs, 30_000),
  });

  const outputFiles = new OutputFileService(path.join(dataDir, 'output'));

  // ------------------------------------------------------- Pipelines
  const pipelineStorage = new PipelineStorage(path.join(dataDir, 'pipelines.db'));
  const prunedPipelines = pipelineStorage.pruneExecutions(500);
  if (prunedPipelines > 0) logger.info(`[Pipeline] pruned ${prunedPipelines} old execution(s)`);
  const pipelineRegistry = new PipelineRegistry(pipelineStorage);
  const pipelineValidator = new PipelineValidator({
    isToolKnown: (name) => registry.isToolEnabled(name) || CORE_TOOL_NAMES.has(name),
    isToolEnabled: (name) => (CORE_TOOL_NAMES.has(name) ? true : registry.isToolEnabled(name)),
  });
  const pipelineExecutor = new PipelineExecutor({
    storage: pipelineStorage,
    registry: pipelineRegistry,
    validator: pipelineValidator,
    logger: logger.child('pipeline'),
    callTool: createPipelineToolRunner(registry, { llmService: llm, fileService: outputFiles }),
  });

  // ---------------------------------------------------------- Scheduler
  const taskStorage = new TaskStorage(path.join(dataDir, 'scheduler.db'));
  const prunedExec = taskStorage.pruneExecutions(settings.scheduler.maxStoredExecutionsPerTask, settings.scheduler.executionRetentionDays);
  if (prunedExec > 0) logger.info(`[Scheduler] pruned ${prunedExec} old execution(s)`);

  const taskExecutor = new TaskExecutor({
    registry,
    storage: taskStorage,
    logger: logger.child('scheduler'),
    getSettings: schedulerSettingsOf,
    pipelineExecutor,
    now: opts.now,
  });

  let schedulerRef: Scheduler | undefined;
  const taskManager = new TaskManager({
    storage: taskStorage,
    executor: taskExecutor,
    registry,
    logger: logger.child('scheduler'),
    getSettings: schedulerSettingsOf,
    pipelineRegistry,
    onTaskChanged: () => schedulerRef?.notifyChanged(),
    now: opts.now,
  });

  const scheduler = new Scheduler({
    storage: taskStorage,
    taskManager,
    logger: logger.child('scheduler'),
    getSettings: schedulerSettingsOf,
    now: opts.now,
  });
  schedulerRef = scheduler;

  const gateway = new McpGateway(registry, logger.child('mcp'), {
    taskManager,
    configManager,
    llmService: llm,
    fileService: outputFiles,
    pipelineExecutor,
    pipelineRegistry,
  });

  const runtime: Runtime = {
    settings,
    configDir,
    dataDir,
    logger,
    requestLogger,
    httpClient,
    configManager,
    registry,
    gateway,
    taskStorage,
    taskExecutor,
    taskManager,
    scheduler,
    llm,
    pipelineStorage,
    pipelineRegistry,
    pipelineExecutor,
    startedAt: Date.now(),
  };
  runtimeRef = runtime;
  return runtime;
}