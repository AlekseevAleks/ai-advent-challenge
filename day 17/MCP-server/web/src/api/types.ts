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
export interface ServerSettingsResponse {
  host: string; port: number; logLevel: 'debug' | 'info' | 'warn' | 'error' | 'silent';
  logRetentionDays: number; maxResponseLogSize: number; requestTimeoutMs: number;
  defaultRetryCount: number; retryBackoffMs: number; corsEnabled: boolean;
  corsOrigins: string[]; debug: boolean;
}