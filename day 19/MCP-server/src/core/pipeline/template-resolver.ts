import { userError } from '../errors.js';
import { safeStringify } from '../util/redact.js';

export interface TemplateContext {
  input: Record<string, unknown>;
  steps: Record<string, unknown>;
}

const TEMPLATE_RE = /\{\{\s*([^{}]+?)\s*\}\}/g;

/**
 * TemplateResolver: подстановка {{input.x}}, {{steps.<id>.output}}, {{steps.<id>.output.path}}.
 * БЕЗ eval/Function: только обход контекста по строкам пути.
 * Если строка — одна переменная целиком, возвращается настоящее значение (object/array сохраняются).
 */
export class TemplateResolver {
  resolve(value: unknown, ctx: TemplateContext): unknown {
    if (typeof value === 'string') {
      return this.resolveString(value, ctx);
    }
    if (Array.isArray(value)) {
      return value.map((item) => this.resolve(item, ctx));
    }
    if (value !== null && typeof value === 'object') {
      const out: Record<string, unknown> = {};
      for (const [key, child] of Object.entries(value as Record<string, unknown>)) {
        out[key] = this.resolve(child, ctx);
      }
      return out;
    }
    return value;
  }

  private resolveString(str: string, ctx: TemplateContext): unknown {
    const trimmed = str.trim();
    const matches = this.findTemplates(str);
    if (matches.length === 1 && matches[0].full === trimmed) {
      return this.lookup(matches[0].ref, ctx);
    }
    let result = str;
    for (const match of matches) {
      const value = this.lookup(match.ref, ctx);
      const rendered = value === undefined ? '' : typeof value === 'string' ? value : safeStringify(value);
      result = result.replace(match.full, rendered);
    }
    return result;
  }

  private findTemplates(str: string): Array<{ full: string; ref: string }> {
    const found: Array<{ full: string; ref: string }> = [];
    TEMPLATE_RE.lastIndex = 0;
    let match: RegExpExecArray | null;
    while ((match = TEMPLATE_RE.exec(str)) !== null) {
      found.push({ full: match[0], ref: match[1].trim() });
    }
    return found;
  }

  /** Lookup пути в контексте: input.owner | steps.getIssues.output.issues | items[0].title */
  private lookup(ref: string, ctx: TemplateContext): unknown {
    if (ref.startsWith('input.')) {
      return this.getPath(ctx.input, ref.slice('input.'.length));
    }
    if (ref.startsWith('steps.')) {
      return this.getPath(ctx.steps, ref.slice('steps.'.length));
    }
    throw userError(`Template reference "${ref}" must start with "input." or "steps."`, 'INVALID_TEMPLATE_REF');
  }

  private getPath(root: unknown, path: string): unknown {
    let current = root;
    for (const raw of path.split('.')) {
      const { key, index } = this.parseSegment(raw);
      if (current === undefined || current === null || typeof current !== 'object') {
        throw userError(`Template reference not found: "${raw}"`, 'TEMPLATE_REF_NOT_FOUND');
      }
      const obj = current as Record<string, unknown>;
      if (!(key in obj)) {
        throw userError(`Template reference not found: "${key}"`, 'TEMPLATE_REF_NOT_FOUND');
      }
      current = obj[key];
      if (index !== undefined) {
        if (!Array.isArray(current) || index >= current.length) {
          throw userError(`Template reference not found: "${raw}"`, 'TEMPLATE_REF_NOT_FOUND');
        }
        current = current[index];
      }
    }
    return current;
  }

  private parseSegment(segment: string): { key: string; index?: number } {
    const match = /^(.+?)(?:\[(\d+)\])?$/.exec(segment);
    if (!match) return { key: segment };
    const index = match[2] !== undefined ? Number(match[2]) : undefined;
    return { key: match[1], index };
  }
}