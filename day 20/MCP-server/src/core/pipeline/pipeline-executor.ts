import { randomUUID } from 'node:crypto';
import type { Logger } from '../logging/logger.js';
import { userError } from '../errors.js';
import { redactText } from '../util/redact.js';
import type { Pipeline, PipelineExecution, PipelineRunResult, PipelineStepResult } from './types.js';
import type { PipelineStorage } from './pipeline-storage.js';
import type { PipelineRegistry } from './pipeline-registry.js';
import type { PipelineValidator } from './pipeline-validator.js';
import { TemplateResolver } from './template-resolver.js';

export type PipelineToolRunner = (tool: string, args: unknown) => Promise<unknown>;

export interface PipelineExecutorOptions {
  storage: PipelineStorage;
  registry: PipelineRegistry;
  validator: PipelineValidator;
  logger: Logger;
  /** Диспетчер вызова tools (провайдерские + core tools), общий с MCP. */
  callTool: PipelineToolRunner;
  now?: () => number;
}

const MAX_ERROR = 2000;

/**
 * PipelineExecutor: выполняет шаги пайплайна по порядку, разрешает шаблоны,
 * передаёт output предыдущего шага следующему, пишет историю выполнений.
 * Output'ы шагов НЕ сохраняются (безопасность: не копим сырые данные и секреты).
 */
export class PipelineExecutor {
  private readonly storage: PipelineStorage;
  private readonly registry: PipelineRegistry;
  private readonly validator: PipelineValidator;
  private readonly logger: Logger;
  private readonly callTool: PipelineToolRunner;
  private readonly now: () => number;
  private readonly resolver = new TemplateResolver();
  private readonly running = new Set<string>();

  constructor(opts: PipelineExecutorOptions) {
    this.storage = opts.storage;
    this.registry = opts.registry;
    this.validator = opts.validator;
    this.logger = opts.logger;
    this.callTool = opts.callTool;
    this.now = opts.now ?? (() => Date.now());
  }

  async run(pipelineId: string, input: Record<string, unknown> = {}): Promise<PipelineRunResult> {
    const pipeline = this.registry.getEntity(pipelineId); // бросает PIPELINE_NOT_FOUND
    this.validator.validate(pipeline);

    if (this.running.has(pipelineId)) {
      throw userError(`Pipeline "${pipelineId}" is already running`, 'PIPELINE_RUNNING');
    }
    this.running.add(pipelineId);
    try {
      return await this.execute(pipeline, input);
    } finally {
      this.running.delete(pipelineId);
    }
  }

  private async execute(pipeline: Pipeline, input: Record<string, unknown>): Promise<PipelineRunResult> {
    const startedAt = new Date(this.now()).toISOString();
    const startedMs = this.now();
    const execution: PipelineExecution = {
      id: `${Date.now().toString(36)}-${randomUUID().slice(0, 8)}`,
      pipelineId: pipeline.id,
      startedAt,
      status: 'running',
      steps: [],
    };
    this.storage.insertExecution(execution);
    this.logger.info(`[Pipeline] ${pipeline.id} started (${pipeline.steps.length} steps)`);

    const outputs: Record<string, unknown> = {};
    const steps: PipelineStepResult[] = [];

    try {
      for (const step of pipeline.steps) {
        let args: unknown;
        try {
          args = this.resolver.resolve(step.input ?? {}, { input: input as Record<string, unknown>, steps: outputs });
        } catch (err) {
          this.markFailed(execution, steps, step, pipeline, err);
          break;
        }
        try {
          const result = await this.callTool(step.tool, args);
          // В контексте шаблонов output шага лежит под steps.<id>.output
          outputs[step.id] = { output: result };
          steps.push({ id: step.id, tool: step.tool, status: 'completed' });
        } catch (err) {
          this.markFailed(execution, steps, step, pipeline, err);
          break;
        }
      }
      if (execution.status !== 'failed') {
        execution.status = 'completed';
        this.registry.updateLastRunAt(pipeline.id);
      }
    } finally {
      execution.finishedAt = new Date(this.now()).toISOString();
      execution.durationMs = this.now() - startedMs;
      execution.steps = steps;
      this.storage.finishExecution(execution);
      this.logger.info(`[Pipeline] ${pipeline.id} ${execution.status} duration=${execution.durationMs}ms`);
    }
    return this.toRunResult(execution);
  }

  private markFailed(
    execution: PipelineExecution,
    steps: PipelineStepResult[],
    step: Pipeline['steps'][number],
    pipeline: Pipeline,
    err: unknown,
  ): void {
    const message = redactText(err instanceof Error ? err.message : String(err)).slice(0, MAX_ERROR);
    steps.push({ id: step.id, tool: step.tool, status: 'failed', error: message });
    execution.status = 'failed';
    execution.failedStep = step.id;
    execution.error = message;
    for (const rest of pipeline.steps.slice(steps.length)) {
      steps.push({ id: rest.id, tool: rest.tool, status: 'skipped' });
    }
  }

  private toRunResult(execution: PipelineExecution): PipelineRunResult {
    return {
      executionId: execution.id,
      pipelineId: execution.pipelineId,
      status: execution.status,
      steps: execution.steps,
      durationMs: execution.durationMs,
      error: execution.error,
    };
  }
}