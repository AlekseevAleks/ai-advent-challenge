// Dashboard `/`: статус сервера, MCP endpoint, статистика, карточки провайдеров,
// последние запросы.
import { useCallback, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../api/client.js';
import type { LogEntry, ProviderRuntimeState, ServerStatus } from '../api/types.js';
import { Badge, Button, Card, CopyButton, EmptyState, ErrorState, Spinner, Stat } from '../components/ui.js';
import { directionKind, directionLabel, healthKind, statusKind } from '../utils/meta.js';
import { formatDuration, formatNumber, formatTime, pathOnly } from '../utils/format.js';

function healthTitle(health: ProviderRuntimeState['health']): string | undefined {
  return health.message || undefined;
}

export function Dashboard(): ReactNode {
  const [status, setStatus] = useState<ServerStatus | null>(null);
  const [providers, setProviders] = useState<ProviderRuntimeState[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  const load = useCallback(() => {
    setError(null);
    Promise.all([api.getStatus(), api.getProviders()])
      .then(([s, p]) => {
        setStatus(s);
        setProviders(p);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Failed to load');
      });
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (error && !status) {
    return <ErrorState message={error} onRetry={load} />;
  }
  if (!status || !providers) {
    return <Spinner text="Loading dashboard…" />;
  }

  const openLog = (entry: LogEntry) => {
    navigate(`/logs?id=${encodeURIComponent(entry.id)}`);
  };

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Dashboard</h1>
          <p className="page-subtitle">
            {status.name} v{status.version}
          </p>
        </div>
        <div className="page-actions">
          <Button variant="secondary" onClick={load}>
            Refresh
          </Button>
        </div>
      </div>

      <div className="stats-row">
        <Card title="Server">
          <div className="running-row">
            <span className={`dot dot-${status.running ? 'ok' : 'error'}`} />
            <strong>{status.running ? 'Running' : 'Stopped'}</strong>
            <span className="text-muted">uptime {formatDuration(status.uptimeSeconds)}</span>
          </div>
          <div className="endpoint-box">
            <code className="mono">{status.mcpEndpoint}</code>
            <CopyButton text={status.mcpEndpoint} label="Copy" />
          </div>
        </Card>
        <div className="stat-grid">
          <Stat
            label="Providers"
            value={formatNumber(status.providers.total)}
            hint={`${status.providers.enabled} enabled · ${status.providers.disabled} disabled`}
          />
          <Stat label="Tools" value={formatNumber(status.tools.total)} hint={`${status.tools.enabled} enabled`} />
          <Stat label="Requests today" value={formatNumber(status.requests.today)} />
          <Stat label="Errors today" value={formatNumber(status.requests.errorsToday)} />
          <Stat label="Avg latency" value={`${status.requests.avgLatencyMs} ms`} />
        </div>
      </div>

      <h2 className="section-title">Providers</h2>
      {providers.length === 0 ? (
        <EmptyState title="No providers" description="Настройте хотя бы одного провайдера в конфигурации." />
      ) : (
        <div className="cards-grid">
          {providers.map((provider) => {
            const health = provider.health;
            return (
              <Card key={provider.id} className="provider-card">
                <div className="provider-card-head">
                  <div className="provider-card-title">{provider.name}</div>
                  <div className="badges">
                    {provider.enabled ? (
                      <Badge kind="accent">Enabled</Badge>
                    ) : (
                      <Badge kind="muted">Disabled</Badge>
                    )}
                    <Badge kind={healthKind(health.status)} title={healthTitle(health)}>
                      {health.status === 'ok' ? '● ok' : health.status === 'error' ? '● error' : 'unknown'}
                    </Badge>
                  </div>
                </div>
                <div className="provider-card-meta">
                  <span className="text-muted">{provider.toolsCount} tools</span>
                  <span className="text-muted">{provider.version}</span>
                </div>
                <div className="provider-card-actions">
                  <Link className="btn btn-secondary btn-sm" to={`/providers/${encodeURIComponent(provider.id)}`}>
                    Open
                  </Link>
                </div>
              </Card>
            );
          })}
        </div>
      )}

      <h2 className="section-title">Last requests</h2>
      {status.lastRequests.length === 0 ? (
        <EmptyState title="No requests yet" description="Как только через MCP будет вызван tool, запросы появятся здесь." />
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Direction</th>
                <th>Tool</th>
                <th>Method</th>
                <th>URL</th>
                <th>Status</th>
                <th>Duration</th>
              </tr>
            </thead>
            <tbody>
              {status.lastRequests.map((entry) => (
                <tr key={entry.id} className="row-clickable" onClick={() => openLog(entry)} title="View details">
                  <td className="nowrap">{formatTime(entry.timestamp)}</td>
                  <td>
                    <Badge kind={directionKind(entry.direction)}>{directionLabel(entry.direction)}</Badge>
                  </td>
                  <td className="mono">{entry.tool ?? '—'}</td>
                  <td className="mono">{entry.method}</td>
                  <td className="mono url-cell">{pathOnly(entry.url)}</td>
                  <td>
                    {entry.status !== undefined ? (
                      <Badge kind={statusKind(entry.status)}>{entry.status}</Badge>
                    ) : (
                      <Badge kind={entry.success ? 'ok' : 'error'}>{entry.success ? 'OK' : 'ERR'}</Badge>
                    )}
                  </td>
                  <td className="nowrap">{entry.durationMs !== undefined ? `${entry.durationMs} ms` : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}