// Settings `/settings` — форма настроек сервера (GET/PUT /api/server/settings).
// maxResponseLogSize показывается в КБ и конвертируется в байты; сохраняются
// только изменённые поля; restartRequired выводится предупреждением.
import { useCallback, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { api } from '../api/client.js';
import type { ServerSettingsResponse } from '../api/types.js';
import { Button, Card, ErrorState, Field, Spinner, Toggle, toast } from '../components/ui.js';

interface SettingsForm {
  host: string;
  port: string;
  logLevel: ServerSettingsResponse['logLevel'];
  logRetentionDays: string;
  maxResponseLogSizeKb: string;
  requestTimeoutMs: string;
  defaultRetryCount: string;
  retryBackoffMs: string;
  corsEnabled: boolean;
  corsOrigins: string;
  debug: boolean;
  schedulerEnabled: boolean;
  tickIntervalMs: string;
  maxStoredExecutionsPerTask: string;
  executionRetentionDays: string;
  retryEnabled: boolean;
  retryMaxAttempts: string;
  retryDelayMs: string;
}

const LOG_LEVELS: ServerSettingsResponse['logLevel'][] = ['debug', 'info', 'warn', 'error', 'silent'];

function fromSettings(s: ServerSettingsResponse): SettingsForm {
  const scheduler = s.scheduler ?? {
    enabled: true,
    tickIntervalMs: 60000,
    maxStoredExecutionsPerTask: 1000,
    executionRetentionDays: 30,
    retry: { enabled: true, maxAttempts: 3, delayMs: 5000 },
  };
  return {
    host: s.host,
    port: String(s.port),
    logLevel: s.logLevel,
    logRetentionDays: String(s.logRetentionDays),
    maxResponseLogSizeKb: String(Math.round(s.maxResponseLogSize / 1024)),
    requestTimeoutMs: String(s.requestTimeoutMs),
    defaultRetryCount: String(s.defaultRetryCount),
    retryBackoffMs: String(s.retryBackoffMs),
    corsEnabled: s.corsEnabled,
    corsOrigins: (s.corsOrigins ?? []).join('\n'),
    debug: s.debug,
    schedulerEnabled: scheduler.enabled,
    tickIntervalMs: String(scheduler.tickIntervalMs),
    maxStoredExecutionsPerTask: String(scheduler.maxStoredExecutionsPerTask),
    executionRetentionDays: String(scheduler.executionRetentionDays),
    retryEnabled: scheduler.retry.enabled,
    retryMaxAttempts: String(scheduler.retry.maxAttempts),
    retryDelayMs: String(scheduler.retry.delayMs),
  };
}

function parseNumber(value: string): number | undefined {
  const n = Number(value);
  return Number.isFinite(n) ? n : undefined;
}

export function Settings(): ReactNode {
  const [settings, setSettings] = useState<ServerSettingsResponse | null>(null);
  const [form, setForm] = useState<SettingsForm | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [restartRequired, setRestartRequired] = useState<string[]>([]);

  const load = useCallback(() => {
    setError(null);
    api
      .getSettings()
      .then((s) => {
        setSettings(s);
        setForm(fromSettings(s));
        setRestartRequired([]);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Failed to load settings');
      });
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const setString = (key: keyof SettingsForm, value: string) => {
    setForm((prev) => (prev ? { ...prev, [key]: value } : prev));
  };

  const setBoolean = (key: keyof SettingsForm, value: boolean) => {
    setForm((prev) => (prev ? { ...prev, [key]: value } : prev));
  };

  const onSave = async () => {
    if (!settings || !form) return;
    const patch: Record<string, unknown> = {};

    if (form.host !== settings.host) patch.host = form.host;
    const port = parseNumber(form.port);
    if (port !== undefined && port !== settings.port) patch.port = port;
    if (form.logLevel !== settings.logLevel) patch.logLevel = form.logLevel;
    const retention = parseNumber(form.logRetentionDays);
    if (retention !== undefined && retention !== settings.logRetentionDays) patch.logRetentionDays = retention;
    const maxSizeBytes = parseNumber(form.maxResponseLogSizeKb);
    if (maxSizeBytes !== undefined && maxSizeBytes * 1024 !== settings.maxResponseLogSize) patch.maxResponseLogSize = maxSizeBytes * 1024;
    const timeout = parseNumber(form.requestTimeoutMs);
    if (timeout !== undefined && timeout !== settings.requestTimeoutMs) patch.requestTimeoutMs = timeout;
    const retries = parseNumber(form.defaultRetryCount);
    if (retries !== undefined && retries !== settings.defaultRetryCount) patch.defaultRetryCount = retries;
    const backoff = parseNumber(form.retryBackoffMs);
    if (backoff !== undefined && backoff !== settings.retryBackoffMs) patch.retryBackoffMs = backoff;
    if (form.corsEnabled !== settings.corsEnabled) patch.corsEnabled = form.corsEnabled;
    const origins = form.corsOrigins
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean);
    if (origins.join('\n') !== (settings.corsOrigins ?? []).join('\n')) patch.corsOrigins = origins;
    if (form.debug !== settings.debug) patch.debug = form.debug;

    // Scheduler / Scheduled Tasks
    const sched = settings.scheduler;
    if (sched) {
      const schedPatch: Record<string, unknown> = {};
      if (form.schedulerEnabled !== sched.enabled) schedPatch.enabled = form.schedulerEnabled;
      const tick = parseNumber(form.tickIntervalMs);
      if (tick !== undefined && tick !== sched.tickIntervalMs) schedPatch.tickIntervalMs = tick;
      const maxStored = parseNumber(form.maxStoredExecutionsPerTask);
      if (maxStored !== undefined && maxStored !== sched.maxStoredExecutionsPerTask) schedPatch.maxStoredExecutionsPerTask = maxStored;
      const retention = parseNumber(form.executionRetentionDays);
      if (retention !== undefined && retention !== sched.executionRetentionDays) schedPatch.executionRetentionDays = retention;
      const retryPatch: Record<string, unknown> = {};
      if (form.retryEnabled !== sched.retry.enabled) retryPatch.enabled = form.retryEnabled;
      const attempts = parseNumber(form.retryMaxAttempts);
      if (attempts !== undefined && attempts !== sched.retry.maxAttempts) retryPatch.maxAttempts = attempts;
      const delay = parseNumber(form.retryDelayMs);
      if (delay !== undefined && delay !== sched.retry.delayMs) retryPatch.delayMs = delay;
      if (Object.keys(retryPatch).length > 0) schedPatch.retry = retryPatch;
      if (Object.keys(schedPatch).length > 0) patch.scheduler = schedPatch;
    }

    if (Object.keys(patch).length === 0) {
      toast('No changes to save', 'info');
      return;
    }

    setSaving(true);
    try {
      const result = await api.updateSettings(patch);
      setSettings(result);
      setForm(fromSettings(result));
      setRestartRequired(result.restartRequired ?? []);
      toast('Saved', 'success');
    } catch {
      /* toast показан в client */
    } finally {
      setSaving(false);
    }
  };

  if (error && !settings) {
    return <ErrorState message={error} onRetry={load} />;
  }
  if (!settings || !form) {
    return <Spinner text="Loading settings…" />;
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Settings</h1>
          <p className="page-subtitle">Настройки сервера MCP Gateway.</p>
        </div>
        <div className="page-actions">
          <Button variant="secondary" onClick={load}>
            Reset form
          </Button>
          <Button variant="primary" loading={saving} onClick={() => void onSave()}>
            Save
          </Button>
        </div>
      </div>

      {restartRequired.length > 0 ? (
        <div className="callout">
          ⚠ Применится после перезапуска: {restartRequired.join(', ')}
        </div>
      ) : null}

      <Card title="Server">
        <div className="form-grid">
          <Field label="Host" hint="Адрес прослушивания (live, кроме перезапуска)." required>
            <input type="text" value={form.host} onChange={(event) => setString('host', event.target.value)} />
          </Field>
          <Field label="Port" hint="Порт HTTP-сервера." required>
            <input type="number" min={1} max={65535} value={form.port} onChange={(event) => setString('port', event.target.value)} />
          </Field>
        </div>
      </Card>

      <Card title="Logging">
        <div className="form-grid">
          <Field label="Log level" hint="Уровень логирования сервера.">
            <select value={form.logLevel} onChange={(event) => setString('logLevel', event.target.value)}>
              {LOG_LEVELS.map((level) => (
                <option key={level} value={level}>
                  {level}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Log retention (days)" hint="Сколько дней хранить логи.">
            <input
              type="number"
              min={0}
              max={365}
              value={form.logRetentionDays}
              onChange={(event) => setString('logRetentionDays', event.target.value)}
            />
          </Field>
          <Field label="Max response log size (KB)" hint="Ограничение размера тела ответа в логах, в килобайтах.">
            <div className="input-unit">
              <input
                type="number"
                min={1}
                value={form.maxResponseLogSizeKb}
                onChange={(event) => setString('maxResponseLogSizeKb', event.target.value)}
              />
              <span className="input-unit-label">KB</span>
            </div>
          </Field>
        </div>
      </Card>

      <Card title="Requests & retries">
        <div className="form-grid">
          <Field label="Request timeout (ms)">
            <input type="number" min={100} max={120000} value={form.requestTimeoutMs} onChange={(event) => setString('requestTimeoutMs', event.target.value)} />
          </Field>
          <Field label="Default retry count">
            <input type="number" min={0} max={10} value={form.defaultRetryCount} onChange={(event) => setString('defaultRetryCount', event.target.value)} />
          </Field>
          <Field label="Retry backoff (ms)">
            <input type="number" min={0} max={60000} value={form.retryBackoffMs} onChange={(event) => setString('retryBackoffMs', event.target.value)} />
          </Field>
        </div>
      </Card>

      <Card title="CORS & debug">
        <Field label="CORS origins" hint="Одна строка на origin.">
          <textarea
            rows={4}
            value={form.corsOrigins}
            placeholder={'http://localhost:5173\nhttps://example.com'}
            onChange={(event) => setString('corsOrigins', event.target.value)}
          />
        </Field>
        <div className="toggle-row">
          <div>
            <div className="toggle-row-label">CORS enabled</div>
            <div className="field-hint">Разрешать кросс-доменные запросы.</div>
          </div>
          <Toggle checked={form.corsEnabled} label="CORS enabled" onChange={(v) => setBoolean('corsEnabled', v)} />
        </div>
        <div className="toggle-row">
          <div>
            <div className="toggle-row-label">Debug</div>
            <div className="field-hint">Расширенное логирование и диагностика.</div>
          </div>
          <Toggle checked={form.debug} label="Debug" onChange={(v) => setBoolean('debug', v)} />
        </div>
      </Card>

      <Card title="Scheduler & Scheduled Tasks">
        <div className="toggle-row">
          <div>
            <div className="toggle-row-label">Scheduler enabled</div>
            <div className="field-hint">Выполнение задач по расписанию (Run now работает всегда).</div>
          </div>
          <Toggle checked={form.schedulerEnabled} label="Scheduler enabled" onChange={(v) => setBoolean('schedulerEnabled', v)} />
        </div>
        <div className="form-grid">
          <Field label="Safety poll interval (ms)" hint="Редкая страховочная проверка расписания.">
            <input type="number" min={100} max={3600000} value={form.tickIntervalMs} onChange={(event) => setString('tickIntervalMs', event.target.value)} />
          </Field>
          <Field label="Max executions per task" hint="Сколько записей истории хранить на задачу.">
            <input type="number" min={10} max={100000} value={form.maxStoredExecutionsPerTask} onChange={(event) => setString('maxStoredExecutionsPerTask', event.target.value)} />
          </Field>
          <Field label="History retention (days)" hint="Сколько дней хранить историю выполнений.">
            <input type="number" min={0} max={3650} value={form.executionRetentionDays} onChange={(event) => setString('executionRetentionDays', event.target.value)} />
          </Field>
        </div>
        <div className="toggle-row">
          <div>
            <div className="toggle-row-label">Execution retry</div>
            <div className="field-hint">Повторять упавшие выполнения (не бесконечно).</div>
          </div>
          <Toggle checked={form.retryEnabled} label="Execution retry" onChange={(v) => setBoolean('retryEnabled', v)} />
        </div>
        <div className="form-grid">
          <Field label="Max attempts">
            <input type="number" min={1} max={10} value={form.retryMaxAttempts} onChange={(event) => setString('retryMaxAttempts', event.target.value)} />
          </Field>
          <Field label="Retry delay (ms)" hint="Задержка между попытками (для 429 учитывается Retry-After).">
            <input type="number" min={0} max={3600000} value={form.retryDelayMs} onChange={(event) => setString('retryDelayMs', event.target.value)} />
          </Field>
        </div>
      </Card>
    </div>
  );
}