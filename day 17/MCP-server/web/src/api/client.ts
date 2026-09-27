// fetch-обёртка над REST API: JSON, ошибки вида {error:{code,message}}, toast на ошибки.
import type {
  LogEntry,
  LogQueryResult,
  ProviderHealth,
  ProviderRuntimeState,
  ProviderRuntimeTool,
  ServerSettingsResponse,
  ServerStatus,
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
    return request('/api/server/settings', { method: 'PUT', body: JSON.stringify(patch) });
  },
};