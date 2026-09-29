// api/types.ts — контракт API из web/SPEC.md (дословно).
export interface ServerStatus {
  ok: boolean; name: string; version: string; running: boolean;
  host: string; port: number; mcpEndpoint: string; webUi: string; uptimeSeconds: number;
  providers: { total: number; enabled: number; disabled: number };
  tools: { total: number; enabled: number };
  requests: { today: number; errorsToday: number; avgLatencyMs: number };
  lastRequests: LogEntry[];
}
export interface ConfigField {
  key: string; label: string; type: 'string' | 'number' | 'boolean';
  description?: string; default?: string | number | boolean; required?: boolean;
  secret?: boolean; env?: string; unit?: string; placeholder?: string;
}
export interface ConfigSchema {
  fields: ConfigField[]; settingsFields: ConfigField[]; credentialFields: ConfigField[];
}
export interface CredentialState { value: string; set: boolean; overridden: boolean; env?: string }
export interface ProviderHealth {
  status: 'ok' | 'error' | 'unknown'; message?: string; checkedAt?: string;
  durationMs?: number; statusCode?: number;
}
export interface ProviderRuntimeTool {
  name: string; description: string;
  inputSchema: { type: 'object'; properties?: Record<string, unknown>; required?: string[]; additionalProperties?: boolean };
  enabled: boolean; settings: Record<string, unknown>;
}
export interface ProviderRuntimeState {
  id: string; name: string; description: string; version: string; enabled: boolean; baseUrl?: string;
  configSchema: ConfigSchema; settings: Record<string, unknown>;
  credentials: Record<string, CredentialState>;
  health: ProviderHealth; tools: ProviderRuntimeTool[]; toolsCount: number; enabledToolsCount: number;
}
export interface LogErrorInfo { kind: string; code: string; message: string; retryAfter?: number }
export interface LogEntry {
  id: string; timestamp: string; direction: 'mcp' | 'test' | 'health';
  provider: string; providerName?: string; tool?: string; method: string;
  url: string; status?: number; durationMs?: number; success: boolean;
  error?: LogErrorInfo;
  request?: { headers?: Record<string, string>; body?: string; bodyTruncated?: boolean };
  response?: { headers?: Record<string, string>; body?: string; bodyTruncated?: boolean };
  attempts?: number;
}
export interface LogQueryResult { items: LogEntry[]; total: number; offset: number; limit: number }

// --------------------------------------------------------------- scheduler

export type TaskScheduleType = 'once' | 'cron';
export type TaskStatus = 'active' | 'paused' | 'completed' | 'error';

export interface TaskSchedule {
  type: TaskScheduleType;
  executeAt?: string;
  cron?: string;
  timezone?: string;
}

export interface TaskAction {
  type: 'provider_tool' | 'pipeline';
  provider?: string;
  tool?: string;
  pipeline?: string;
  input: unknown;
}

export interface TaskAggregation {
  enabled?: boolean;
  strategy?: string;
  window?: string;
}

export interface ScheduledTask {
  id: string;
  name: string;
  description?: string;
  enabled: boolean;
  schedule: TaskSchedule;
  action: TaskAction;
  aggregation?: TaskAggregation;
  createdAt: string;
  updatedAt: string;
  lastRunAt?: string;
  nextRunAt?: string;
  status: TaskStatus;
  running: boolean;
  version: number;
}

export interface TaskExecution {
  id: string;
  taskId: string;
  startedAt: string;
  finishedAt?: string;
  status: 'running' | 'success' | 'error';
  durationMs?: number;
  result?: unknown;
  error?: string;
}

export interface TaskHistoryPage {
  items: TaskExecution[];
  total: number;
  offset: number;
  limit: number;
}

export interface NumericStats {
  count: number;
  min?: number;
  max?: number;
  avg?: number;
  sum?: number;
  latest?: number;
  first?: number;
}

export interface CategoryCounts {
  total: number;
  values: Record<string, number>;
}

export interface TaskSummary {
  taskId: string;
  window: { label: string; from?: string; to?: string };
  executions: { total: number; success: number; error: number };
  numericSeries: Record<string, NumericStats>;
  categories: Record<string, CategoryCounts>;
  summaryText: string;
}

export type SummaryWindow = '1h' | '24h' | '7d' | '30d' | 'all' | 'custom';

export interface SchedulerRetrySettings {
  enabled: boolean;
  maxAttempts: number;
  delayMs: number;
}

export interface SchedulerSettings {
  enabled: boolean;
  tickIntervalMs: number;
  maxStoredExecutionsPerTask: number;
  executionRetentionDays: number;
  retry: SchedulerRetrySettings;
}

export type TaskInput = {
  id?: string;
  name: string;
  description?: string;
  enabled?: boolean;
  schedule: TaskSchedule;
  action: TaskAction;
  aggregation?: TaskAggregation;
};

export interface ServerSettingsResponse {
  host: string; port: number; logLevel: 'debug' | 'info' | 'warn' | 'error' | 'silent';
  logRetentionDays: number; maxResponseLogSize: number; requestTimeoutMs: number;
  defaultRetryCount: number; retryBackoffMs: number; corsEnabled: boolean;
  corsOrigins: string[]; debug: boolean;
  scheduler: SchedulerSettings;
  restartRequired?: string[];
}

/** Scheduler tool (тул для работы с задачами) и его состояние. */
export interface SchedulerToolInfo {
  name: string;
  description: string;
  inputSchema: { type: 'object'; properties?: Record<string, unknown>; required?: string[]; additionalProperties?: boolean };
  enabled: boolean;
}

/** Pipeline tool (тул для работы с пайплайнами) и его состояние. */
export interface PipelineToolInfo {
  name: string;
  description: string;
  inputSchema: { type: 'object'; properties?: Record<string, unknown>; required?: string[]; additionalProperties?: boolean };
  enabled: boolean;
}

// --------------------------------------------------------------- LLM

export interface LlmPublicSettings {
  provider: 'openai';
  apiUrl: string;
  model: string;
  configured: boolean;
}

export interface LlmCheckResult {
  ok: boolean;
  status: 'connected' | 'error';
  message: string;
}

export interface LlmSaveResult {
  success: boolean;
  configured: boolean;
  provider: 'openai';
  model: string;
}

export type LlmSettingsPatch = {
  apiUrl?: string;
  apiKey?: string;
  model?: string;
};

// ------------------------------------------------------------ Pipelines

export interface PipelineStepInput {
  id: string;
  tool: string;
  input: unknown;
}

export interface Pipeline {
  id: string;
  name: string;
  description?: string;
  enabled: boolean;
  steps: PipelineStepInput[];
  createdAt: string;
  updatedAt: string;
  lastRunAt?: string;
}

export interface PipelineStepResult {
  id: string;
  tool: string;
  status: 'completed' | 'failed' | 'skipped';
  error?: string;
}

export interface PipelineExecution {
  id: string;
  pipelineId: string;
  startedAt: string;
  finishedAt?: string;
  status: 'running' | 'completed' | 'failed';
  steps: PipelineStepResult[];
  durationMs?: number;
  failedStep?: string;
  error?: string;
}

export interface PipelineRunResult {
  executionId: string;
  pipelineId: string;
  status: PipelineExecution['status'];
  steps: PipelineStepResult[];
  durationMs?: number;
  error?: string;
  message?: string;
}

export interface PipelineHistoryPage {
  items: PipelineExecution[];
  total: number;
  offset: number;
  limit: number;
}

export type PipelineInputBody = {
  id?: string;
  name: string;
  description?: string;
  enabled?: boolean;
  steps: PipelineStepInput[];
};