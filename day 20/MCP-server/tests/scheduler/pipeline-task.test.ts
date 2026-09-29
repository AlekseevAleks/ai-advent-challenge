import { describe, expect, it, afterEach } from 'vitest';
import { mkdtempSync, rmSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { Logger } from '../../src/core/logging/logger.js';
import { PipelineStorage } from '../../src/core/pipeline/pipeline-storage.js';
import { PipelineRegistry } from '../../src/core/pipeline/pipeline-registry.js';
import { PipelineValidator } from '../../src/core/pipeline/pipeline-validator.js';
import { PipelineExecutor } from '../../src/core/pipeline/pipeline-executor.js';
import { TaskExecutor } from '../../src/core/scheduler/task-executor.js';
import { rowToTask } from '../../src/core/scheduler/task-storage.js';
import { createSchedulerHarness, weatherOk, type SchedulerHarness } from './helpers.js';

let h: SchedulerHarness | undefined;
let cleanupDirs: string[] = [];

afterEach(() => {
  h?.cleanup();
  h = undefined;
  for (const d of cleanupDirs) rmSync(d, { recursive: true, force: true });
  cleanupDirs = [];
});

describe('Scheduler + Pipeline (action type = pipeline)', () => {
  it('TaskExecutor runs a pipeline action and records pipeline history', async () => {
    const dbDir = mkdtempSync(path.join(os.tmpdir(), 'mcp-gw-ppl-task-'));
    cleanupDirs.push(dbDir);
    h = await createSchedulerHarness({
      providerConfigs: { weather: { id: 'weather', enabled: true } },
      onFetch: weatherOk,
      dbPath: path.join(dbDir, 'scheduler.db'),
    });
    await h.harness.registry.loadProviders();
    await h.harness.registry.initializeAll();

    const pipelineStorage = new PipelineStorage(path.join(dbDir, 'pipelines.db'));
    const pipelineRegistry = new PipelineRegistry(pipelineStorage);
    await pipelineRegistry.create({
      id: 'pipe-a',
      name: 'Pipe A',
      steps: [
        { id: 's1', tool: 'weather_current', input: { latitude: 52.52, longitude: 13.405 } },
        { id: 's2', tool: 'weather_forecast', input: { latitude: '{{input.lat}}', longitude: '{{input.lon}}', days: 2 } },
      ],
    } as never);
    const validator = new PipelineValidator({
      isToolKnown: (name) => h!.harness.registry.isToolEnabled(name),
      isToolEnabled: (name) => h!.harness.registry.isToolEnabled(name),
    });
    const executor = new PipelineExecutor({
      storage: pipelineStorage,
      registry: pipelineRegistry,
      validator,
      logger: new Logger({ level: 'silent' }),
      callTool: (tool, args) => h!.harness.registry.executeTool(tool, args),
      now: () => h!.clock.value,
    });

    const taskExecutor = new TaskExecutor({
      registry: h.harness.registry,
      storage: h.storage,
      logger: new Logger({ level: 'silent' }),
      getSettings: () => h!.settings,
      pipelineExecutor: executor,
      now: () => h!.clock.value,
    });

    h.storage.insertTask({
      id: 'pipeline-task',
      name: 'Run pipeline by schedule',
      enabled: true,
      schedule: { type: 'once', executeAt: new Date(h.clock.value + 60_000).toISOString(), timezone: 'UTC' },
      action: { type: 'pipeline', pipeline: 'pipe-a', input: { lat: 52.52, lon: 13.405 } },
      aggregation: {},
      createdAt: new Date(h.clock.value).toISOString(),
      updatedAt: new Date(h.clock.value).toISOString(),
      nextRunAt: new Date(h.clock.value + 60_000).toISOString(),
      status: 'active',
      running: false,
      version: 1,
    });

    const execution = await taskExecutor.execute(rowToTask(h.storage.getTask('pipeline-task')!));
    expect(execution.status).toBe('success');
    const history = await pipelineRegistry.listExecutions('pipe-a', 0, 10);
    expect(history.total).toBe(1);
    expect(history.items[0].status).toBe('completed');
    const row = h.storage.getTask('pipeline-task')!;
    expect(row.last_run_at).toBeTruthy();
  });

  it('TaskManager rejects pipeline actions when pipelines are unavailable', async () => {
    const dbDir = mkdtempSync(path.join(os.tmpdir(), 'mcp-gw-ppl-task2-'));
    cleanupDirs.push(dbDir);
    h = await createSchedulerHarness({ onFetch: weatherOk, dbPath: path.join(dbDir, 'scheduler.db') });
    let err: { code?: string } | undefined;
    try {
      await h.manager.create({
        name: 'x',
        schedule: { type: 'cron', cron: '0 * * * *', timezone: 'UTC' },
        action: { type: 'pipeline', pipeline: 'nope', input: {} },
      } as never);
    } catch (e) {
      err = e as { code?: string };
    }
    expect(err?.code).toBe('PIPELINES_UNAVAILABLE');
  });
});