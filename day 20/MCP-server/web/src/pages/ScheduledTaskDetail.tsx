// Scheduled Task detail `/scheduled-tasks/:id` — статус, summary, история выполнений.
import { useCallback, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { api } from '../api/client.js';
import type { ScheduledTask, SummaryWindow, TaskExecution, TaskHistoryPage, TaskSummary } from '../api/types.js';
import { Badge, Button, Card, ConfirmDialog, EmptyState, ErrorState, JsonView, Modal, Spinner, Stat, toast } from '../components/ui.js';
import { formatDateTime } from '../utils/format.js';
import { humanCron, taskStatusKind } from './ScheduledTasks.js';

const WINDOWS: Array<{ value: SummaryWindow; label: string }> = [
  { value: '1h', label: 'Last hour' },
  { value: '24h', label: 'Last 24 hours' },
  { value: '7d', label: 'Last 7 days' },
  { value: '30d', label: 'Last 30 days' },
  { value: 'all', label: 'All time' },
];

const PAGE_SIZE = 20;

export function ScheduledTaskDetail(): ReactNode {
  const { id = '' } = useParams();
  const navigate = useNavigate();
  const [task, setTask] = useState<ScheduledTask | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<TaskHistoryPage | null>(null);
  const [offset, setOffset] = useState(0);
  const [summary, setSummary] = useState<TaskSummary | null>(null);
  const [window, setWindow] = useState<SummaryWindow>('24h');
  const [busy, setBusy] = useState(false);
  const [detail, setDetail] = useState<TaskExecution | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const loadTask = useCallback(() => {
    api
      .getTask(id)
      .then(setTask)
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load task'));
  }, [id]);

  const loadHistory = useCallback((pageOffset: number) => {
    api
      .taskHistory(id, pageOffset, PAGE_SIZE)
      .then(setHistory)
      .catch(() => undefined);
  }, [id]);

  const loadSummary = useCallback((w: SummaryWindow) => {
    api
      .taskSummary(id, w)
      .then(setSummary)
      .catch(() => undefined);
  }, [id]);

  useEffect(() => {
    loadTask();
    loadHistory(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  useEffect(() => {
    loadSummary(window);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [window]);

  const onRun = async () => {
    setBusy(true);
    try {
      const execution = await api.runTask(id);
      if (execution.status === 'success') {
        toast(`Executed in ${execution.durationMs ?? '?'}ms`, 'success');
      } else {
        toast(`Failed: ${execution.error ?? 'unknown error'}`, 'error');
      }
      loadTask();
      loadHistory(0);
      loadSummary(window);
    } catch {
      /* toast в client */
    } finally {
      setBusy(false);
    }
  };

  const onTogglePause = async () => {
    if (!task) return;
    setBusy(true);
    try {
      const updated = task.enabled ? await api.pauseTask(id) : await api.resumeTask(id);
      setTask(updated);
      toast(updated.enabled ? 'Task resumed' : 'Task paused', 'success');
    } catch {
      /* toast в client */
    } finally {
      setBusy(false);
    }
  };

  const onDelete = async () => {
    try {
      await api.deleteTask(id);
      toast('Task deleted', 'success');
      navigate('/scheduled-tasks');
    } catch {
      /* toast в client */
    } finally {
      setConfirmDelete(false);
    }
  };

  if (error && !task) {
    return (
      <div className="page">
        <ErrorState message={error} onRetry={loadTask} />
        <div className="back-link">
          <Link to="/scheduled-tasks">← Back to tasks</Link>
        </div>
      </div>
    );
  }
  if (!task) return <Spinner text="Loading task…" />;

  const total = history?.total ?? 0;

  return (
    <div className="page">
      <div className="back-link">
        <Link to="/scheduled-tasks">← Back to tasks</Link>
      </div>

      <div className="provider-header">
        <div className="provider-header-main">
          <div className="provider-title">
            {task.name}
            <span className="provider-id mono">{task.id}</span>
            <Badge kind={taskStatusKind(task.status)}>{task.status}</Badge>
            {task.running ? <Badge kind="warn">running</Badge> : null}
          </div>
          {task.description ? <p className="provider-desc">{task.description}</p> : null}
          <div className="badges">
            <Badge kind="neutral">Schedule: {task.schedule.type === 'cron' ? humanCron(task.schedule.cron ?? '') : 'once'}</Badge>
            <Badge kind="neutral">Timezone: {task.schedule.timezone ?? '—'}</Badge>
            <Badge kind="neutral">
              {task.action.provider} / {task.action.tool}
            </Badge>
          </div>
        </div>
        <div className="page-actions">
          <Button variant="secondary" loading={busy} onClick={() => void onRun()}>
            Run now
          </Button>
          <Button variant="secondary" loading={busy} onClick={() => void onTogglePause()}>
            {task.enabled ? 'Pause' : 'Resume'}
          </Button>
          <Button variant="secondary" onClick={() => navigate(`/scheduled-tasks?edit=${encodeURIComponent(task.id)}`)}>
            Edit
          </Button>
          <Button variant="danger" onClick={() => setConfirmDelete(true)}>
            Delete
          </Button>
        </div>
      </div>

      <div className="stat-grid">
        <Stat label="Created" value={formatDateTime(task.createdAt)} />
        <Stat label="Updated" value={formatDateTime(task.updatedAt)} />
        <Stat label="Last execution" value={task.lastRunAt ? formatDateTime(task.lastRunAt) : '—'} />
        <Stat label="Next execution" value={task.nextRunAt ? formatDateTime(task.nextRunAt) : '—'} />
        <Stat label="Executions" value={String(total)} />
        <Stat
          label="Status in window"
          value={
            summary ? (
              <>
                {summary.executions.total} runs · {summary.executions.success} ok · {summary.executions.error} errors
              </>
            ) : (
              '—'
            )
          }
        />
      </div>

      <Card
        title="Summary"
        actions={
          <select className="window-select" value={window} onChange={(event) => setWindow(event.target.value as SummaryWindow)}>
            {WINDOWS.map((w) => (
              <option key={w.value} value={w.value}>
                {w.label}
              </option>
            ))}
          </select>
        }
      >
        {summary ? (
          <div className="summary-block">
            <pre className="code-block summary-text">{summary.summaryText}</pre>
            {Object.keys(summary.numericSeries).length > 0 ? (
              <table className="table table-compact">
                <thead>
                  <tr>
                    <th>Metric</th>
                    <th>Count</th>
                    <th>Min</th>
                    <th>Max</th>
                    <th>Avg</th>
                    <th>Latest</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(summary.numericSeries).map(([path, stats]) => (
                    <tr key={path}>
                      <td className="mono">{path}</td>
                      <td>{stats.count}</td>
                      <td>{stats.min ?? '—'}</td>
                      <td>{stats.max ?? '—'}</td>
                      <td>{stats.avg ?? '—'}</td>
                      <td>{stats.latest ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <EmptyState title="No numeric data yet" description="После нескольких выполнений здесь появятся агрегированные метрики." />
            )}
          </div>
        ) : (
          <Spinner text="Loading summary…" />
        )}
      </Card>

      <Card title={`Execution history (${total})`}>
        {history && history.items.length === 0 ? (
          <EmptyState title="No executions yet" description="Задача ещё не выполнялась. Нажмите Run now или дождитесь расписания." />
        ) : null}
        {history && history.items.length > 0 ? (
          <>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Started</th>
                    <th>Status</th>
                    <th>Duration</th>
                    <th>Error</th>
                  </tr>
                </thead>
                <tbody>
                  {history.items.map((exec) => (
                    <tr key={exec.id} className="row-clickable" onClick={() => setDetail(exec)} title="View details">
                      <td className="nowrap">{formatDateTime(exec.startedAt)}</td>
                      <td>
                        <Badge kind={exec.status === 'success' ? 'ok' : exec.status === 'running' ? 'warn' : 'error'}>{exec.status}</Badge>
                      </td>
                      <td className="nowrap">{exec.durationMs !== undefined ? `${exec.durationMs} ms` : '—'}</td>
                      <td className="mono url-cell">{exec.error ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="pagination">
              <span className="pagination-info">
                {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}
              </span>
              <div className="pagination-buttons">
                <Button size="sm" disabled={offset === 0} onClick={() => { setOffset(offset - PAGE_SIZE); loadHistory(offset - PAGE_SIZE); }}>
                  ← Prev
                </Button>
                <Button size="sm" disabled={offset + PAGE_SIZE >= total} onClick={() => { setOffset(offset + PAGE_SIZE); loadHistory(offset + PAGE_SIZE); }}>
                  Next →
                </Button>
              </div>
            </div>
          </>
        ) : null}
      </Card>

      {detail ? (
        <Modal title={`Execution ${detail.id}`} onClose={() => setDetail(null)} wide>
          <dl className="log-dl">
            <div>
              <dt>Started</dt>
              <dd>{formatDateTime(detail.startedAt)}</dd>
            </div>
            <div>
              <dt>Finished</dt>
              <dd>{detail.finishedAt ? formatDateTime(detail.finishedAt) : '—'}</dd>
            </div>
            <div>
              <dt>Duration</dt>
              <dd>{detail.durationMs !== undefined ? `${detail.durationMs} ms` : '—'}</dd>
            </div>
            <div>
              <dt>Status</dt>
              <dd>
                <Badge kind={detail.status === 'success' ? 'ok' : detail.status === 'running' ? 'warn' : 'error'}>{detail.status}</Badge>
              </dd>
            </div>
          </dl>
          {detail.error ? (
            <div className="log-section log-section-error">
              <h4 className="log-section-title">Error</h4>
              <pre className="code-block">{detail.error}</pre>
            </div>
          ) : null}
          <div className="log-section">
            <h4 className="log-section-title">Result</h4>
            {detail.result !== undefined ? (
              <JsonView data={detail.result} />
            ) : (
              <span className="text-muted">—</span>
            )}
          </div>
          <div className="modal-actions">
            <Button variant="secondary" onClick={() => setDetail(null)}>
              Close
            </Button>
          </div>
        </Modal>
      ) : null}

      <ConfirmDialog
        open={confirmDelete}
        title="Delete scheduled task"
        message={`Удалить задачу "${task.name}" и её историю?`}
        confirmLabel="Delete"
        danger
        pending={busy}
        onConfirm={() => void onDelete()}
        onCancel={() => setConfirmDelete(false)}
      />
    </div>
  );
}