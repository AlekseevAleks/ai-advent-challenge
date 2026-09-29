// fetch-обёртка над REST API: JSON, ошибки вида {error:{code,message}}, toast на ошибки.
import type {
  LlmCheckResult,
  LlmPublicSettings,
  LlmSaveResult,
  LlmSettingsPatch,
  LogEntry,
  LogQueryResult,
  Pipeline,
  PipelineExecution,
  PipelineHistoryPage,
  PipelineInputBody,
  PipelineRunResult,
  PipelineToolInfo,
  ProviderHealth,
  ProviderRuntimeState,
  ProviderRuntimeTool,
  ScheduledTask,
  SchedulerToolInfo,
  ServerSettingsResponse,
  ServerStatus,
  SummaryWindow,
  TaskExecution,
  TaskHistoryPage,
  TaskInput,
  TaskSummary,
} from './types.js';
import { toast } from '../components/ui.js';

export interface ApiErrorBody {
  error?: { code?: string; kind?: string; message?: string; retryAfter?: number };
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly kind?: string;
  readonly retryAfter?: number;

  constructor(status: number, code: string, message: string, kind?: string, retryAfter?: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.kind = kind;
    this.retryAfter = retryAfter;
  }
}

export interface RequestOptions extends RequestInit {
  /** Не показывать toast при ошибке (например, тихий авто-refresh). */
  silent?: boolean;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { silent = false, ...init } = options;
  let res: Response;
  try {
    const headers = new Headers(init.headers);
    const hasBody = init.body !== undefined && init.body !== null && init.body !== '';
    if (hasBody && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
    res = await fetch(path, { ...init, headers });
  } catch (err) {
    if (options.signal?.aborted) throw new ApiError(0, 'ABORTED', 'Request aborted');
    const message = err instanceof Error ? err.message : 'Network error';
    if (!silent) toast(message, 'error');
    throw new ApiError(0, 'NETWORK_ERROR', message);
  }

  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text) as unknown;
    } catch {
      data = null;
    }
  }

  if (!res.ok) {
    const body = data as ApiErrorBody | null;
    const message = body?.error?.message ?? `Request failed with status ${res.status}`;
    const code = body?.error?.code ?? `HTTP_${res.status}`;
    if (!silent) toast(message, 'error');
    throw new ApiError(res.status, code, message, body?.error?.kind, body?.error?.retryAfter);
  }
  return data as T;
}

export type QueryValue = string | number | boolean | undefined | null;

export function buildQuery(params: Record<string, QueryValue>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') {
      search.set(key, String(value));
    }
  }
  const qs = search.toString();
  return qs ? `?${qs}` : '';
}

export interface HealthResponse {
  ok: boolean;
  version: string;
  uptimeSeconds: number;
}

export interface LogQuery {
  search?: string;
  provider?: string;
  tool?: string;
  status?: number;
  result?: 'success' | 'error' | 'all';
  from?: string;
  to?: string;
  offset?: number;
  limit?: number;
}

export type ProviderUpdate = {
  enabled?: boolean;
  name?: string;
  baseUrl?: string;
  settings?: Record<string, unknown>;
  credentials?: Record<string, string>;
  tools?: Record<string, { enabled?: boolean; settings?: Record<string, unknown> }>;
};

export type ToolUpdate = { enabled?: boolean; settings?: Record<string, unknown> };

export type ServerSettingsUpdate = Partial<ServerSettingsResponse>;

export type SettingsSaveResult = ServerSettingsResponse & { restartRequired: string[] };

export const api = {
  getStatus(): Promise<ServerStatus> {
    return request('/api/server/status');
  },
  getHealth(): Promise<HealthResponse> {
    return request('/api/health');
  },
  getProviders(): Promise<ProviderRuntimeState[]> {
    return request('/api/providers');
  },
  getProvider(id: string): Promise<ProviderRuntimeState> {
    return request(`/api/providers/${encodeURIComponent(id)}`);
  },
  updateProvider(id: string, body: ProviderUpdate): Promise<ProviderRuntimeState> {
    return request(`/api/providers/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(body) });
  },
  enableProvider(id: string): Promise<ProviderRuntimeState> {
    return request(`/api/providers/${encodeURIComponent(id)}/enable`, { method: 'POST' });
  },
  disableProvider(id: string): Promise<ProviderRuntimeState> {
    return request(`/api/providers/${encodeURIComponent(id)}/disable`, { method: 'POST' });
  },
  testProvider(id: string): Promise<ProviderHealth & { ok: boolean }> {
    return request(`/api/providers/${encodeURIComponent(id)}/test`, { method: 'POST' });
  },
  getProviderTools(id: string): Promise<ProviderRuntimeTool[]> {
    return request(`/api/providers/${encodeURIComponent(id)}/tools`);
  },
  updateProviderTool(id: string, toolId: string, body: ToolUpdate): Promise<ProviderRuntimeTool> {
    return request(`/api/providers/${encodeURIComponent(id)}/tools/${encodeURIComponent(toolId)}`, {
      method: 'PUT',
      body: JSON.stringify(body),
    });
  },
  getLogs(query: LogQuery = {}, options?: RequestOptions): Promise<LogQueryResult> {
    return request(`/api/logs${buildQuery({ ...query })}`, options);
  },
  getLog(id: string): Promise<LogEntry> {
    return request(`/api/logs/${encodeURIComponent(id)}`);
  },
  clearLogs(): Promise<{ deleted: number; message?: string }> {
    return request('/api/logs', { method: 'DELETE', body: JSON.stringify({ confirm: true }) });
  },
  getSettings(): Promise<ServerSettingsResponse> {
    return request('/api/server/settings');
  },
  updateSettings(patch: ServerSettingsUpdate): Promise<SettingsSaveResult> {
    return request(`/api/server/settings`, { method: 'PUT', body: JSON.stringify(patch) });
  },
  // ----------------------------------------------------------- Scheduled Tasks
  listTasks(): Promise<{ items: ScheduledTask[]; total: number }> {
    return request('/api/tasks');
  },
  createTask(body: TaskInput): Promise<ScheduledTask> {
    return request('/api/tasks', { method: 'POST', body: JSON.stringify(body) });
  },
  getTask(id: string): Promise<ScheduledTask> {
    return request(`/api/tasks/${encodeURIComponent(id)}`);
  },
  updateTask(id: string, patch: Partial<TaskInput>): Promise<ScheduledTask> {
    return request(`/api/tasks/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(patch) });
  },
  deleteTask(id: string): Promise<{ deleted: boolean }> {
    return request(`/api/tasks/${encodeURIComponent(id)}`, { method: 'DELETE' });
  },
  pauseTask(id: string): Promise<ScheduledTask> {
    return request(`/api/tasks/${encodeURIComponent(id)}/pause`, { method: 'POST' });
  },
  resumeTask(id: string): Promise<ScheduledTask> {
    return request(`/api/tasks/${encodeURIComponent(id)}/resume`, { method: 'POST' });
  },
  runTask(id: string): Promise<TaskExecution> {
    return request(`/api/tasks/${encodeURIComponent(id)}/run`, { method: 'POST' });
  },
  taskHistory(id: string, offset = 0, limit = 20): Promise<TaskHistoryPage> {
    return request(`/api/tasks/${encodeURIComponent(id)}/history${buildQuery({ offset, limit })}`);
  },
  taskSummary(id: string, window?: SummaryWindow, from?: string, to?: string): Promise<TaskSummary> {
    return request(`/api/tasks/${encodeURIComponent(id)}/summary${buildQuery({ window, from, to })}`);
  },
  createDemoTasks(): Promise<{ created: string[] }> {
    return request('/api/tasks/demo', { method: 'POST' });
  },
  // ------------------------------------------------- Scheduled Task Tools
  listSchedulerTools(): Promise<{ items: SchedulerToolInfo[]; total: number }> {
    return request('/api/scheduler-tools');
  },
  updateSchedulerTool(toolId: string, enabled: boolean): Promise<SchedulerToolInfo> {
    return request(`/api/scheduler-tools/${encodeURIComponent(toolId)}`, { method: 'PUT', body: JSON.stringify({ enabled }) });
  },
  // --------------------------------------------------------------- LLM
  getLlmSettings(): Promise<LlmPublicSettings> {
    return request('/api/settings/llm');
  },
  checkLlm(patch: LlmSettingsPatch): Promise<LlmCheckResult> {
    return request('/api/settings/llm/check', { method: 'POST', body: JSON.stringify(patch) });
  },
  listLlmModels(patch: LlmSettingsPatch): Promise<{ models: string[] }> {
    return request('/api/settings/llm/models', { method: 'POST', body: JSON.stringify(patch) });
  },
  saveLlm(patch: LlmSettingsPatch): Promise<LlmSaveResult> {
    return request('/api/settings/llm', { method: 'PUT', body: JSON.stringify(patch) });
  },
  // ------------------------------------------------------------ Pipelines
  listPipelines(): Promise<{ items: Pipeline[]; total: number }> {
    return request('/api/pipelines');
  },
  getPipeline(id: string): Promise<Pipeline> {
    return request(`/api/pipelines/${encodeURIComponent(id)}`);
  },
  createPipeline(body: PipelineInputBody): Promise<Pipeline> {
    return request('/api/pipelines', { method: 'POST', body: JSON.stringify(body) });
  },
  updatePipeline(id: string, patch: Partial<PipelineInputBody>): Promise<Pipeline> {
    return request(`/api/pipelines/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(patch) });
  },
  deletePipeline(id: string): Promise<{ deleted: boolean }> {
    return request(`/api/pipelines/${encodeURIComponent(id)}`, { method: 'DELETE' });
  },
  runPipeline(id: string, input: Record<string, unknown>): Promise<PipelineRunResult> {
    return request(`/api/pipelines/${encodeURIComponent(id)}/run`, { method: 'POST', body: JSON.stringify({ input }) });
  },
  pipelineHistory(id: string, offset = 0, limit = 20): Promise<PipelineHistoryPage> {
    return request(`/api/pipelines/${encodeURIComponent(id)}/history${buildQuery({ offset, limit })}`);
  },
  pipelineExecution(executionId: string): Promise<PipelineExecution> {
    return request(`/api/pipeline-executions/${encodeURIComponent(executionId)}`);
  },
  seedPipelines(): Promise<{ created: string[] }> {
    return request('/api/pipelines/demo', { method: 'POST' });
  },
  // ----------------------------------------------------- Pipeline Tools
  listPipelineTools(): Promise<{ items: PipelineToolInfo[]; total: number }> {
    return request('/api/pipeline-tools');
  },
  updatePipelineTool(toolId: string, enabled: boolean): Promise<PipelineToolInfo> {
    return request(`/api/pipeline-tools/${encodeURIComponent(toolId)}`, { method: 'PUT', body: JSON.stringify({ enabled }) });
  },
};
