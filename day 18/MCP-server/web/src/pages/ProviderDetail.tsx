// Provider detail `/providers/:id` — хедер с Enable/Test, вкладки
// General | Credentials | Tools (вкладка хранится в ?tab=).
import { useCallback, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { api } from '../api/client.js';
import type { ConfigField, ProviderRuntimeState, ProviderRuntimeTool } from '../api/types.js';
import { Badge, Button, Card, EmptyState, ErrorState, Field, Spinner, Tabs, Toggle, toast } from '../components/ui.js';
import { healthKind } from '../utils/meta.js';

type TabKey = 'general' | 'credentials' | 'tools';

interface TabProps {
  provider: ProviderRuntimeState;
  onSaved: (updated: ProviderRuntimeState | null) => void;
}

export function ProviderDetail(): ReactNode {
  const { id = '' } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const [provider, setProvider] = useState<ProviderRuntimeState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState(false);
  const tab = (searchParams.get('tab') as TabKey | null) ?? 'general';

  const load = useCallback(() => {
    setError(null);
    setProvider(null);
    api
      .getProvider(id)
      .then(setProvider)
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Failed to load provider');
      });
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  const setTab = (value: TabKey) => {
    const next = new URLSearchParams(searchParams);
    if (value === 'general') next.delete('tab');
    else next.set('tab', value);
    setSearchParams(next, { replace: true });
  };

  const onEnableDisable = async () => {
    if (!provider) return;
    setBusy(true);
    try {
      const updated = provider.enabled ? await api.disableProvider(provider.id) : await api.enableProvider(provider.id);
      setProvider(updated);
      toast(`${provider.name} ${provider.enabled ? 'disabled' : 'enabled'}`, 'success');
    } catch {
      /* toast показан в client */
    } finally {
      setBusy(false);
    }
  };

  const onTest = async () => {
    setTesting(true);
    try {
      const result = await api.testProvider(id);
      if (result.status === 'ok') {
        toast(`Connection OK${result.durationMs !== undefined ? ` (${result.durationMs} ms)` : ''}`, 'success');
      } else {
        toast(result.message ?? 'Connection failed', 'error');
      }
      const updated = await api.getProvider(id);
      setProvider(updated);
    } catch {
      /* toast показан в client */
    } finally {
      setTesting(false);
    }
  };

  if (error && !provider) {
    return (
      <div className="page">
        <ErrorState message={error} onRetry={load} />
        <div className="back-link">
          <Link to="/providers">← Back to APIs</Link>
        </div>
      </div>
    );
  }
  if (!provider) {
    return <Spinner text="Loading provider…" />;
  }

  const health = provider.health;

  return (
    <div className="page">
      <div className="back-link">
        <Link to="/providers">← Back to APIs</Link>
      </div>
      <div className="provider-header">
        <div className="provider-header-main">
          <div className="provider-title">
            {provider.name}
            <span className="provider-id mono">{provider.id}</span>
            <Badge kind="neutral">v{provider.version}</Badge>
          </div>
          {provider.description ? <p className="provider-desc">{provider.description}</p> : null}
          <div className="badges">
            {provider.enabled ? <Badge kind="accent">Enabled</Badge> : <Badge kind="muted">Disabled</Badge>}
            <Badge kind={healthKind(health.status)} title={health.message}>
              {health.status === 'ok' ? '● ok' : health.status === 'error' ? '● error' : 'unknown'}
            </Badge>
          </div>
        </div>
        <div className="page-actions">
          <Button variant={provider.enabled ? 'secondary' : 'primary'} loading={busy} onClick={() => void onEnableDisable()}>
            {provider.enabled ? 'Disable' : 'Enable'}
          </Button>
          <Button variant="secondary" loading={testing} onClick={() => void onTest()}>
            Test connection
          </Button>
        </div>
      </div>

      <Tabs<TabKey>
        tabs={[
          { value: 'general', label: 'General' },
          { value: 'credentials', label: 'Credentials' },
          { value: 'tools', label: 'Tools' },
        ]}
        value={tab}
        onChange={setTab}
      />

      {tab === 'general' ? <GeneralTab key={provider.id} provider={provider} onSaved={setProvider} /> : null}
      {tab === 'credentials' ? <CredentialsTab key={provider.id} provider={provider} onSaved={setProvider} /> : null}
      {tab === 'tools' ? <ToolsTab key={provider.id} provider={provider} /> : null}
    </div>
  );
}

// ---------------------------------------------------------------- General

function GeneralTab({ provider, onSaved }: TabProps): ReactNode {
  const schema = provider.configSchema;
  const fields = schema.fields;
  const hasNameField = fields.some((f) => f.key === 'name');

  const [form, setForm] = useState<Record<string, string>>(() => {
    const out: Record<string, string> = {};
    for (const f of fields) {
      if (f.key === 'name') out[f.key] = provider.name;
      else if (f.key === 'baseUrl') out[f.key] = provider.baseUrl ?? '';
      else out[f.key] = '';
    }
    for (const f of schema.settingsFields) {
      const value = provider.settings[f.key];
      out[f.key] = value === undefined || value === null ? '' : String(value);
    }
    return out;
  });
  const [name, setName] = useState(provider.name);
  const [saving, setSaving] = useState(false);

  const setField = (key: string, value: string) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const onSave = async () => {
    setSaving(true);
    try {
      const patch: { name?: string; baseUrl?: string; settings?: Record<string, unknown> } = {};
      const effectiveName = (hasNameField ? form['name'] ?? '' : name).trim();
      if (effectiveName) patch.name = effectiveName;

      for (const f of fields) {
        if (f.key === 'name' || f.key === 'baseUrl') {
          if (f.key === 'baseUrl') patch.baseUrl = (form[f.key] ?? '').trim();
          continue;
        }
        // Прочие строковые поля верхнего уровня (сейчас на бэке их нет).
      }

      const settingsPatch: Record<string, unknown> = {};
      for (const f of schema.settingsFields) {
        const value = (form[f.key] ?? '').trim();
        if (value === '') continue;
        settingsPatch[f.key] = f.type === 'number' ? Number(value) : value;
      }
      if (Object.keys(settingsPatch).length > 0) patch.settings = settingsPatch;

      const updated = await api.updateProvider(provider.id, patch);
      onSaved(updated);
      toast('Settings saved', 'success');
    } catch {
      /* toast показан в client */
    } finally {
      setSaving(false);
    }
  };

  if (fields.length === 0 && schema.settingsFields.length === 0) {
    return <EmptyState title="No editable settings" description="У этого провайдера нет настраиваемых полей." />;
  }

  return (
    <div className="settings-section">
      <Card
        title="Configuration"
        actions={
          <Button variant="primary" size="sm" loading={saving} onClick={() => void onSave()}>
            Save
          </Button>
        }
      >
        <div className="form-grid">
          {!hasNameField ? (
            <Field label="Name" hint="Отображаемое имя провайдера.">
              <input type="text" value={name} onChange={(event) => setName(event.target.value)} />
            </Field>
          ) : null}
          {fields.map((f) => (
            <ConfigFieldInput key={f.key} field={f} value={form[f.key] ?? ''} onChange={(v) => setField(f.key, v)} />
          ))}
          {schema.settingsFields.map((f) => (
            <ConfigFieldInput key={f.key} field={f} value={form[f.key] ?? ''} onChange={(v) => setField(f.key, v)} />
          ))}
        </div>
      </Card>
    </div>
  );
}

function ConfigFieldInput({
  field,
  value,
  onChange,
}: {
  field: ConfigField;
  value: string;
  onChange: (value: string) => void;
}): ReactNode {
  const type = field.type === 'number' ? 'number' : 'text';
  return (
    <Field label={field.label} hint={field.description} required={field.required}>
      {field.type === 'number' ? (
        <div className="input-unit">
          <input type="number" value={value} placeholder={field.placeholder} onChange={(event) => onChange(event.target.value)} />
          {field.unit ? <span className="input-unit-label">{field.unit}</span> : null}
        </div>
      ) : (
        <input type={type} value={value} placeholder={field.placeholder} onChange={(event) => onChange(event.target.value)} />
      )}
    </Field>
  );
}

// ---------------------------------------------------------------- Credentials

function CredentialsTab({ provider, onSaved }: TabProps): ReactNode {
  const fields = provider.configSchema.credentialFields;
  const [values, setValues] = useState<Record<string, string>>({});
  const [revealed, setRevealed] = useState<Record<string, boolean>>({});
  const [savingKey, setSavingKey] = useState<string | null>(null);

  if (fields.length === 0) {
    return <EmptyState title="No credentials" description="Этот провайдер не требует учётных данных." />;
  }

  const onSave = async (key: string, label: string) => {
    const value = (values[key] ?? '').trim();
    if (!value) {
      toast(`Введите новое значение для ${label}`, 'info');
      return;
    }
    setSavingKey(key);
    try {
      const updated = await api.updateProvider(provider.id, { credentials: { [key]: value } });
      setValues((prev) => ({ ...prev, [key]: '' }));
      onSaved(updated);
      toast(`${label} saved`, 'success');
    } catch {
      /* toast показан в client */
    } finally {
      setSavingKey(null);
    }
  };

  return (
    <div className="settings-section">
      {fields.map((field) => {
        const cred = provider.credentials[field.key];
        const overridden = cred?.overridden ?? false;
        const mask = cred?.value ?? '';
        const isSaving = savingKey === field.key;
        const isRevealed = revealed[field.key] === true;
        return (
          <div key={field.key} className="credential-row">
            <div className="credential-head">
              <span className="field-label">{field.label}</span>
              {overridden ? (
                <Badge kind="warn">from env {field.env ?? ''}</Badge>
              ) : cred?.set ? (
                <Badge kind="muted">set</Badge>
              ) : (
                <Badge kind="neutral">not set</Badge>
              )}
            </div>
            {field.description ? <span className="field-hint">{field.description}</span> : null}
            {overridden ? (
              <div className="credential-mask mono">{mask || '—'}</div>
            ) : (
              <div className="credential-controls">
                {cred?.set && mask ? (
                  <div className="credential-mask mono">
                    Current: {mask}
                    <span className="text-muted"> (secret value is never shown)</span>
                  </div>
                ) : null}
                <div className="credential-input-row">
                  <input
                    type={isRevealed ? 'text' : 'password'}
                    value={values[field.key] ?? ''}
                    placeholder="Введите новый …"
                    autoComplete="new-password"
                    onChange={(event) => setValues((prev) => ({ ...prev, [field.key]: event.target.value }))}
                  />
                  <Button size="sm" onClick={() => setRevealed((prev) => ({ ...prev, [field.key]: !prev[field.key] }))}>
                    {isRevealed ? 'Hide' : 'Show'}
                  </Button>
                  <Button variant="primary" size="sm" loading={isSaving} onClick={() => void onSave(field.key, field.label)}>
                    Save
                  </Button>
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------- Tools

function ToolsTab({ provider }: { provider: ProviderRuntimeState }): ReactNode {
  const [tools, setTools] = useState<ProviderRuntimeTool[]>(provider.tools);
  const [pending, setPending] = useState<Record<string, boolean>>({});

  const onToggle = async (tool: ProviderRuntimeTool, enabled: boolean) => {
    setPending((prev) => ({ ...prev, [tool.name]: true }));
    try {
      const updated = await api.updateProviderTool(provider.id, tool.name, { enabled });
      setTools((prev) => prev.map((t) => (t.name === updated.name ? updated : t)));
    } catch {
      // Ошибку показывает toast; локальное значение не менялось — переключатель сам откатывается.
    } finally {
      setPending((prev) => {
        const next = { ...prev };
        delete next[tool.name];
        return next;
      });
    }
  };

  if (tools.length === 0) {
    return <EmptyState title="No tools" description="У этого провайдера нет доступных tools." />;
  }

  return (
    <div className="tools-grid">
      {tools.map((tool) => (
        <div key={tool.name} className={`tool-card${tool.enabled ? '' : ' tool-card-disabled'}`}>
          <div className="tool-card-head">
            <div className="tool-card-title">
              <span className="mono">{tool.name}</span>
              {!tool.enabled ? <Badge kind="muted">Disabled</Badge> : null}
            </div>
            <Toggle
              checked={tool.enabled}
              pending={pending[tool.name] === true}
              label={`Toggle ${tool.name}`}
              onChange={(next) => void onToggle(tool, next)}
            />
          </div>
          <p className="tool-card-desc">{tool.description || 'No description'}</p>
          <ToolSchemaView schema={tool.inputSchema} />
        </div>
      ))}
    </div>
  );
}

function ToolSchemaView({ schema }: { schema: ProviderRuntimeTool['inputSchema'] }): ReactNode {
  const properties = schema.properties ?? {};
  const required = new Set(schema.required ?? []);
  const entries = Object.entries(properties);

  return (
    <div className="schema-block">
      {entries.length === 0 ? (
        <span className="schema-type">no input properties</span>
      ) : (
        <ul className="schema-props">
          {entries.map(([key, prop]) => {
            const propType =
              typeof prop === 'object' && prop !== null && 'type' in prop && typeof prop.type === 'string'
                ? prop.type
                : 'any';
            return (
              <li key={key}>
                <code className="schema-key">{key}</code>
                <span className="schema-type">{propType}</span>
                {required.has(key) ? <span className="schema-required">*</span> : null}
              </li>
            );
          })}
        </ul>
      )}
      <details className="schema-details">
        <summary>JSON Schema</summary>
        <pre className="code-block">{JSON.stringify(schema, null, 2)}</pre>
      </details>
    </div>
  );
}