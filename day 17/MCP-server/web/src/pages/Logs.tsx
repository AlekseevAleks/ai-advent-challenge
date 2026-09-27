// Logs `/logs` — фильтры, таблица, пагинация (offset, pageSize 50),
// детальная модалка (GET /api/logs/:id), Clear logs с подтверждением,
// авто-refresh раз в 10 с (пауза при открытой модалке). Поддержка /?id=<id>.
import { useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api, ApiError } from '../api/client.js';
import type { LogEntry, LogQueryResult, ProviderRuntimeState, ProviderRuntimeTool } from '../api/types.js';
import {
  Badge,
  Button,
  CodeBlock,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Modal,
  SearchInput,
  Spinner,
  toast,
} from '../components/ui.js';
import { IconRefresh, IconTrash } from '../components/icons.js';
import { directionKind, directionLabel, statusKind } from '../utils/meta.js';
import { formatDateTime, formatHeaders, pathOnly } from '../utils/format.js';

const PAGE_SIZE = 50;
const REFRESH_MS = 10_000;
type ResultFilter = 'all' | 'success' | 'error';

export function Logs(): ReactNode {
  const [searchParams, setSearchParams] = useSearchParams();
  const [data, setData] = useState<LogQueryResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [providers, setProviders] = useState<ProviderRuntimeState[]>([]);
  const [tools, setTools] = useState<ProviderRuntimeTool[]>([]);
  const [detail, setDetail] = useState<LogEntry | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);
  const [clearing, setClearing] = useState(false);

  const params = useMemo(() => {
    return {
      search: searchParams.get('search') ?? '',
      provider: searchParams.get('provider') ?? '',
      tool: searchParams.get('tool') ?? '',
      status: searchParams.get('status') ?? '',
      result: (searchParams.get('result') as ResultFilter | null) ?? 'all',
      from: searchParams.get('from') ?? '',
      to: searchParams.get('to') ?? '',
      offset: Math.max(0, Math.floor(Number(searchParams.get('offset') ?? '0') || 0)),
    };
  }, [searchParams]);

  const detailId = searchParams.get('id');
  const paramsRef = useRef(params);
  paramsRef.current = params;

  // Провайдеры для фильтра и tools выбранного провайдера.
  useEffect(() => {
    let active = true;
    api
      .getProviders()
      .then((list) => {
        if (active) setProviders(list);
      })
      .catch(() => {
        if (active) setProviders([]);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!params.provider) {
      setTools([]);
      return;
    }
    let active = true;
    api
      .getProviderTools(params.provider)
      .then((list) => {
        if (active) setTools(list);
      })
      .catch(() => {
        if (active) setTools([]);
      });
    return () => {
      active = false;
    };
  }, [params.provider]);

  // Основная загрузка списка (с debounce 250 ms, отменой устаревших запросов).
  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      api
        .getLogs(
          {
            search: params.search || undefined,
            provider: params.provider || undefined,
            tool: params.tool || undefined,
            status: params.status ? Number(params.status) : undefined,
            result: params.result === 'all' ? undefined : params.result,
            from: params.from || undefined,
            to: params.to || undefined,
            offset: params.offset,
            limit: PAGE_SIZE,
          },
          { signal: controller.signal },
        )
        .then((result) => {
          setData(result);
          setError(null);
        })
        .catch((err) => {
          if (controller.signal.aborted) return;
          const code = err instanceof ApiError ? err.code : undefined;
          if (code === 'ABORTED') return;
          setError(err instanceof Error ? err.message : 'Failed to load logs');
        });
    }, 250);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [params.search, params.provider, params.tool, params.status, params.result, params.from, params.to, params.offset]);

  // Авто-refresh раз в 10 с; при открытой модалке не обновляем список.
  useEffect(() => {
    if (detailId) return;
    const tick = () => {
      const p = paramsRef.current;
      api
        .getLogs(
          {
            search: p.search || undefined,
            provider: p.provider || undefined,
            tool: p.tool || undefined,
            status: p.status ? Number(p.status) : undefined,
            result: p.result === 'all' ? undefined : p.result,
            from: p.from || undefined,
            to: p.to || undefined,
            offset: p.offset,
            limit: PAGE_SIZE,
          },
          { silent: true },
        )
        .then(setData)
        .catch(() => {
          /* тихо */
        });
    };
    const interval = window.setInterval(tick, REFRESH_MS);
    return () => window.clearInterval(interval);
  }, [detailId]);

  // Открытие детали по ?id=.
  useEffect(() => {
    if (!detailId) {
      setDetail(null);
      setDetailError(null);
      return;
    }
    let active = true;
    setDetailLoading(true);
    setDetailError(null);
    api
      .getLog(detailId)
      .then((entry) => {
        if (active) setDetail(entry);
      })
      .catch((err) => {
        if (active) {
          setDetail(null);
          setDetailError(err instanceof Error ? err.message : 'Failed to load log entry');
        }
      })
      .finally(() => {
        if (active) setDetailLoading(false);
      });
    return () => {
      active = false;
    };
  }, [detailId]);

  const closeDetail = () => {
    const next = new URLSearchParams(searchParams);
    next.delete('id');
    setSearchParams(next, { replace: true });
  };

  const setParam = (key: string, value: string) => {
    const next = new URLSearchParams(searchParams);
    if (value === '' || value === 'all') next.delete(key);
    else next.set(key, value);
    next.delete('offset');
    setSearchParams(next, { replace: true });
  };

  const setOffset = (offset: number) => {
    if (offset < 0) return;
    const next = new URLSearchParams(searchParams);
    if (offset === 0) next.delete('offset');
    else next.set('offset', String(offset));
    setSearchParams(next, { replace: true });
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const resetFilters = () => {
    const next = new URLSearchParams(searchParams);
    for (const key of ['search', 'provider', 'tool', 'status', 'result', 'from', 'to', 'offset']) next.delete(key);
    setSearchParams(next, { replace: true });
  };

  const refresh = () => {
    const p = paramsRef.current;
    setData(null);
    api
      .getLogs({
        search: p.search || undefined,
        provider: p.provider || undefined,
        tool: p.tool || undefined,
        status: p.status ? Number(p.status) : undefined,
        result: p.result === 'all' ? undefined : p.result,
        from: p.from || undefined,
        to: p.to || undefined,
        offset: p.offset,
        limit: PAGE_SIZE,
      })
      .then((result) => {
        setData(result);
        setError(null);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Failed to load logs');
      });
  };

  const onClear = async () => {
    setClearing(true);
    try {
      const result = await api.clearLogs();
      toast(`Deleted ${result.deleted} log file(s)`, 'success');
      closeDetail();
      refresh();
    } catch {
      /* toast показан в client */
    } finally {
      setClearing(false);
      setConfirmClear(false);
    }
  };

  const offset = params.offset;
  const total = data?.total ?? 0;
  const items = data?.items ?? [];
  const from = total === 0 ? 0 : offset + 1;
  const to = offset + items.length;

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Logs</h1>
          <p className="page-subtitle">Запросы AI → MCP → API. Обновление каждые 10 секунд.</p>
        </div>
        <div className="page-actions">
          <Button variant="secondary" onClick={refresh}>
            <IconRefresh size={14} />
            Refresh
          </Button>
          <Button variant="danger" onClick={() => setConfirmClear(true)}>
            <IconTrash size={14} />
            Clear logs
          </Button>
        </div>
      </div>

      <div className="filters-panel">
        <div className="filter-field filter-search">
          <label htmlFor="log-search">Search</label>
          <SearchInput value={params.search} onChange={(v) => setParam('search', v)} placeholder="tool, url, provider…" />
        </div>
        <div className="filter-field">
          <label htmlFor="log-provider">Provider</label>
          <select id="log-provider" value={params.provider} onChange={(event) => setParam('provider', event.target.value)}>
            <option value="">All providers</option>
            {providers.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
        <div className="filter-field">
          <label htmlFor="log-tool">Tool</label>
          <input
            id="log-tool"
            type="text"
            list="log-tools"
            value={params.tool}
            placeholder={params.provider ? 'Tool name…' : 'Select provider first'}
            disabled={!params.provider}
            onChange={(event) => setParam('tool', event.target.value)}
          />
          <datalist id="log-tools">
            {tools.map((t) => (
              <option key={t.name} value={t.name} />
            ))}
          </datalist>
        </div>
        <div className="filter-field">
          <label htmlFor="log-status">Status</label>
          <input
            id="log-status"
            type="number"
            min={100}
            max={599}
            value={params.status}
            placeholder="100–599"
            onChange={(event) => setParam('status', event.target.value)}
          />
        </div>
        <div className="filter-field">
          <label htmlFor="log-result">Result</label>
          <select id="log-result" value={params.result} onChange={(event) => setParam('result', event.target.value)}>
            <option value="all">All</option>
            <option value="success">Success</option>
            <option value="error">Error</option>
          </select>
        </div>
        <div className="filter-field">
          <label htmlFor="log-from">From</label>
          <input id="log-from" type="datetime-local" value={params.from} onChange={(event) => setParam('from', event.target.value)} />
        </div>
        <div className="filter-field">
          <label htmlFor="log-to">To</label>
          <input id="log-to" type="datetime-local" value={params.to} onChange={(event) => setParam('to', event.target.value)} />
        </div>
        <div className="filter-actions">
          <Button variant="ghost" onClick={resetFilters}>
            Reset
          </Button>
        </div>
      </div>

      {error && !data ? <ErrorState message={error} onRetry={refresh} /> : null}
      {!error && !data ? <Spinner text="Loading logs…" /> : null}

      {data && items.length === 0 ? (
        <EmptyState title="No log entries yet — вызовите tool через MCP" description="Или измените фильтры: сейчас они ничего не находят." />
      ) : null}

      {data && items.length > 0 ? (
        <>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Direction</th>
                  <th>Provider</th>
                  <th>Tool</th>
                  <th>Method</th>
                  <th>URL</th>
                  <th>Status</th>
                  <th>Duration</th>
                </tr>
              </thead>
              <tbody>
                {items.map((entry) => (
                  <tr key={entry.id} className="row-clickable" onClick={() => setParam('id', entry.id)} title="View details">
                    <td className="nowrap">{formatDateTime(entry.timestamp)}</td>
                    <td>
                      <Badge kind={directionKind(entry.direction)}>{directionLabel(entry.direction)}</Badge>
                    </td>
                    <td className="mono">{entry.providerName ?? entry.provider}</td>
                    <td className="mono">{entry.tool ?? '—'}</td>
                    <td className="mono">{entry.method}</td>
                    <td className="mono url-cell">{pathOnly(entry.url)}</td>
                    <td>
                      <Badge kind={statusKind(entry.status ?? (entry.success ? 200 : 500))}>{entry.status ?? (entry.success ? 'OK' : 'ERR')}</Badge>
                    </td>
                    <td className="nowrap">{entry.durationMs !== undefined ? `${entry.durationMs} ms` : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="pagination">
            <span className="pagination-info">
              {from}–{to} of {total}
            </span>
            <div className="pagination-buttons">
              <Button size="sm" disabled={offset === 0} onClick={() => setOffset(offset - PAGE_SIZE)}>
                ← Prev
              </Button>
              <Button size="sm" disabled={items.length < PAGE_SIZE || to >= total} onClick={() => setOffset(offset + PAGE_SIZE)}>
                Next →
              </Button>
            </div>
          </div>
        </>
      ) : null}

      <ConfirmDialog
        open={confirmClear}
        title="Clear logs"
        message="Удалить все логи? Это действие необратимо."
        confirmLabel="Delete all"
        danger
        pending={clearing}
        onConfirm={() => void onClear()}
        onCancel={() => setConfirmClear(false)}
      />

      {detailId ? (
        <Modal
          title={
            <span>
              Log detail <span className="mono text-muted">{detailId}</span>
            </span>
          }
          onClose={closeDetail}
          wide
          footer={
            <Button variant="secondary" onClick={closeDetail}>
              Close
            </Button>
          }
        >
          {detailLoading ? <Spinner text="Loading entry…" /> : null}
          {!detailLoading && detailError ? <ErrorState message={detailError} onRetry={closeDetail} /> : null}
          {!detailLoading && detail ? <LogDetail entry={detail} /> : null}
        </Modal>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------- detail

function LogDetail({ entry }: { entry: LogEntry }): ReactNode {
  return (
    <div className="log-detail">
      <div className="log-section">
        <h4 className="log-section-title">Overview</h4>
        <dl className="log-dl">
          <div>
            <dt>Time</dt>
            <dd>{formatDateTime(entry.timestamp)}</dd>
          </div>
          <div>
            <dt>Direction</dt>
            <dd>
              <Badge kind={directionKind(entry.direction)}>{directionLabel(entry.direction)}</Badge>
            </dd>
          </div>
          <div>
            <dt>Provider</dt>
            <dd className="mono">{entry.providerName ?? entry.provider}</dd>
          </div>
          <div>
            <dt>Tool</dt>
            <dd className="mono">{entry.tool ?? '—'}</dd>
          </div>
          <div>
            <dt>Method</dt>
            <dd className="mono">{entry.method}</dd>
          </div>
          <div>
            <dt>Status</dt>
            <dd>
              {entry.status !== undefined ? (
                <Badge kind={statusKind(entry.status)}>{entry.status}</Badge>
              ) : (
                <Badge kind={entry.success ? 'ok' : 'error'}>{entry.success ? 'OK' : 'ERR'}</Badge>
              )}
            </dd>
          </div>
          <div>
            <dt>Duration</dt>
            <dd>{entry.durationMs !== undefined ? `${entry.durationMs} ms` : '—'}</dd>
          </div>
          <div>
            <dt>Attempts</dt>
            <dd>{entry.attempts ?? '—'}</dd>
          </div>
        </dl>
        <div className="log-field">
          <dt>URL</dt>
          <dd className="mono">{entry.url}</dd>
        </div>
      </div>

      {entry.request ? (
        <div className="log-section">
          <h4 className="log-section-title">Request</h4>
          {entry.request.headers ? (
            <div className="log-block">
              <div className="log-block-label">Headers</div>
              <CodeBlock text={formatHeaders(entry.request.headers)} />
            </div>
          ) : null}
          {entry.request.body !== undefined ? (
            <div className="log-block">
              <div className="log-block-label">
                Body
                {entry.request.bodyTruncated ? <span className="log-truncated"> [Request truncated]</span> : null}
              </div>
              <CodeBlock text={entry.request.body} />
            </div>
          ) : null}
        </div>
      ) : null}

      {entry.response ? (
        <div className="log-section">
          <h4 className="log-section-title">Response</h4>
          {entry.response.headers ? (
            <div className="log-block">
              <div className="log-block-label">Headers</div>
              <CodeBlock text={formatHeaders(entry.response.headers)} />
            </div>
          ) : null}
          {entry.response.body !== undefined ? (
            <div className="log-block">
              <div className="log-block-label">
                Body
                {entry.response.bodyTruncated ? <span className="log-truncated"> [Response truncated]</span> : null}
              </div>
              <CodeBlock text={entry.response.body} />
            </div>
          ) : null}
        </div>
      ) : null}

      {entry.error ? (
        <div className="log-section log-section-error">
          <h4 className="log-section-title">Error</h4>
          <dl className="log-dl">
            <div>
              <dt>Kind</dt>
              <dd className="mono">{entry.error.kind}</dd>
            </div>
            <div>
              <dt>Code</dt>
              <dd className="mono">{entry.error.code}</dd>
            </div>
            <div>
              <dt>Retry after</dt>
              <dd>{entry.error.retryAfter !== undefined ? `${entry.error.retryAfter} s` : '—'}</dd>
            </div>
          </dl>
          <div className="log-block">
            <div className="log-block-label">Message</div>
            <CodeBlock text={entry.error.message} />
          </div>
        </div>
      ) : null}
    </div>
  );
}