import { mkdirSync } from 'node:fs';
import path from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import { configError } from '../errors.js';
import type {
  ExecutionStatus,
  ScheduledTask,
  TaskExecution,
  TaskStatus,
} from './task-types.js';
import { safeStringify } from '../util/redact.js';

/** Строка таблицы tasks (как хранится в SQLite). */
export interface TaskRow {
  id: string;
  name: string;
  description: string | null;
  enabled: number;
  schedule_type: 'once' | 'cron';
  execute_at: string | null;
  cron: string | null;
  timezone: string | null;
  provider: string;
  tool: string;
  input_json: string;
  aggregation_json: string;
  created_at: string;
  updated_at: string;
  last_run_at: string | null;
  next_run_at: string | null;
  status: string;
  running: number;
  version: number;
  action_type: 'provider_tool' | 'pipeline';
  pipeline_id: string | null;
}

/** Строка таблицы executions. */
export interface ExecutionRow {
  id: string;
  task_id: string;
  started_at: string;
  finished_at: string | null;
  status: ExecutionStatus;
  duration_ms: number | null;
  result_json: string | null;
  error_text: string | null;
}

export interface HistoryPageRows {
  rows: ExecutionRow[];
  total: number;
}

const TASK_COLUMNS =
  'id,name,description,enabled,schedule_type,execute_at,cron,timezone,provider,tool,input_json,aggregation_json,created_at,updated_at,last_run_at,next_run_at,status,running,version,action_type,pipeline_id';

export function taskToRow(task: ScheduledTask): TaskRow {
  return {
    id: task.id,
    name: task.name,
    description: task.description ?? null,
    enabled: task.enabled ? 1 : 0,
    schedule_type: task.schedule.type,
    execute_at: task.schedule.executeAt ?? null,
    cron: task.schedule.cron ?? null,
    timezone: task.schedule.timezone ?? null,
    provider: task.action.provider ?? '',
    tool: task.action.tool ?? '',
    input_json: safeStringify(task.action.input ?? {}),
    aggregation_json: safeStringify(task.aggregation ?? {}),
    created_at: task.createdAt,
    updated_at: task.updatedAt,
    last_run_at: task.lastRunAt ?? null,
    next_run_at: task.nextRunAt ?? null,
    status: task.status,
    running: task.running ? 1 : 0,
    version: task.version,
    action_type: task.action.type,
    pipeline_id: task.action.pipeline ?? null,
  };
}

export function rowToTask(row: TaskRow): ScheduledTask {
  return {
    id: row.id,
    name: row.name,
    description: row.description ?? undefined,
    enabled: row.enabled === 1,
    schedule: {
      type: row.schedule_type,
      executeAt: row.execute_at ?? undefined,
      cron: row.cron ?? undefined,
      timezone: row.timezone ?? undefined,
    },
    action: {
      type: row.action_type === 'pipeline' ? 'pipeline' : 'provider_tool',
      provider: row.provider || undefined,
      tool: row.tool || undefined,
      pipeline: row.pipeline_id || undefined,
      input: parseJsonSafe(row.input_json, {}),
    },
    aggregation: parseJsonSafe<Record<string, unknown>>(row.aggregation_json, {}),
    createdAt: row.created_at,
    updatedAt: row.updated_at,
    lastRunAt: row.last_run_at ?? undefined,
    nextRunAt: row.next_run_at ?? undefined,
    status: row.status as TaskStatus,
    running: row.running === 1,
    version: row.version,
  };
}

export function rowToExecution(row: ExecutionRow): TaskExecution {
  return {
    id: row.id,
    taskId: row.task_id,
    startedAt: row.started_at,
    finishedAt: row.finished_at ?? undefined,
    status: row.status,
    durationMs: row.duration_ms ?? undefined,
    result: row.result_json === null ? undefined : parseJsonSafe(row.result_json, undefined),
    error: row.error_text ?? undefined,
  };
}

function parseJsonSafe<T>(json: string, fallback: T): T {
  try {
    return JSON.parse(json) as T;
  } catch {
    return fallback;
  }
}

/**
 * SQLite-хранилище задач и истории выполнений (data/scheduler.db).
 * Использует встроенный node:sqlite — без нативных зависимостей.
 * Защита от двойного выполнения: атомарный claim через UPDATE ... WHERE running=0.
 */
export class TaskStorage {
  readonly dbPath: string;
  private readonly db: DatabaseSync;

  constructor(dbPath: string) {
    this.dbPath = path.resolve(dbPath);
    mkdirSync(path.dirname(this.dbPath), { recursive: true });
    try {
      this.db = new DatabaseSync(this.dbPath);
    } catch (err) {
      throw configError(
        `Cannot open scheduler database at ${this.dbPath}: ${err instanceof Error ? err.message : String(err)}`,
        'SCHEDULER_DB_OPEN_FAILED',
        err,
      );
    }
    this.db.exec('PRAGMA journal_mode = WAL;');
    this.db.exec(`CREATE TABLE IF NOT EXISTS tasks (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      description TEXT,
      enabled INTEGER NOT NULL DEFAULT 1,
      schedule_type TEXT NOT NULL,
      execute_at TEXT,
      cron TEXT,
      timezone TEXT NOT NULL DEFAULT 'UTC',
      provider TEXT NOT NULL,
      tool TEXT NOT NULL,
      input_json TEXT NOT NULL DEFAULT '{}',
      aggregation_json TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      last_run_at TEXT,
      next_run_at TEXT,
      status TEXT NOT NULL DEFAULT 'active',
      running INTEGER NOT NULL DEFAULT 0,
      version INTEGER NOT NULL DEFAULT 1
    )`);
    this.db.exec(`CREATE TABLE IF NOT EXISTS executions (
      id TEXT PRIMARY KEY,
      task_id TEXT NOT NULL,
      started_at TEXT NOT NULL,
      finished_at TEXT,
      status TEXT NOT NULL,
      duration_ms INTEGER,
      result_json TEXT,
      error_text TEXT
    )`);
    this.db.exec('CREATE INDEX IF NOT EXISTS idx_tasks_next ON tasks(next_run_at)');
    this.db.exec('CREATE INDEX IF NOT EXISTS idx_exec_task ON executions(task_id, started_at DESC)');
    this.migrateTaskColumns();
  }

  /** Лёгкая миграция для задач нового типа (pipeline). */
  private migrateTaskColumns(): void {
    const cols = this.db.prepare('PRAGMA table_info(tasks)').all() as unknown as Array<{ name: string }>;
    if (!cols.some((c) => c.name === 'action_type')) {
      this.db.exec("ALTER TABLE tasks ADD COLUMN action_type TEXT NOT NULL DEFAULT 'provider_tool'");
    }
    if (!cols.some((c) => c.name === 'pipeline_id')) {
      this.db.exec('ALTER TABLE tasks ADD COLUMN pipeline_id TEXT');
    }
  }

  close(): void {
    try {
      this.db.close();
    } catch {
      /* уже закрыт */
    }
  }

  /** Выполнить statement без возврата (DDL/PRAGMA). */
  exec(sql: string): void {
    this.db.exec(sql);
  }

  // ---------------------------------------------------------------- tasks

  listTasks(): TaskRow[] {
    return this.all<TaskRow>(`SELECT ${TASK_COLUMNS} FROM tasks ORDER BY created_at ASC`);
  }

  getTask(id: string): TaskRow | null {
    return this.get<TaskRow>(`SELECT ${TASK_COLUMNS} FROM tasks WHERE id = ?`, id);
  }

  insertTask(task: ScheduledTask): void {
    const row = taskToRow(task);
    const values = TASK_COLUMNS.split(',').map((c) => (row as unknown as Record<string, unknown>)[c]);
    this.run(
      `INSERT INTO tasks (${TASK_COLUMNS}) VALUES (${TASK_COLUMNS.split(',').map(() => '?').join(', ')})`,
      ...values,
    );
  }

  updateTask(task: ScheduledTask): void {
    const row = taskToRow(task);
    const cols = TASK_COLUMNS.split(',').filter((c) => c !== 'id');
    const set = cols.map((c) => `${c} = ?`).join(', ');
    const values = cols.map((c) => (row as unknown as Record<string, unknown>)[c]);
    this.run(`UPDATE tasks SET ${set} WHERE id = ?`, ...values, task.id);
  }

  deleteTask(id: string): boolean {
    return this.run('DELETE FROM tasks WHERE id = ?', id) > 0;
  }

  /** Атомарный захват задачи для выполнения (защита от concurrent execution). */
  claimRunning(id: string): boolean {
    return this.run('UPDATE tasks SET running = 1, version = version + 1 WHERE id = ? AND running = 0', id) === 1;
  }

  releaseRunning(id: string): void {
    this.run('UPDATE tasks SET running = 0, version = version + 1 WHERE id = ?', id);
  }

  /** После старта сервера сбрасываем «зависшие» флаги running (процесс упал). */
  resetRunningFlags(): void {
    this.run('UPDATE tasks SET running = 0');
  }

  /** Обновить состояние после выполнения. */
  updateTaskRunState(id: string, patch: { lastRunAt: string; nextRunAt: string | null; status: TaskStatus }): void {
    this.run(
      'UPDATE tasks SET last_run_at = ?, next_run_at = ?, status = ?, updated_at = ?, running = 0 WHERE id = ?',
      patch.lastRunAt,
      patch.nextRunAt,
      patch.status,
      new Date().toISOString(),
      id,
    );
  }

  updateNextRunAt(id: string, nextRunAt: string | null): void {
    this.run('UPDATE tasks SET next_run_at = ?, updated_at = ? WHERE id = ?', nextRunAt, new Date().toISOString(), id);
  }

  setTaskPaused(id: string, enabled: boolean): void {
    this.run(
      'UPDATE tasks SET enabled = ?, status = ?, next_run_at = NULL, updated_at = ? WHERE id = ?',
      enabled ? 1 : 0,
      enabled ? 'active' : 'paused',
      new Date().toISOString(),
      id,
    );
  }

  /** Подходящие к запуску задачи (сортировка: самые срочные первыми). */
  findDueTasks(nowIso: string): TaskRow[] {
    return this.all<TaskRow>(
      `SELECT ${TASK_COLUMNS} FROM tasks
       WHERE enabled = 1 AND status = 'active' AND running = 0
         AND next_run_at IS NOT NULL AND next_run_at <= ?
       ORDER BY next_run_at ASC`,
      nowIso,
    );
  }

  /** Ближайшая будущая задача (для постановки таймера). */
  findNextPending(): TaskRow | null {
    return this.get<TaskRow>(
      `SELECT ${TASK_COLUMNS} FROM tasks
       WHERE enabled = 1 AND status = 'active' AND running = 0 AND next_run_at IS NOT NULL
       ORDER BY next_run_at ASC LIMIT 1`,
    );
  }

  // ------------------------------------------------------------ executions

  insertExecution(exec: TaskExecution): void {
    this.run(
      'INSERT INTO executions (id, task_id, started_at, finished_at, status, duration_ms, result_json, error_text) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
      exec.id,
      exec.taskId,
      exec.startedAt,
      exec.finishedAt ?? null,
      exec.status,
      exec.durationMs ?? null,
      exec.result === undefined ? null : safeStringify(exec.result),
      exec.error ?? null,
    );
  }

  finishExecution(exec: TaskExecution): void {
    this.run(
      'UPDATE executions SET finished_at = ?, status = ?, duration_ms = ?, result_json = ?, error_text = ? WHERE id = ?',
      exec.finishedAt ?? null,
      exec.status,
      exec.durationMs ?? null,
      exec.result === undefined ? null : safeStringify(exec.result),
      exec.error ?? null,
      exec.id,
    );
  }

  getExecution(id: string): ExecutionRow | null {
    return this.get<ExecutionRow>('SELECT * FROM executions WHERE id = ?', id);
  }

  listExecutions(taskId: string, offset: number, limit: number): HistoryPageRows {
    const total = this.get<{ c: number }>('SELECT COUNT(*) AS c FROM executions WHERE task_id = ?', taskId)?.c ?? 0;
    const rows = this.all<ExecutionRow>(
      'SELECT * FROM executions WHERE task_id = ? ORDER BY started_at DESC LIMIT ? OFFSET ?',
      taskId,
      Math.max(0, limit),
      Math.max(0, offset),
    );
    return { rows, total };
  }

  countExecutions(taskId: string): { total: number; success: number; error: number } {
    const row = this.get<{ total: number; success: number | null; error: number | null }>(
      "SELECT COUNT(*) AS total, SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS success, SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS error FROM executions WHERE task_id = ?",
      taskId,
    ) ?? { total: 0, success: 0, error: 0 };
    return { total: row.total, success: row.success ?? 0, error: row.error ?? 0 };
  }

  /** Выполнения задачи в окне (по started_at), по возрастанию. */
  executionsBetween(taskId: string, fromIso: string | null, toIso: string | null): TaskExecution[] {
    let sql = "SELECT * FROM executions WHERE task_id = ? AND status != 'running'";
    const params: unknown[] = [taskId];
    if (fromIso) {
      sql += ' AND started_at >= ?';
      params.push(fromIso);
    }
    if (toIso) {
      sql += ' AND started_at <= ?';
      params.push(toIso);
    }
    sql += ' ORDER BY started_at ASC';
    const rows = this.all<ExecutionRow>(sql, ...params);
    return rows.map(rowToExecution);
  }

  /** Retention: удалить старые и «лишние» выполнения (по количеству на задачу). */
  pruneExecutions(maxPerTask: number | null, retentionDays: number): number {
    let removed = 0;
    if (retentionDays > 0) {
      const cutoff = new Date(Date.now() - retentionDays * 24 * 60 * 60 * 1000).toISOString();
      removed += this.run('DELETE FROM executions WHERE started_at < ?', cutoff);
    }
    if (maxPerTask && maxPerTask > 0) {
      const tasks = this.all<{ task_id: string }>('SELECT DISTINCT task_id FROM executions');
      for (const { task_id } of tasks) {
        removed += this.run(
          'DELETE FROM executions WHERE task_id = ? AND id NOT IN (SELECT id FROM executions WHERE task_id = ? ORDER BY started_at DESC LIMIT ?)',
          task_id,
          task_id,
          maxPerTask,
        );
      }
    }
    return removed;
  }

  deleteExecutionsForTask(taskId: string): number {
    return this.run('DELETE FROM executions WHERE task_id = ?', taskId);
  }

  // ---------------------------------------------------------------- helpers

  private get<T>(sql: string, ...params: unknown[]): T | null {
    const result = this.db.prepare(sql).get(...(params as never[]));
    return (result as T | undefined) ?? null;
  }

  private all<T>(sql: string, ...params: unknown[]): T[] {
    return this.db.prepare(sql).all(...(params as never[])) as unknown as T[];
  }

  private run(sql: string, ...params: unknown[]): number {
    const result = this.db.prepare(sql).run(...(params as never[]));
    return Number(result.changes);
  }
}