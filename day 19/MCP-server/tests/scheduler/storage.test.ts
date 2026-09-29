import { describe, expect, it } from 'vitest';
import { mkdtempSync, rmSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { TaskStorage, taskToRow, rowToTask } from '../../src/core/scheduler/task-storage.js';
import type { ScheduledTask, TaskExecution } from '../../src/core/scheduler/task-types.js';

function makeTask(overrides: Partial<ScheduledTask> = {}): ScheduledTask {
  const base: ScheduledTask = {
    id: 'test-task',
    name: 'Test Task',
    enabled: true,
    schedule: { type: 'cron', cron: '0 * * * *', timezone: 'UTC' },
    action: { type: 'provider_tool', provider: 'weather', tool: 'weather_current', input: {} },
    aggregation: { enabled: true, strategy: 'auto' },
    createdAt: '2026-09-27T10:00:00.000Z',
    updatedAt: '2026-09-27T10:00:00.000Z',
    nextRunAt: '2026-09-27T11:00:00.000Z',
    status: 'active',
    running: false,
    version: 1,
    ...overrides,
  };
  return base;
}

function makeDb(): { db: TaskStorage; cleanup: () => void } {
  const dir = mkdtempSync(path.join(os.tmpdir(), 'mcp-gw-sched-'));
  const db = new TaskStorage(path.join(dir, 'test.db'));
  return { db, cleanup: () => { db.close(); rmSync(dir, { recursive: true, force: true }); } };
}

describe('TaskStorage', () => {
  it('persists tasks across reopen (server restart)', () => {
    const { db, cleanup } = makeDb();
    db.insertTask(makeTask());
    db.close();

    const reopened = new TaskStorage(path.join(path.dirname(db.dbPath), 'test.db'));
    const rows = reopened.listTasks();
    expect(rows).toHaveLength(1);
    const task = rowToTask(rows[0]);
    expect(task.id).toBe('test-task');
    expect(task.name).toBe('Test Task');
    expect(task.schedule.cron).toBe('0 * * * *');
    expect(task.schedule.timezone).toBe('UTC');
    expect(task.nextRunAt).toBe('2026-09-27T11:00:00.000Z');
    reopened.close();
    cleanup();
  });

  it('round-trips once tasks with executeAt', () => {
    const { db, cleanup } = makeDb();
    db.insertTask(makeTask({ id: 'once-task', schedule: { type: 'once', executeAt: '2026-09-28T10:00:00Z', timezone: 'Europe/Berlin' } }));
    const row = db.getTask('once-task')!;
    expect(row.schedule_type).toBe('once');
    expect(row.execute_at).toBe('2026-09-28T10:00:00Z');
    const task = rowToTask(row);
    expect(task.schedule.type).toBe('once');
    expect(task.schedule.executeAt).toBe('2026-09-28T10:00:00Z');
    cleanup();
  });

  it('claimRunning is atomic and prevents double execution', () => {
    const { db, cleanup } = makeDb();
    db.insertTask(makeTask());
    const row = db.getTask('test-task')!;
    expect(db.claimRunning('test-task')).toBe(true);
    expect(db.claimRunning('test-task')).toBe(false);
    expect(rowToTask(db.getTask('test-task')!).running).toBe(true);
    db.releaseRunning('test-task');
    expect(db.claimRunning('test-task')).toBe(true);
    cleanup();
  });

  it('stores history with pagination and counts', () => {
    const { db, cleanup } = makeDb();
    db.insertTask(makeTask());
    for (let i = 0; i < 5; i++) {
      const exec: TaskExecution = {
        id: `e${i}`,
        taskId: 'test-task',
        startedAt: `2026-09-27T10:0${i}:00.000Z`,
        status: i === 3 ? 'error' : 'success',
        durationMs: 100 + i,
        result: { n: i },
        error: i === 3 ? 'boom' : undefined,
      };
      db.insertExecution(exec);
      db.finishExecution(exec);
    }
    const page = db.listExecutions('test-task', 0, 2);
    expect(page.total).toBe(5);
    expect(page.rows).toHaveLength(2);
    expect(page.rows[0].started_at).toBe('2026-09-27T10:04:00.000Z'); // DESC

    const counts = db.countExecutions('test-task');
    expect(counts.total).toBe(5);
    expect(counts.success).toBe(4);
    expect(counts.error).toBe(1);
    cleanup();
  });

  it('prunes executions by max per task and retention days', () => {
    const { db, cleanup } = makeDb();
    db.insertTask(makeTask());
    for (let i = 0; i < 10; i++) {
      db.insertExecution({
        id: `old${i}`,
        taskId: 'test-task',
        startedAt: `2026-09-26T10:0${i}:00.000Z`,
        status: 'success',
      });
    }
    for (let i = 0; i < 5; i++) {
      db.insertExecution({
        id: `new${i}`,
        taskId: 'test-task',
        startedAt: `2026-09-27T11:0${i}:00.000Z`,
        status: 'success',
      });
    }
    const removed = db.pruneExecutions(4, 0); // оставить 4 самых свежих
    expect(removed).toBe(11);
    const after = db.listExecutions('test-task', 0, 100);
    expect(after.total).toBe(4);
    expect(after.rows.every((r) => r.id.startsWith('new'))).toBe(true);
    cleanup();
  });

  it('deletes task and its executions', () => {
    const { db, cleanup } = makeDb();
    db.insertTask(makeTask());
    db.insertExecution({ id: 'e1', taskId: 'test-task', startedAt: '2026-09-27T10:00:00.000Z', status: 'success' });
    expect(db.deleteExecutionsForTask('test-task')).toBe(1);
    expect(db.deleteTask('test-task')).toBe(true);
    expect(db.getTask('test-task')).toBeNull();
    expect(db.listExecutions('test-task', 0, 10).total).toBe(0);
    cleanup();
  });
});