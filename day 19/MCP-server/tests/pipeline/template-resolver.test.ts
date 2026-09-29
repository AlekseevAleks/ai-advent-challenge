import { describe, expect, it } from 'vitest';
import { TemplateResolver } from '../../src/core/pipeline/template-resolver.js';

const resolver = new TemplateResolver();

function ctx(steps: Record<string, unknown> = {}, input: Record<string, unknown> = {}) {
  return { input, steps };
}

describe('TemplateResolver', () => {
  it('single variable returns the actual typed value (object/array preserved)', () => {
    const obj = { a: 1 };
    const arr = [1, 2, 3];
    expect(resolver.resolve('{{steps.x.output}}', ctx({ x: { output: obj } }))).toEqual(obj);
    expect(resolver.resolve('{{steps.x.output}}', ctx({ x: { output: arr } }))).toEqual(arr);
    expect(resolver.resolve('{{input.n}}', ctx({}, { n: 42 }))).toBe(42);
    expect(resolver.resolve('{{input.b}}', ctx({}, { b: true }))).toBe(true);
    expect(resolver.resolve('{{input.s}}', ctx({}, { s: 'hello' }))).toBe('hello');
    expect(resolver.resolve('{{input.n}}', ctx({}, { n: null }))).toBeNull();
  });

  it('supports nested paths', () => {
    expect(resolver.resolve('{{steps.a.output.issues}}', ctx({ a: { output: { issues: [1, 2] } } }))).toEqual([1, 2]);
    expect(resolver.resolve('{{steps.a.output.weather.temperatureC}}', ctx({ a: { output: { weather: { temperatureC: 15.5 } } } }))).toBe(15.5);
  });

  it('supports array indexes', () => {
    expect(resolver.resolve('{{steps.a.output.items[1].title}}', ctx({ a: { output: { items: [{ title: 'x' }, { title: 'y' }] } } }))).toBe('y');
  });

  it('supports embedded templates in strings', () => {
    expect(resolver.resolve('Report for {{input.owner}}/{{input.repo}}', ctx({}, { owner: 'octocat', repo: 'hello' }))).toBe('Report for octocat/hello');
  });

  it('serializes objects/arrays inside embedded templates as JSON', () => {
    expect(resolver.resolve('data={{steps.a.output}}', ctx({ a: { output: { x: 1 } } }))).toBe('data={"x":1}');
  });

  it('recurses into objects and arrays of templates', () => {
    const value = { filename: '{{input.repo}}-summary.txt', nested: { list: ['{{input.owner}}'] } };
    expect(resolver.resolve(value, ctx({}, { owner: 'o', repo: 'r' }))).toEqual({
      filename: 'r-summary.txt',
      nested: { list: ['o'] },
    });
  });

  it('throws on unknown reference paths', () => {
    expect(() => resolver.resolve('{{steps.missing.output}}', ctx({}))).toThrowError(/not found/);
    expect(() => resolver.resolve('{{input.nope}}', ctx({}))).toThrowError(/not found/);
  });

  it('throws on invalid reference prefixes (no eval, no code execution)', () => {
    expect(() => resolver.resolve('{{process.exit(1)}}', ctx({}))).toThrowError(/input|steps/);
    expect(() => resolver.resolve('{{constructor.constructor}}', ctx({}))).toThrowError(/input|steps/);
  });

  it('does not use eval or Function', () => {
    const src = String(new TemplateResolver());
    expect(src).not.toContain('eval');
    expect(src).not.toContain('new Function');
  });
});