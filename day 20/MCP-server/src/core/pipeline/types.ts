/** Модель Pipeline: композиция MCP tools. */

export interface PipelineStepInput {
  id: string;
  tool: string;
  input: unknown; // может содержать шаблоны {{input.x}} / {{steps.<id>.output}}
}

export interface Pipeline {
  id: string;
  name: string;
  description?: string;
  enabled: boolean;
  steps: PipelineStepInput[];
  createdAt: string;
  updatedAt: string;
  lastRunAt?: string;
}

export interface PipelineStepResult {
  id: string;
  tool: string;
  status: 'completed' | 'failed' | 'skipped';
  error?: string;
}

export interface PipelineExecution {
  id: string;
  pipelineId: string;
  startedAt: string;
  finishedAt?: string;
  status: 'running' | 'completed' | 'failed';
  steps: PipelineStepResult[];
  durationMs?: number;
  failedStep?: string;
  error?: string;
}

export interface PipelineRunResult {
  executionId: string;
  pipelineId: string;
  status: PipelineExecution['status'];
  steps: PipelineStepResult[];
  durationMs?: number;
  error?: string;
}

export interface PipelineInput {
  id?: string;
  name: string;
  description?: string;
  enabled?: boolean;
  steps: PipelineStepInput[];
}