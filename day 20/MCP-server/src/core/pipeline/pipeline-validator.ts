import { userError } from '../errors.js';
import { TEMPLATE_REF_RE } from './template-refs.js';
import type { Pipeline } from './types.js';

export interface PipelineToolPolicy {
  isToolKnown: (name: string) => boolean;
  isToolEnabled?: (name: string) => boolean;
}

/**
 * PipelineValidator: статическая проверка перед запуском:
 *  - pipeline существует и не пуст;
 *  - step id уникальны;
 *  - tools известны (и включены, если применимо);
 *  - ссылки в шаблонах указывают на существующие РАННИЕ шаги или на input.*.
 */
export class PipelineValidator {
  constructor(private readonly policy: PipelineToolPolicy) {}

  validate(pipeline: Pipeline | null | undefined): void {
    if (!pipeline) throw userError('Pipeline not found', 'PIPELINE_NOT_FOUND');
    if (pipeline.steps.length === 0) throw userError(`Pipeline "${pipeline.id}" has no steps`, 'PIPELINE_NO_STEPS');

    const ids = pipeline.steps.map((s) => s.id);
    for (const id of ids) {
      if (!id || id.trim() === '') throw userError('Every pipeline step must have an id', 'PIPELINE_STEP_NO_ID');
    }
    const unique = new Set(ids);
    if (unique.size !== ids.length) throw userError(`Pipeline "${pipeline.id}" has duplicate step ids`, 'PIPELINE_DUPLICATE_STEP');

    for (const tool of pipeline.steps.map((s) => s.tool)) {
      if (!this.policy.isToolKnown(tool)) {
        throw userError(`Pipeline "${pipeline.id}" uses unknown tool "${tool}"`, 'PIPELINE_UNKNOWN_TOOL');
      }
      if (this.policy.isToolEnabled && !this.policy.isToolEnabled(tool)) {
        throw userError(`Pipeline "${pipeline.id}" uses disabled tool "${tool}"`, 'PIPELINE_TOOL_DISABLED');
      }
    }

    const indexById = new Map(ids.map((id, i) => [id, i]));
    pipeline.steps.forEach((step, stepIndex) => {
      for (const ref of this.collectRefs(step.input)) {
        if (ref.startsWith('input.')) continue;
        if (ref.startsWith('steps.')) {
          const targetId = ref.slice('steps.'.length).split('.')[0];
          const targetIndex = indexById.get(targetId);
          if (targetIndex === undefined) {
            throw userError(`Pipeline "${pipeline.id}" step "${step.id}" references unknown step "${targetId}"`, 'PIPELINE_UNKNOWN_STEP_REF');
          }
          if (targetIndex >= stepIndex) {
            throw userError(`Pipeline "${pipeline.id}" step "${step.id}" references step "${targetId}" declared later`, 'PIPELINE_FORWARD_STEP_REF');
          }
          continue;
        }
        throw userError(`Pipeline "${pipeline.id}" step "${step.id}" has invalid template reference "${ref}"`, 'PIPELINE_INVALID_REF');
      }
    });
  }

  private collectRefs(value: unknown, out: string[] = []): string[] {
    if (typeof value === 'string') {
      TEMPLATE_REF_RE.lastIndex = 0;
      let m: RegExpExecArray | null;
      while ((m = TEMPLATE_REF_RE.exec(value)) !== null) out.push(m[1].trim());
      return out;
    }
    if (Array.isArray(value)) {
      for (const item of value) this.collectRefs(item, out);
      return out;
    }
    if (value !== null && typeof value === 'object') {
      for (const child of Object.values(value as Record<string, unknown>)) this.collectRefs(child, out);
    }
    return out;
  }
}