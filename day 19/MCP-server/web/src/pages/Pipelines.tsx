// Pipelines `/pipelines` — композиция MCP tools: список, создание/редактирование,
// Run, история выполнений, детализация execution.
import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { api } from '../api/client.js';
import type { Pipeline, PipelineExecution, PipelineInputBody, PipelineStepInput, ProviderRuntimeState } from '../api/types.js';
import { Badge, Button, Card, ConfirmDialog, EmptyState, ErrorState, Field, Modal, Spinner, toast } from '../components/ui.js';
import { IconRefresh } from '../components/icons.js';
import { formatDateTime } from '../utils/format.js';

const CORE_TOOLS = ['summarize', 'saveToFile'];

function renderSteps(steps: Pipeline['steps']): ReactNode {
  return (
    <span className="pipeline-steps">
      {steps.map((step, i) => (
        <span key={step.id} className="pipeline-step">
          {i > 0 ? <span className="pipeline-arrow">→</span> : null}
          <code>{step.tool}</code>
        </span>
      ))}
    </span>
  );
}

function PipelineEditor({
  initial,
  providers,
  submitting,
  onSubmit,
  onCancel,
}: {
  initial?: Pipeline | null;
  providers: ProviderRuntimeState[];
  submitting: boolean;
  onSubmit: (input: PipelineInputBody) => Promise<void>;
  onCancel: () => void;
}): ReactNode {
  const [name, setName] = useState(initial?.name ?? '');
  const [description, setDescription] = useState(initial?.description ?? '');
  const [steps, setSteps] = useState<PipelineStepInput[]>(
    initial?.steps.map((s) => ({ id: s.id, tool: s.tool, input: JSON.stringify(s.input ?? {}, null, 2) })) ?? [newStep()],
  );
  const [localError, setLocalError] = useState<string | null>(null);

  const toolOptions = useMemo(() => {
    const set = new Set<string>(CORE_TOOLS);
    for (const p of providers) for (const t of p.tools) if (t.enabled) set.add(t.name);
    return [...set].sort();
  }, [providers]);

  function newStep(): PipelineStepInput {
    return { id: '', tool: toolOptions[0] ?? 'summarize', input: '{\n  \n}' };
  }

  const updateStep = (index: number, patch: Partial<PipelineStepInput>) => {
    setSteps((prev) => prev.map((s, i) => (i === index ? { ...s, ...patch } : s)));
  };

  const submit = () => {
    if (!name.trim()) return setLocalError('Pipeline name is required');
    if (steps.some((s) => !s.id.trim())) return setLocalError('Every step needs an id');
    const ids = steps.map((s) => s.id.trim());
    if (new Set(ids).size !== ids.length) return setLocalError('Step ids must be unique');
    const parsedSteps: PipelineStepInput[] = [];
    for (const step of steps) {
      try {
        const input = JSON.parse(step.input as string || '{}');
        parsedSteps.push({ id: step.id.trim(), tool: step.tool, input });
      } catch {
        return setLocalError(`Step "${step.id}" input is not valid JSON`);
      }
    }
    setLocalError(null);
    void onSubmit({ name: name.trim(), description: description.trim() || undefined, steps: parsedSteps });
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
        <Field label="Name" required>
          <input type="text" value={name} onChange={(event) => setName(event.target.value)} placeholder="GitHub Issues Summary" />
        </Field>
        <Field label="Description">
          <input type="text" value={description} onChange={(event) => setDescription(event.target.value)} />
        </Field>
      </div>

      <Card title={`Steps (${steps.length})`}>
        {steps.map((step, index) => (
          <div key={index} className="pipeline-step-editor">
            <Field label={`Step ${index + 1}: id`}>
              <input type="text" value={step.id} onChange={(event) => updateStep(index, { id: event.target.value })} placeholder="getIssues" />
            </Field>
            <Field label="Tool">
              <select value={step.tool} onChange={(event) => updateStep(index, { tool: event.target.value })}>
                {toolOptions.map((tool) => (
                  <option key={tool} value={tool}>
                    {tool}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Input (JSON, шаблоны {{input.*}} / {{steps.<id>.output}})">
              <textarea className="json-input" rows={3} spellCheck={false} value={step.input as string} onChange={(event) => updateStep(index, { input: event.target.value })} />
            </Field>
            <div className="modal-actions">
              <Button variant="ghost" onClick={() => setSteps((prev) => prev.filter((_, i) => i !== index))} disabled={steps.length === 1}>
                Remove step
              </Button>
            </div>
          </div>
        ))}
        <Button variant="secondary" onClick={() => setSteps((prev) => [...prev, newStep()])}>
          + Add step
        </Button>
      </Card>

      <div className="modal-actions">
        <Button variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
        <Button variant="primary" loading={submitting} onClick={submit}>
          {initial ? 'Save changes' : 'Create pipeline'}
        </Button>
      </div>
    </form>
  );
}

export function Pipelines(): ReactNode {
  const [items, setItems] = useState<Pipeline[] | null>(null);
  const [providers, setProviders] = useState<ProviderRuntimeState[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<Pipeline | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<Pipeline | null>(null);
  const [historyFor, setHistoryFor] = useState<Pipeline | null>(null);
  const [history, setHistory] = useState<{ items: PipelineExecution[]; total: number } | null>(null);
  const [detail, setDetail] = useState<PipelineExecution | null>(null);
  const [seeding, setSeeding] = useState(false);

  const load = useCallback(() => {
    setError(null);
    api
      .listPipelines()
      .then((result) => setItems(result.items))
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load pipelines'));
  }, []);

  useEffect(() => {
    load();
    void api.getProviders().then(setProviders).catch(() => setProviders([]));
  }, [load]);

  const onSubmit = async (input: PipelineInputBody) => {
    setSubmitting(true);
    try {
      if (editing) {
        await api.updatePipeline(editing.id, input);
        toast(`Pipeline "${input.name}" saved`, 'success');
      } else {
        const created = await api.createPipeline(input);
        toast(`Pipeline created: ${created.id}`, 'success');
      }
      setCreating(false);
      setEditing(null);
      load();
    } catch {
      /* toast в client */
    } finally {
      setSubmitting(false);
    }
  };

  const onRun = async (pipeline: Pipeline) => {
    setBusyId(pipeline.id);
    try {
      const result = await api.runPipeline(pipeline.id, {});
      toast(`${pipeline.name}: ${result.status} (${result.durationMs ?? '?'}ms)`, result.status === 'completed' ? 'success' : 'error');
      load();
    } catch {
      /* toast в client */
    } finally {
      setBusyId(null);
    }
  };

  const onSeed = async () => {
    setSeeding(true);
    try {
      const { created } = await api.seedPipelines();
      toast(created.length ? `Demo pipelines created: ${created.join(', ')}` : 'Demo pipelines already exist', created.length ? 'success' : 'info');
      load();
    } catch {
      /* toast в client */
    } finally {
      setSeeding(false);
    }
  };

  const openHistory = async (pipeline: Pipeline) => {
    setHistoryFor(pipeline);
    setHistory(null);
    try {
      const page = await api.pipelineHistory(pipeline.id, 0, 20);
      setHistory({ items: page.items, total: page.total });
    } catch {
      setHistory({ items: [], total: 0 });
    }
  };

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Pipelines</h1>
          <p className="page-subtitle">Композиция MCP tools: output одного шага передаётся следующему через шаблоны.</p>
        </div>
        <div className="page-actions">
          <Button variant="secondary" loading={seeding} onClick={() => void onSeed()}>
            Create demo
          </Button>
          <Button variant="secondary" onClick={load}>
            <IconRefresh size={14} />
            Refresh
          </Button>
          <Button variant="primary" onClick={() => setCreating(true)}>
            Create pipeline
          </Button>
        </div>
      </div>

      {error && !items ? <ErrorState message={error} onRetry={load} /> : null}
      {!error && !items ? <Spinner text="Loading pipelines…" /> : null}
      {items && items.length === 0 ? (
        <EmptyState title="No pipelines yet" description="Создайте pipeline (например, github-list → summarize → saveToFile) или нажмите Create demo." />
      ) : null}
      {items && items.length > 0 ? (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Steps</th>
                <th>Last run</th>
                <th className="actions-col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((pipeline) => (
                <tr key={pipeline.id} className={pipeline.enabled ? '' : 'row-muted'}>
                  <td>
                    <span className="provider-name-link">{pipeline.name}</span>
                    <span className="mono text-muted"> · {pipeline.id}</span>
                    {pipeline.description ? <div className="field-hint">{pipeline.description}</div> : null}
                  </td>
                  <td>{renderSteps(pipeline.steps)}</td>
                  <td className="nowrap">{pipeline.lastRunAt ? formatDateTime(pipeline.lastRunAt) : '—'}</td>
                  <td>
                    <div className="row-actions">
                      <Button size="sm" loading={busyId === pipeline.id} onClick={() => void onRun(pipeline)}>
                        Run
                      </Button>
                      <Button size="sm" variant="secondary" onClick={() => setEditing(pipeline)}>
                        Edit
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => void openHistory(pipeline)}>
                        History
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(pipeline)}>
                        Delete
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {creating || editing ? (
        <Modal title={editing ? `Edit: ${editing.name}` : 'Create pipeline'} onClose={() => { setCreating(false); setEditing(null); }} wide>
          <PipelineEditor
            initial={editing}
            providers={providers}
            submitting={submitting}
            onSubmit={onSubmit}
            onCancel={() => {
              setCreating(false);
              setEditing(null);
            }}
          />
        </Modal>
      ) : null}

      {historyFor ? (
        <Modal title={`History: ${historyFor.name}`} onClose={() => setHistoryFor(null)} wide>
          {!history ? (
            <Spinner text="Loading history…" />
          ) : history.items.length === 0 ? (
            <EmptyState title="No executions yet" description="Запустите pipeline, чтобы появилась история." />
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Started</th>
                  <th>Status</th>
                  <th>Duration</th>
                  <th>Failed step</th>
                </tr>
              </thead>
              <tbody>
                {history.items.map((exec) => (
                  <tr key={exec.id} className="row-clickable" onClick={() => setDetail(exec)}>
                    <td className="nowrap">{formatDateTime(exec.startedAt)}</td>
                    <td>
                      <Badge kind={exec.status === 'completed' ? 'ok' : exec.status === 'running' ? 'warn' : 'error'}>{exec.status}</Badge>
                    </td>
                    <td>{exec.durationMs !== undefined ? `${exec.durationMs} ms` : '—'}</td>
                    <td className="mono">{exec.failedStep ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Modal>
      ) : null}

      {detail ? (
        <Modal title={`Execution ${detail.id}`} onClose={() => setDetail(null)} wide>
          <dl className="log-dl">
            <div>
              <dt>Pipeline</dt>
              <dd className="mono">{detail.pipelineId}</dd>
            </div>
            <div>
              <dt>Status</dt>
              <dd>
                <Badge kind={detail.status === 'completed' ? 'ok' : detail.status === 'running' ? 'warn' : 'error'}>{detail.status}</Badge>
              </dd>
            </div>
            <div>
              <dt>Duration</dt>
              <dd>{detail.durationMs !== undefined ? `${detail.durationMs} ms` : '—'}</dd>
            </div>
            <div>
              <dt>Error</dt>
              <dd className="mono">{detail.error ?? '—'}</dd>
            </div>
          </dl>
          <h4 className="log-section-title">Steps</h4>
          <ul className="schema-props">
            {detail.steps.map((step) => (
              <li key={step.id}>
                <code className="schema-key">{step.id}</code>
                <span className="schema-type">{step.tool}</span>
                <Badge kind={step.status === 'completed' ? 'ok' : step.status === 'failed' ? 'error' : 'muted'}>{step.status}</Badge>
                {step.error ? <span className="field-hint"> — {step.error}</span> : null}
              </li>
            ))}
          </ul>
          <div className="modal-actions">
            <Button variant="secondary" onClick={() => setDetail(null)}>
              Close
            </Button>
          </div>
        </Modal>
      ) : null}

      <ConfirmDialog
        open={!!confirmDelete}
        title="Delete pipeline"
        message={`Удалить pipeline "${confirmDelete?.name}" и его историю?`}
        confirmLabel="Delete"
        danger
        onConfirm={async () => {
          if (!confirmDelete) return;
          try {
            await api.deletePipeline(confirmDelete.id);
            toast(`Pipeline "${confirmDelete.name}" deleted`, 'success');
            load();
          } catch {
            /* toast в client */
          } finally {
            setConfirmDelete(null);
          }
        }}
        onCancel={() => setConfirmDelete(null)}
      />
    </div>
  );
}