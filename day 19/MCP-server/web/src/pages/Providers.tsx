// Providers `/providers` — таблица API-провайдеров: статус, health, tools,
// действия Settings / Test connection / Enable / Disable.
import { useCallback, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client.js';
import type { ProviderRuntimeState } from '../api/types.js';
import { Badge, Button, EmptyState, ErrorState, Spinner, toast } from '../components/ui.js';
import { healthKind } from '../utils/meta.js';
import { formatRelative } from '../utils/format.js';

function HealthCell({ provider }: { provider: ProviderRuntimeState }): ReactNode {
  const health = provider.health;
  if (health.status === 'unknown') {
    return <span className="text-muted">—</span>;
  }
  const checked = health.checkedAt ? ` · ${formatRelative(health.checkedAt)}` : '';
  return (
    <span title={health.message}>
      <Badge kind={healthKind(health.status)}>
        {health.status === 'ok' ? '● ok' : '● error'}
        {checked}
      </Badge>
    </span>
  );
}

export function Providers(): ReactNode {
  const [providers, setProviders] = useState<ProviderRuntimeState[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    api
      .getProviders()
      .then(setProviders)
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Failed to load providers');
      });
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const onTest = async (provider: ProviderRuntimeState) => {
    setTestingId(provider.id);
    try {
      const result = await api.testProvider(provider.id);
      if (result.status === 'ok') {
        toast(`${provider.name}: connection OK${result.durationMs !== undefined ? ` (${result.durationMs} ms)` : ''}`, 'success');
      } else {
        toast(`${provider.name}: ${result.message ?? 'connection failed'}`, 'error');
      }
    } catch {
      /* toast показан в client */
    } finally {
      setTestingId(null);
      void load();
    }
  };

  const onToggle = async (provider: ProviderRuntimeState) => {
    setBusyId(provider.id);
    try {
      if (provider.enabled) {
        await api.disableProvider(provider.id);
      } else {
        await api.enableProvider(provider.id);
      }
      toast(`${provider.name} ${provider.enabled ? 'disabled' : 'enabled'}`, 'success');
      void load();
    } catch {
      /* toast показан в client */
    } finally {
      setBusyId(null);
    }
  };

  if (error && !providers) {
    return <ErrorState message={error} onRetry={load} />;
  }
  if (!providers) {
    return <Spinner text="Loading providers…" />;
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">APIs</h1>
          <p className="page-subtitle">Подключённые провайдеры и их состояние.</p>
        </div>
        <div className="page-actions">
          <Button variant="secondary" onClick={load}>
            Refresh
          </Button>
        </div>
      </div>

      {providers.length === 0 ? (
        <EmptyState title="No providers" description="Провайдеры подключаются из конфигурации сервера (config/providers)." />
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Name</th>
                <th>ID</th>
                <th>Status</th>
                <th>Health</th>
                <th>Tools</th>
                <th>Base URL</th>
                <th className="actions-col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {providers.map((provider) => (
                <tr key={provider.id}>
                  <td>
                    <Link className="provider-name-link" to={`/providers/${encodeURIComponent(provider.id)}`}>
                      {provider.name}
                    </Link>
                  </td>
                  <td className="mono text-muted">{provider.id}</td>
                  <td>{provider.enabled ? <Badge kind="accent">Enabled</Badge> : <Badge kind="muted">Disabled</Badge>}</td>
                  <td>
                    <HealthCell provider={provider} />
                  </td>
                  <td>
                    <span className="mono">
                      {provider.enabledToolsCount}/{provider.toolsCount}
                    </span>
                  </td>
                  <td className="mono url-cell">{provider.baseUrl ?? '—'}</td>
                  <td>
                    <div className="row-actions">
                      <Link className="btn btn-secondary btn-sm" to={`/providers/${encodeURIComponent(provider.id)}`}>
                        Settings
                      </Link>
                      <Button variant="secondary" size="sm" loading={testingId === provider.id} onClick={() => void onTest(provider)}>
                        Test connection
                      </Button>
                      <Button
                        variant={provider.enabled ? 'ghost' : 'primary'}
                        size="sm"
                        loading={busyId === provider.id}
                        onClick={() => void onToggle(provider)}
                      >
                        {provider.enabled ? 'Disable' : 'Enable'}
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}