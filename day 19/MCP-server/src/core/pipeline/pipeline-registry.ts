import { randomUUID } from 'node:crypto';
import { userError } from '../errors.js';
import type { Pipeline, PipelineExecution, PipelineInput, PipelineStepInput } from './types.js';
import type { PipelineStorage } from './pipeline-storage.js';
import { rowToExecution, rowToPipeline } from './pipeline-storage.js';

const ID_SLUG_RE = /^[a-zA-Z0-9_-]{1,64}$/;

/** Статическая проверка формы PipelineInput (без проверки tools — её делает Validator). */
export function validatePipelineInput(input: PipelineInput, now: () => number = Date.now): Pipeline {
  const name = typeof input.name === 'string' && input.name.trim() ? input.name.trim() : null;
  if (!name) throw userError('Pipeline name is required', 'PIPELINE_NAME_REQUIRED');
  if (!Array.isArray(input.steps) || input.steps.length === 0) {
    throw userError('Pipeline must have at least one step', 'PIPELINE_NO_STEPS');
  }
  for (const step of input.steps) {
    if (!step || typeof step.id !== 'string' || step.id.trim() === '') {
      throw userError('Every pipeline step must have an id string', 'PIPELINE_STEP_NO_ID');
    }
    if (typeof step.tool !== 'string' || step.tool.trim() === '') {
      throw userError(`Step "${step.id}" must have a tool name`, 'PIPELINE_STEP_NO_TOOL');
    }
  }
  const steps: PipelineStepInput[] = input.steps.map((s) => ({
    id: s.id.trim(),
    tool: s.tool.trim(),
    input: s.input ?? {},
  }));
  const nowIso = new Date(now()).toISOString();
  return {
    id: input.id!,
    name,
    description: input.description?.trim() || undefined,
    enabled: input.enabled ?? true,
    steps,
    createdAt: nowIso,
    updatedAt: nowIso,
  };
}

function slugify(name: string): string {
  return (
    name
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, 48) || 'pipeline'
  );
}

/**
 * PipelineRegistry: CRUD + история + демо-пайплайны.
 * Валидация ссылок/tools выполняется PipelineValidator при запуске.
 */
export class PipelineRegistry {
  constructor(
    private readonly storage: PipelineStorage,
    private readonly now: () => number = Date.now,
  ) {}

  list(): Pipeline[] {
    return this.storage.listPipelines().map(rowToPipeline);
  }

  get(id: string): Pipeline | null {
    const row = this.storage.getPipeline(id);
    return row ? rowToPipeline(row) : null;
  }

  getEntity(id: string): Pipeline {
    const pipeline = this.get(id);
    if (!pipeline) throw this.notFound(id);
    return pipeline;
  }

  async create(input: PipelineInput): Promise<Pipeline> {
    let id = input.id;
    if (!id) {
      id = slugify(input.name);
      if (this.get(id)) id = `${id}-${randomUUID().slice(0, 6)}`;
    } else if (!ID_SLUG_RE.test(id)) {
      throw userError('Pipeline id must match [a-zA-Z0-9_-]{1,64}', 'INVALID_PIPELINE_ID');
    } else if (this.get(id)) {
      throw userError(`Pipeline id "${id}" already exists`, 'PIPELINE_ID_EXISTS');
    }
    const pipeline = validatePipelineInput({ ...input, id });
    this.storage.insertPipeline(pipeline);
    return pipeline;
  }

  async update(id: string, patch: Partial<PipelineInput>): Promise<Pipeline> {
    const current = this.getEntity(id);
    const merged: PipelineInput = {
      name: patch.name?.trim() || current.name,
      description: patch.description !== undefined ? patch.description?.trim() || undefined : current.description,
      enabled: patch.enabled ?? current.enabled,
      steps: patch.steps ?? current.steps,
    };
    const next = validatePipelineInput(merged, this.now);
    next.id = id;
    next.createdAt = current.createdAt;
    next.lastRunAt = current.lastRunAt;
    next.updatedAt = new Date(this.now()).toISOString();
    this.storage.updatePipeline(next);
    return next;
  }

  async delete(id: string): Promise<{ deleted: boolean }> {
    this.getEntity(id);
    return { deleted: this.storage.deletePipeline(id) };
  }

  updateLastRunAt(id: string): void {
    const pipeline = this.get(id);
    if (!pipeline) return;
    pipeline.lastRunAt = new Date(this.now()).toISOString();
    pipeline.updatedAt = pipeline.lastRunAt;
    this.storage.updatePipeline(pipeline);
  }

  listExecutions(id: string, offset: number, limit: number): { items: PipelineExecution[]; total: number; offset: number; limit: number } {
    this.getEntity(id);
    const page = this.storage.listExecutions(id, offset, limit);
    return { items: page.rows.map(rowToExecution), total: page.total, offset, limit };
  }

  getExecution(executionId: string): PipelineExecution {
    const row = this.storage.getExecution(executionId);
    if (!row) throw userError(`Pipeline execution "${executionId}" not found`, 'EXECUTION_NOT_FOUND');
    return rowToExecution(row);
  }

  /** Демо-пайплайны (идемпотентно). Возвращает созданные id. */
  async seedDemo(): Promise<string[]> {
    const created: string[] = [];
    const demos: PipelineInput[] = [
      {
        id: 'github-summary',
        name: 'GitHub Issues Summary',
        description: 'github_list_issues → summarize → saveToFile. Требует настроенный LLM.',
        steps: [
          { id: 'getIssues', tool: 'github_list_issues', input: { owner: '{{input.owner}}', repo: '{{input.repo}}', state: 'open', limit: 30 } },
          { id: 'summary', tool: 'summarize', input: { data: '{{steps.getIssues.output}}' } },
          { id: 'save', tool: 'saveToFile', input: { filename: '{{input.repo}}-summary.txt', content: '{{steps.summary.output.summary}}' } },
        ],
      },
      {
        id: 'weather-snapshot',
        name: 'Weather Snapshot',
        description: 'weather_current → saveToFile. Работает без LLM.',
        steps: [
          { id: 'getWeather', tool: 'weather_current', input: { latitude: '{{input.latitude}}', longitude: '{{input.longitude}}' } },
          { id: 'save', tool: 'saveToFile', input: { filename: 'weather-{{input.latitude}}-{{input.longitude}}.txt', content: '{{steps.getWeather.output}}' } },
        ],
      },
    ];
    for (const demo of demos) {
      if (this.get(demo.id as string)) continue;
      await this.create({ ...demo, id: demo.id });
      created.push(demo.id as string);
    }
    return created;
  }

  private notFound(id: string): ReturnType<typeof userError> {
    return userError(`Pipeline "${id}" not found`, 'PIPELINE_NOT_FOUND');
  }
}