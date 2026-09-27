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
}

const LOG_LEVELS: ServerSettingsResponse['logLevel'][] = ['debug', 'info', 'warn', 'error', 'silent'];

function fromSettings(s: ServerSettingsResponse): SettingsForm {
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
    </div>
  );
}