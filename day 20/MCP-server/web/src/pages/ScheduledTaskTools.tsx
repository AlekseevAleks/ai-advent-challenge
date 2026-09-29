// Scheduled Task Tools `/scheduled-tasks-tools` — настройки MCP tools,
// которые управляют Scheduled Tasks (вкл/выкл доступность для AI-агента).
import { useCallback, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { api } from '../api/client.js';
import type { SchedulerToolInfo } from '../api/types.js';
import { Badge, Button, EmptyState, ErrorState, Spinner, Toggle, toast } from '../components/ui.js';
import { IconRefresh } from '../components/icons.js';

export function ScheduledTaskTools(): ReactNode {
  const [tools, setTools] = useState<SchedulerToolInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<Record<string, boolean>>({});

  const load = useCallback(() => {
    setError(null);
    api
      .listSchedulerTools()
      .then((result) => setTools(result.items))
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load scheduler tools'));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const onToggle = async (tool: SchedulerToolInfo, enabled: boolean) => {
    setPending((prev) => ({ ...prev, [tool.name]: true }));
    try {
      const updated = await api.updateSchedulerTool(tool.name, enabled);
      setTools((prev) => prev?.map((t) => (t.name === updated.name ? updated : t)) ?? prev);
      toast(`${tool.name} ${enabled ? 'enabled' : 'disabled'}`, 'success');
    } catch {
      /* toast в client */
    } finally {
      setPending((prev) => {
        const next = { ...prev };
        delete next[tool.name];
        return next;
      });
    }
  };

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Scheduled Task Tools</h1>
          <p className="page-subtitle">
            MCP tools, которые работают с задачами. Отключённый тул не объявляется AI-агенту и не может быть вызван.
          </p>
        </div>
        <div className="page-actions">
          <Button variant="secondary" onClick={load}>
            <IconRefresh size={14} />
            Refresh
          </Button>
        </div>
      </div>

      {error && !tools ? <ErrorState message={error} onRetry={load} /> : null}
      {!error && !tools ? <Spinner text="Loading scheduler tools…" /> : null}
      {tools && tools.length === 0 ? (
        <EmptyState title="No scheduler tools" description="Scheduler отключён или не настроен." />
      ) : null}
      {tools ? (
        <div className="tools-grid">
          {tools.map((tool) => (
            <div key={tool.name} className={`tool-card${tool.enabled ? '' : ' tool-card-disabled'}`}>
              <div className="tool-card-head">
                <div className="tool-card-title">
                  <span className="mono">{tool.name}</span>
                  {tool.enabled ? <Badge kind="accent">Enabled</Badge> : <Badge kind="muted">Disabled</Badge>}
                </div>
                <Toggle
                  checked={tool.enabled}
                  pending={pending[tool.name] === true}
                  label={`Toggle ${tool.name}`}
                  onChange={(next) => void onToggle(tool, next)}
                />
              </div>
              <p className="tool-card-desc">{tool.description || 'No description'}</p>
              <div className="schema-block">
                {Object.keys(tool.inputSchema.properties ?? {}).length === 0 ? (
                  <span className="schema-type">no input properties</span>
                ) : (
                  <ul className="schema-props">
                    {Object.entries(tool.inputSchema.properties ?? {}).map(([key, prop]) => (
                      <li key={key}>
                        <code className="schema-key">{key}</code>
                        <span className="schema-type">
                          {typeof prop === 'object' && prop !== null && 'type' in prop
                            ? String((prop as { type: unknown }).type)
                            : 'any'}
                        </span>
                        {tool.inputSchema.required?.includes(key) ? <span className="schema-required">*</span> : null}
                      </li>
                    ))}
                  </ul>
                )}
                <details className="schema-details">
                  <summary>JSON Schema</summary>
                  <pre className="code-block">{JSON.stringify(tool.inputSchema, null, 2)}</pre>
                </details>
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}