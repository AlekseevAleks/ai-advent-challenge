// Scheduled Tasks `/scheduled-tasks` — список задач и создание/редактирование.
import { useCallback, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { api } from '../api/client.js';
import type { ProviderRuntimeState, ProviderRuntimeTool, ScheduledTask, TaskInput } from '../api/types.js';
import { Badge, Button, Card, ConfirmDialog, EmptyState, ErrorState, Field, Modal, Spinner, Toggle, toast } from '../components/ui.js';
import { IconRefresh } from '../components/icons.js';
import { formatDateTime, formatRelative } from '../utils/format.js';

export const TIMEZONES = ['UTC', 'Europe/Berlin', 'Europe/Moscow', 'Europe/London', 'Europe/Paris', 'Europe/Istanbul', 'America/New_York', 'Asia/Dubai', 'Asia/Tokyo', 'Australia/Sydney'];

const CRON_PRESETS: Array<{ label: string; value: string }> = [
  { label: 'Every minute', value: '* * * * *' },
  { label: 'Every 5 minutes', value: '*/5 * * * *' },
  { label: 'Every 15 minutes', value: '*/15 * * * *' },
  { label: 'Every 30 minutes', value: '*/30 * * * *' },
  { label: 'Every hour', value: '0 * * * *' },
  { label: 'Every 3 hours', value: '0 */3 * * *' },
  { label: 'Every day at 00:00', value: '0 0 * * *' },
  { label: 'Every day at 09:00', value: '0 9 * * *' },
  { label: 'Monday–Friday 09:00', value: '0 9 * * 1-5' },
];

export function humanCron(cron: string): string {
  const presets = new Map(CRON_PRESETS.map((p) => [p.value, p.label]));
  if (presets.has(cron)) return presets.get(cron) as string;
  const parts = cron.trim().split(/\s+/);
  if (parts.length === 5 && parts[2] === '*' && parts[3] === '*' && parts[4] === '*') {
    return `Every day at ${parts[1].padStart(2, '0')}:${parts[0].padStart(2, '0')}`;
  }
  return cron;
}

export function taskStatusKind(status: ScheduledTask['status']): 'accent' | 'muted' | 'ok' | 'error' {
  switch (status) {
    case 'active':
      return 'accent';
    case 'paused':
      return 'muted';
    case 'completed':
      return 'ok';
    case 'error':
      return 'error';
  }
}

function describeSchedule(task: ScheduledTask): string {
  return task.schedule.type === 'once'
    ? `Once at ${formatDateTime(task.schedule.executeAt ?? '')}`
    : humanCron(task.schedule.cron ?? '');
}

// ------------------------------------------------------------------- form

export function TaskForm({
  providers,
  initial,
  submitting,
  onSubmit,
  onCancel,
}: {
  providers: ProviderRuntimeState[];
  initial?: ScheduledTask | null;
  submitting: boolean;
  onSubmit: (input: TaskInput) => Promise<void>;
  onCancel: () => void;
}): ReactNode {
  const editing = !!initial;
  const [name, setName] = useState(initial?.name ?? '');
  const [description, setDescription] = useState(initial?.description ?? '');
  const [enabled, setEnabled] = useState(initial?.enabled ?? true);
  const [scheduleType, setScheduleType] = useState<'once' | 'cron'>(initial?.schedule.type ?? 'cron');
  const [executeAt, setExecuteAt] = useState(() => {
    if (initial?.schedule.type === 'once' && initial.schedule.executeAt) {
      const d = new Date(initial.schedule.executeAt);
      const pad = (n: number) => String(n).padStart(2, '0');
      return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
    }
    return '';
  });
  const [cron, setCron] = useState(initial?.schedule.type === 'cron' ? (initial.schedule.cron ?? '0 * * * *') : '0 * * * *');
  const [timezone, setTimezone] = useState(initial?.schedule.timezone ?? 'UTC');
  const [providerId, setProviderId] = useState(initial?.action.provider ?? providers[0]?.id ?? '');
  const [tool, setTool] = useState(initial?.action.tool ?? '');
  const [inputText, setInputText] = useState(() =>
    initial ? JSON.stringify(initial.action.input ?? {}, null, 2) : '{\n  \n}',
  );
  const [actionType, setActionType] = useState<'provider_tool' | 'pipeline'>(
    initial?.action.type === 'pipeline' ? 'pipeline' : 'provider_tool',
  );
  const [pipelineId, setPipelineId] = useState(initial?.action.type === 'pipeline' ? (initial.action.pipeline ?? '') : '');
  const [pipelines, setPipelines] = useState<Array<{ id: string; name: string }>>([]);
  const [localError, setLocalError] = useState<string | null>(null);

  useEffect(() => {
    void api
      .listPipelines()
      .then((result) => setPipelines(result.items))
      .catch(() => setPipelines([]));
  }, []);

  const provider = providers.find((p) => p.id === providerId);
  const tools = provider?.tools ?? [];

  useEffect(() => {
    if (provider && !tools.some((t) => t.name === tool)) {
      setTool(tools.find((t) => t.enabled)?.name ?? '');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [providerId, provider?.id]);

  const selectedTool: ProviderRuntimeTool | undefined = tools.find((t) => t.name === tool);

  const validate = (): TaskInput | null => {
    if (!name.trim()) {
      setLocalError('Task name is required');
      return null;
    }
    if (actionType === 'pipeline') {
      if (!pipelineId) {
        setLocalError('Select a pipeline');
        return null;
      }
    } else {
      if (!provider) {
        setLocalError('Select a provider');
        return null;
      }
      if (!selectedTool) {
        setLocalError('Select a tool');
        return null;
      }
    }
    let input: unknown = {};
    try {
      const parsed = JSON.parse(inputText || '{}');
      if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
        setLocalError('Input must be a JSON object');
        return null;
      }
      input = parsed;
    } catch {
      setLocalError('Input must be valid JSON');
      return null;
    }
    if (scheduleType === 'once') {
      if (!executeAt) {
        setLocalError('executeAt is required for once tasks');
        return null;
      }
      const ms = Date.parse(executeAt);
      if (Number.isNaN(ms)) {
        setLocalError('Invalid executeAt');
        return null;
      }
      if (ms <= Date.now()) {
        setLocalError('executeAt must be in the future');
        return null;
      }
    } else if (!cron.trim()) {
      setLocalError('Cron expression is required');
      return null;
    }
    return {
      name: name.trim(),
      description: description.trim() || undefined,
      enabled,
      schedule: scheduleType === 'once' ? { type: 'once', executeAt: new Date(executeAt).toISOString(), timezone } : { type: 'cron', cron: cron.trim(), timezone },
      action:
        actionType === 'pipeline'
          ? { type: 'pipeline', pipeline: pipelineId, input }
          : { type: 'provider_tool', provider: provider?.id ?? '', tool: selectedTool?.name ?? '', input },
    };
  };

  const submit = () => {
    const input = validate();
    if (!input) return;
    setLocalError(null);
    void onSubmit(input);
  };

  return (
    <form
      className="task-form"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      {localError ? <div className="callout">{localError}</div> : null}
      <div className="form-grid">
        <Field label="Task name" required>
          <input type="text" value={name} onChange={(event) => setName(event.target.value)} placeholder="Berlin Weather" />
        </Field>
        <Field label="Description">
          <input type="text" value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Раз в час собирать погоду в Берлине" />
        </Field>
      </div>

      <Card title="Schedule">
        <div className="schedule-type">
          <label className="radio-label">
            <input type="radio" name="schedule-type" checked={scheduleType === 'cron'} onChange={() => setScheduleType('cron')} />
            Cron (повторяется)
          </label>
          <label className="radio-label">
            <input type="radio" name="schedule-type" checked={scheduleType === 'once'} onChange={() => setScheduleType('once')} />
            Once (однократно)
          </label>
        </div>
        {scheduleType === 'cron' ? (
          <div className="form-grid">
            <Field label="Cron" hint='Формат: "минута час день-месяца месяц день-недели"' required>
              <select className="cron-preset" value={cron} onChange={(event) => setCron(event.target.value)}>
                {CRON_PRESETS.map((p) => (
                  <option key={p.value} value={p.value}>
                    {p.label} — {p.value}
                  </option>
                ))}
                {!CRON_PRESETS.some((p) => p.value === cron) ? <option value={cron}>{cron}</option> : null}
              </select>
              <input type="text" value={cron} onChange={(event) => setCron(event.target.value)} placeholder="0 * * * *" />
            </Field>
            <Field label="Timezone" required>
              <input type="text" list="tz-list" value={timezone} onChange={(event) => setTimezone(event.target.value)} placeholder="Europe/Berlin" />
              <datalist id="tz-list">
                {TIMEZONES.map((tz) => (
                  <option key={tz} value={tz} />
                ))}
              </datalist>
            </Field>
          </div>
        ) : (
          <div className="form-grid">
            <Field label="Execute at" hint="Локальное время; сохраняется в UTC" required>
              <input type="datetime-local" value={executeAt} onChange={(event) => setExecuteAt(event.target.value)} />
            </Field>
            <Field label="Timezone" required>
              <input type="text" list="tz-list" value={timezone} onChange={(event) => setTimezone(event.target.value)} placeholder="Europe/Berlin" />
              <datalist id="tz-list">
                {TIMEZONES.map((tz) => (
                  <option key={tz} value={tz} />
                ))}
              </datalist>
            </Field>
          </div>
        )}
      </Card>

      <Card title="Action">
        <div className="schedule-type">
          <label className="radio-label">
            <input type="radio" name="action-type" checked={actionType === 'provider_tool'} onChange={() => setActionType('provider_tool')} />
            Provider tool
          </label>
          <label className="radio-label">
            <input type="radio" name="action-type" checked={actionType === 'pipeline'} onChange={() => setActionType('pipeline')} />
            Pipeline
          </label>
        </div>
        {actionType === 'pipeline' ? (
          <div className="form-grid">
            <Field label="Pipeline" required hint="Scheduler будет запускать pipeline по расписанию.">
              <select value={pipelineId} onChange={(event) => setPipelineId(event.target.value)}>
                {pipelines.length === 0 ? <option value="">— no pipelines —</option> : null}
                {pipelines.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} ({p.id})
                  </option>
                ))}
              </select>
            </Field>
          </div>
        ) : (
          <div className="form-grid">
            <Field label="Provider" required>
              <select
                value={providerId}
                onChange={(event) => {
                  setProviderId(event.target.value);
                  setTool('');
                }}
              >
                {providers.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} ({p.id})
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Tool" required>
              <select value={tool} onChange={(event) => setTool(event.target.value)}>
                {tools.length === 0 ? <option value="">— no tools —</option> : null}
                {tools.map((t) => (
                  <option key={t.name} value={t.name} disabled={!t.enabled}>
                    {t.name} {t.enabled ? '' : '(disabled)'}
                  </option>
                ))}
              </select>
            </Field>
          </div>
        )}
        {selectedTool ? (
          <div className="schema-block">
            <span className="field-hint">{selectedTool.description}</span>
            <ul className="schema-props">
              {Object.entries(selectedTool.inputSchema.properties ?? {}).map(([key, prop]) => (
                <li key={key}>
                  <code className="schema-key">{key}</code>
                  <span className="schema-type">{typeof prop === 'object' && prop !== null && 'type' in prop ? String((prop as { type: unknown }).type) : 'any'}</span>
                  {selectedTool.inputSchema.required?.includes(key) ? <span className="schema-required">*</span> : null}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        <Field label="Input (JSON)" hint="Аргументы tool, которые будут передаваться при каждом запуске.">
          <textarea
            className="json-input"
            rows={5}
            spellCheck={false}
            value={inputText}
            onChange={(event) => setInputText(event.target.value)}
            placeholder={'{\n  "latitude": 52.52\n}'}
          />
        </Field>
      </Card>

      <div className="toggle-row">
        <div>
          <div className="toggle-row-label">{editing ? 'Enabled' : 'Create enabled'}</div>
          <div className="field-hint">Если выключена — scheduler не будет запускать задачу.</div>
        </div>
        <Toggle checked={enabled} label="Enabled" onChange={setEnabled} />
      </div>

      <div className="modal-actions">
        <Button variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
        <Button variant="primary" loading={submitting} onClick={submit}>
          {editing ? 'Save changes' : 'Create task'}
        </Button>
      </div>
    </form>
  );
}

// ------------------------------------------------------------------- list page

export function ScheduledTasks(): ReactNode {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const [tasks, setTasks] = useState<ScheduledTask[] | null>(null);
  const [providers, setProviders] = useState<ProviderRuntimeState[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<ScheduledTask | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<ScheduledTask | null>(null);
  const [seeding, setSeeding] = useState(false);

  const editId = searchParams.get('edit');

  const load = useCallback(() => {
    setError(null);
    api
      .listTasks()
      .then((result) => setTasks(result.items))
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load tasks'));
  }, []);

  useEffect(() => {
    void load();
    void api
      .getProviders()
      .then(setProviders)
      .catch(() => setProviders([]));
  }, [load]);

  useEffect(() => {
    if (editId) {
      api
        .getTask(editId)
        .then((task) => setEditing(task))
        .catch(() => setEditing(null));
    } else {
      setEditing(null);
    }
  }, [editId]);

  const closeEditor = () => {
    const next = new URLSearchParams(searchParams);
    next.delete('edit');
    setSearchParams(next, { replace: true });
    setCreating(false);
  };

  const onSubmit = async (input: TaskInput) => {
    setSubmitting(true);
    try {
      if (editing) {
        const updated = await api.updateTask(editing.id, input);
        setEditing(updated);
        toast(`Task "${updated.name}" saved`, 'success');
      } else {
        const created = await api.createTask(input);
        toast(`Task created: ${created.id}`, 'success');
      }
      closeEditor();
      load();
    } catch {
      /* toast в client */
    } finally {
      setSubmitting(false);
    }
  };

  const onRun = async (task: ScheduledTask) => {
    setBusyId(task.id);
    try {
      const execution = await api.runTask(task.id);
      if (execution.status === 'success') {
        toast(`${task.name}: executed in ${execution.durationMs ?? '?'}ms`, 'success');
      } else {
        toast(`${task.name}: failed — ${execution.error ?? 'unknown error'}`, 'error');
      }
      load();
    } catch {
      /* toast в client */
    } finally {
      setBusyId(null);
    }
  };

  const onTogglePause = async (task: ScheduledTask) => {
    setBusyId(task.id);
    try {
      if (task.enabled) await api.pauseTask(task.id);
      else await api.resumeTask(task.id);
      toast(task.enabled ? `${task.name} paused` : `${task.name} resumed`, 'success');
      load();
    } catch {
      /* toast в client */
    } finally {
      setBusyId(null);
    }
  };

  const onConfirmDelete = async () => {
    if (!confirmDelete) return;
    try {
      await api.deleteTask(confirmDelete.id);
      toast(`Task "${confirmDelete.name}" deleted`, 'success');
      load();
    } catch {
      /* toast в client */
    } finally {
      setConfirmDelete(null);
    }
  };

  const onSeedDemo = async () => {
    setSeeding(true);
    try {
      const { created } = await api.createDemoTasks();
      toast(created.length ? `Demo tasks created: ${created.join(', ')}` : 'Demo tasks already exist', created.length ? 'success' : 'info');
      load();
    } catch {
      /* toast в client */
    } finally {
      setSeeding(false);
    }
  };

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Scheduled Tasks</h1>
          <p className="page-subtitle">Задачи, которые MCP Gateway выполняет по расписанию через существующие providers.</p>
        </div>
        <div className="page-actions">
          <Button variant="secondary" loading={seeding} onClick={() => void onSeedDemo()}>
            Create demo tasks
          </Button>
          <Button variant="secondary" onClick={load}>
            <IconRefresh size={14} />
            Refresh
          </Button>
          <Button variant="primary" onClick={() => setCreating(true)}>
            Create task
          </Button>
        </div>
      </div>

      {error && !tasks ? <ErrorState message={error} onRetry={load} /> : null}
      {!error && !tasks ? <Spinner text="Loading tasks…" /> : null}
      {tasks && tasks.length === 0 ? (
        <EmptyState
          title="No scheduled tasks yet"
          description="Создайте задачу: она будет периодически вызывать существующий provider tool (weather, github, ...) и сохранять результаты. Или нажмите «Create demo tasks»."
        />
      ) : null}
      {tasks && tasks.length > 0 ? (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Provider / Tool</th>
                <th>Schedule</th>
                <th>Status</th>
                <th>Last run</th>
                <th>Next run</th>
                <th className="actions-col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((task) => (
                <tr key={task.id} className={task.enabled ? '' : 'row-muted'}>
                  <td>
                    <Link to={`/scheduled-tasks/${encodeURIComponent(task.id)}`} className="provider-name-link">
                      {task.name}
                    </Link>
                    <span className="mono text-muted"> · {task.id}</span>
                  </td>
                  <td className="mono">
                    {task.action.provider} / {task.action.tool}
                  </td>
                  <td>{describeSchedule(task)}</td>
                  <td>
                    <Badge kind={taskStatusKind(task.status)}>{task.status}</Badge>
                    {task.running ? <Badge kind="warn">running</Badge> : null}
                  </td>
                  <td className="nowrap">{task.lastRunAt ? formatRelative(task.lastRunAt) : '—'}</td>
                  <td className="nowrap">{task.nextRunAt ? formatDateTime(task.nextRunAt) : '—'}</td>
                  <td>
                    <div className="row-actions">
                      <Button size="sm" loading={busyId === task.id} disabled={task.running} onClick={() => void onRun(task)}>
                        Run now
                      </Button>
                      <Button size="sm" variant="secondary" onClick={() => void onTogglePause(task)}>
                        {task.enabled ? 'Pause' : 'Resume'}
                      </Button>
                      <Button size="sm" variant="secondary" onClick={() => navigate(`/scheduled-tasks?edit=${encodeURIComponent(task.id)}`)}>
                        Edit
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(task)}>
                        Delete
                      </Button>
                      <Link className="btn btn-secondary btn-sm" to={`/scheduled-tasks/${encodeURIComponent(task.id)}`}>
                        History
                      </Link>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {creating || editing ? (
        <Modal
          title={editing ? `Edit: ${editing.name}` : 'Create scheduled task'}
          onClose={closeEditor}
          wide
          footer={null}
        >
          <TaskForm
            providers={providers}
            initial={editing}
            submitting={submitting}
            onSubmit={onSubmit}
            onCancel={closeEditor}
          />
        </Modal>
      ) : null}

      <ConfirmDialog
        open={!!confirmDelete}
        title="Delete scheduled task"
        message={`Удалить задачу "${confirmDelete?.name}"? История её выполнений также будет удалена.`}
        confirmLabel="Delete"
        danger
        pending={busyId === confirmDelete?.id}
        onConfirm={() => void onConfirmDelete()}
        onCancel={() => setConfirmDelete(null)}
      />
    </div>
  );
}