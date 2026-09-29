// LLM Settings `/settings/llm` — OpenAI configuration.
// Флоу: API URL + API Key → Проверить (backend → GET /models) → выбор/ввод модели → Сохранить.
// API key никогда не возвращается backend'ом и не отображается после сохранения.
import { useCallback, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client.js';
import type { LlmPublicSettings } from '../api/types.js';
import { Button, Card, Field, Spinner, toast } from '../components/ui.js';

type ConnectionState = 'idle' | 'checking' | 'connected' | 'error';

export function LlmSettings(): ReactNode {
  const [loaded, setLoaded] = useState(false);
  const [settings, setSettings] = useState<LlmPublicSettings | null>(null);
  const [apiUrl, setApiUrl] = useState('');
  const [apiKeyInput, setApiKeyInput] = useState('');
  const [models, setModels] = useState<string[]>([]);
  const [model, setModel] = useState('');
  const [manualModel, setManualModel] = useState('');
  const [state, setState] = useState<ConnectionState>('idle');
  const [message, setMessage] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(() => {
    api
      .getLlmSettings()
      .then((s) => {
        setSettings(s);
        setApiUrl(s.apiUrl);
        setModel(s.model);
        setManualModel(s.model);
        setState(s.configured ? 'connected' : 'idle');
        setMessage(null);
      })
      .catch((err) => {
        setMessage(err instanceof Error ? err.message : 'Failed to load LLM settings');
        setState('error');
      })
      .finally(() => setLoaded(true));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const patch = (): { apiUrl: string; apiKey?: string } => {
    const p: { apiUrl: string; apiKey?: string } = { apiUrl: apiUrl.trim() };
    if (apiKeyInput.trim() !== '') p.apiKey = apiKeyInput.trim();
    return p;
  };

  const onCheck = async () => {
    setState('checking');
    setMessage(null);
    try {
      const result = await api.checkLlm(patch());
      if (result.ok) {
        setState('connected');
        const modelsResult = await api.listLlmModels(patch());
        setModels(modelsResult.models);
        if (!modelsResult.models.includes(model)) {
          setModel('');
          setManualModel('');
        }
      } else {
        setState('error');
        setMessage(result.message);
      }
    } catch (err) {
      setState('error');
      setMessage(err instanceof Error ? err.message : 'Connection failed');
    }
  };

  const onSave = async () => {
    setSaving(true);
    setMessage(null);
    try {
      const result = await api.saveLlm({ ...patch(), model: manualModel.trim() || model });
      toast('Settings saved successfully', 'success');
      const fresh = await api.getLlmSettings();
      setSettings(fresh);
      setModel(result.model);
      setManualModel(result.model);
      setApiKeyInput('');
      setState(fresh.configured ? 'connected' : 'idle');
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'Save failed');
    } finally {
      setSaving(false);
    }
  };

  const editable = state === 'connected' || state === 'idle';
  const modelEnabled = state === 'connected';
  const saveEnabled = modelEnabled && (manualModel.trim() !== '' || model !== '');

  if (!loaded) return <Spinner text="Loading LLM settings…" />;

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">LLM Settings</h1>
          <p className="page-subtitle">Настройка OpenAI для summarize и pipeline-шага summarize. Ключ хранится только на backend.</p>
        </div>
      </div>

      {state === 'connected' ? (
        <div className="callout ok">Connection: Connected</div>
      ) : state === 'error' ? (
        <div className="callout">Connection failed: {message}</div>
      ) : null}

      <Card title="OpenAI">
        <div className="form-grid">
          <Field label="Provider">
            <input type="text" value="OpenAI" disabled />
          </Field>
          <Field label="API URL" hint="OpenAI-compatible base, например https://api.openai.com/v1">
            <input type="text" value={apiUrl} onChange={(event) => { setApiUrl(event.target.value); if (settings?.configured) setState('idle'); }} placeholder="https://api.openai.com/v1" />
          </Field>
          <Field label="API Key" hint={settings?.configured ? 'Configured' : 'Не показывается после сохранения'}>
            <input
              type="password"
              autoComplete="new-password"
              value={apiKeyInput}
              placeholder={settings?.configured ? '••••••••••••••••' : 'sk-…'}
              onChange={(event) => { setApiKeyInput(event.target.value); if (settings?.configured) setState('idle'); }}
            />
          </Field>
        </div>

        <div className="modal-actions">
          <Button variant="primary" loading={state === 'checking'} disabled={!editable || apiUrl.trim() === ''} onClick={() => void onCheck()}>
            {state === 'checking' ? 'Checking…' : 'Проверить'}
          </Button>
        </div>
      </Card>

      <Card title="Model">
        <div className="form-grid">
          <Field label="Model" hint={modelEnabled ? 'Выберите из списка или введите вручную' : 'Доступно после успешной проверки'}>
            <select
              disabled={!modelEnabled}
              value={model}
              onChange={(event) => { setModel(event.target.value); setManualModel(event.target.value); }}
            >
              <option value="">— Select model —</option>
              {models.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Or enter model ID manually" hint="Работает даже если модели нет в списке /models">
            <input
              type="text"
              disabled={!modelEnabled}
              value={manualModel}
              placeholder="gpt-4.1 или my-custom-model"
              onChange={(event) => { setManualModel(event.target.value); if (models.includes(event.target.value)) setModel(event.target.value); }}
            />
          </Field>
        </div>

        <div className="modal-actions">
          <Button variant="primary" loading={saving} disabled={!saveEnabled} onClick={() => void onSave()}>
            {saving ? 'Saving…' : 'Сохранить'}
          </Button>
          <Button variant="secondary" onClick={load}>
            Reset
          </Button>
        </div>
      </Card>

      <div className="back-link">
        <Link to="/settings">← Back to Settings</Link>
      </div>
    </div>
  );
}