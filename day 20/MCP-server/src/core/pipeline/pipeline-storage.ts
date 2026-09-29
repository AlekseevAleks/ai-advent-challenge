import { mkdirSync } from 'node:fs';
import path from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import { configError } from '../errors.js';
import { safeStringify } from '../util/redact.js';
import type { Pipeline, PipelineExecution, PipelineStepInput, PipelineStepResult } from './types.js';

export interface PipelineRow {
  id: string;
  name: string;
  description: string | null;
  enabled: number;
  steps_json: string;
  created_at: string;
  updated_at: string;
  last_run_at: string | null;
}

export interface PipelineExecutionRow {
  id: string;
  pipeline_id: string;
  started_at: string;
  finished_at: string | null;
  status: string;
  steps_json: string;
  duration_ms: number | null;
  failed_step: string | null;
  error_text: string | null;
}

export function rowToPipeline(row: PipelineRow): Pipeline {
  return {
    id: row.id,
    name: row.name,
    description: row.description ?? undefined,
    enabled: row.enabled === 1,
    steps: parseJson<PipelineStepInput[]>(row.steps_json, []),
    createdAt: row.created_at,
    updatedAt: row.updated_at,
    lastRunAt: row.last_run_at ?? undefined,
  };
}

export function pipelineToRow(pipeline: Pipeline): PipelineRow {
  return {
    id: pipeline.id,
    name: pipeline.name,
    description: pipeline.description ?? null,
    enabled: pipeline.enabled ? 1 : 0,
    steps_json: safeStringify(pipeline.steps),
    created_at: pipeline.createdAt,
    updated_at: pipeline.updatedAt,
    last_run_at: pipeline.lastRunAt ?? null,
  };
}

export function rowToExecution(row: PipelineExecutionRow): PipelineExecution {
  return {
    id: row.id,
    pipelineId: row.pipeline_id,
    startedAt: row.started_at,
    finishedAt: row.finished_at ?? undefined,
    status: row.status as PipelineExecution['status'],
    steps: parseJson<PipelineStepResult[]>(row.steps_json, []),
    durationMs: row.duration_ms ?? undefined,
    failedStep: row.failed_step ?? undefined,
    error: row.error_text ?? undefined,
  };
}

function parseJson<T>(json: string, fallback: T): T {
  try {
    return JSON.parse(json) as T;
  } catch {
    return fallback;
  }
}

/**
 * PipelineStorage: SQLite-хранилище pipeline-ов и истории выполнений
 * (data/pipelines.db, встроенный node:sqlite — как у Scheduler).
 */
export class PipelineStorage {
  readonly dbPath: string;
  private readonly db: DatabaseSync;

  constructor(dbPath: string) {
    this.dbPath = path.resolve(dbPath);
    mkdirSync(path.dirname(this.dbPath), { recursive: true });
    try {
      this.db = new DatabaseSync(this.dbPath);
    } catch (err) {
      throw configError(`Cannot open pipeline database: ${err instanceof Error ? err.message : String(err)}`, 'PIPELINE_DB_OPEN_FAILED', err);
    }
    this.db.exec('PRAGMA journal_mode = WAL;');
    this.db.exec(`CREATE TABLE IF NOT EXISTS pipelines (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      description TEXT,
      enabled INTEGER NOT NULL DEFAULT 1,
      steps_json TEXT NOT NULL,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      last_run_at TEXT
    )`);
    this.db.exec(`CREATE TABLE IF NOT EXISTS pipeline_executions (
      id TEXT PRIMARY KEY,
      pipeline_id TEXT NOT NULL,
      started_at TEXT NOT NULL,
      finished_at TEXT,
      status TEXT NOT NULL,
      steps_json TEXT NOT NULL,
      duration_ms INTEGER,
      failed_step TEXT,
      error_text TEXT
    )`);
    this.db.exec('CREATE INDEX IF NOT EXISTS idx_pipe_exec ON pipeline_executions(pipeline_id, started_at DESC)');
  }

  close(): void {
    try {
      this.db.close();
    } catch {
      /* уже закрыт */
    }
  }

  listPipelines(): PipelineRow[] {
    return this.all<PipelineRow>('SELECT * FROM pipelines ORDER BY created_at ASC');
  }

  getPipeline(id: string): PipelineRow | null {
    return this.get<PipelineRow>('SELECT * FROM pipelines WHERE id = ?', id);
  }

  insertPipeline(pipeline: Pipeline): void {
    const row = pipelineToRow(pipeline);
    this.run(
      'INSERT INTO pipelines (id, name, description, enabled, steps_json, created_at, updated_at, last_run_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
      row.id,
      row.name,
      row.description,
      row.enabled,
      row.steps_json,
      row.created_at,
      row.updated_at,
      row.last_run_at,
    );
  }

  updatePipeline(pipeline: Pipeline): void {
    const row = pipelineToRow(pipeline);
    this.run(
      'UPDATE pipelines SET name = ?, description = ?, enabled = ?, steps_json = ?, updated_at = ?, last_run_at = ? WHERE id = ?',
      row.name,
      row.description,
      row.enabled,
      row.steps_json,
      row.updated_at,
      row.last_run_at,
      row.id,
    );
  }

  deletePipeline(id: string): boolean {
    this.run('DELETE FROM pipeline_executions WHERE pipeline_id = ?', id);
    return this.run('DELETE FROM pipelines WHERE id = ?', id) > 0;
  }

  insertExecution(exec: PipelineExecution): void {
    this.run(
      'INSERT INTO pipeline_executions (id, pipeline_id, started_at, finished_at, status, steps_json, duration_ms, failed_step, error_text) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
      exec.id,
      exec.pipelineId,
      exec.startedAt,
      exec.finishedAt ?? null,
      exec.status,
      safeStringify(exec.steps),
      exec.durationMs ?? null,
      exec.failedStep ?? null,
      exec.error ?? null,
    );
  }

  finishExecution(exec: PipelineExecution): void {
    this.run(
      'UPDATE pipeline_executions SET finished_at = ?, status = ?, steps_json = ?, duration_ms = ?, failed_step = ?, error_text = ? WHERE id = ?',
      exec.finishedAt ?? null,
      exec.status,
      safeStringify(exec.steps),
      exec.durationMs ?? null,
      exec.failedStep ?? null,
      exec.error ?? null,
      exec.id,
    );
  }

  getExecution(id: string): PipelineExecutionRow | null {
    return this.get<PipelineExecutionRow>('SELECT * FROM pipeline_executions WHERE id = ?', id);
  }

  listExecutions(pipelineId: string, offset: number, limit: number): { rows: PipelineExecutionRow[]; total: number } {
    const total = this.get<{ c: number }>('SELECT COUNT(*) AS c FROM pipeline_executions WHERE pipeline_id = ?', pipelineId)?.c ?? 0;
    const rows = this.all<PipelineExecutionRow>(
      'SELECT * FROM pipeline_executions WHERE pipeline_id = ? ORDER BY started_at DESC LIMIT ? OFFSET ?',
      pipelineId,
      Math.max(0, limit),
      Math.max(0, offset),
    );
    return { rows, total };
  }

  /** Retention: оставить только последние N выполнений на pipeline. */
  pruneExecutions(maxPerPipeline: number): number {
    let removed = 0;
    const pipelines = this.all<{ id: string }>('SELECT id FROM pipelines');
    for (const { id } of pipelines) {
      removed += this.run(
        'DELETE FROM pipeline_executions WHERE pipeline_id = ? AND id NOT IN (SELECT id FROM pipeline_executions WHERE pipeline_id = ? ORDER BY started_at DESC LIMIT ?)',
        id,
        id,
        maxPerPipeline,
      );
    }
    return removed;
  }

  private get<T>(sql: string, ...params: unknown[]): T | null {
    const result = this.db.prepare(sql).get(...(params as never[]));
    return (result as T | undefined) ?? null;
  }

  private all<T>(sql: string, ...params: unknown[]): T[] {
    return this.db.prepare(sql).all(...(params as never[])) as unknown as T[];
  }

  private run(sql: string, ...params: unknown[]): number {
    return Number(this.db.prepare(sql).run(...(params as never[])).changes);
  }
}