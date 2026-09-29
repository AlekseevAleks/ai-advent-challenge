import { describe, expect, it } from 'vitest';
import { mkdtempSync, rmSync, readFileSync, statSync, existsSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { LlmSettingsStore } from '../../src/core/llm/llm-settings-store.js';

function tmpDir(): string {
  return mkdtempSync(path.join(os.tmpdir(), 'mcp-gw-llm-'));
}

describe('LlmSettingsStore', () => {
  it('saves and loads settings (round-trip)', () => {
    const dir = tmpDir();
    const store = new LlmSettingsStore(dir);
    store.save({ provider: 'openai', apiUrl: 'https://api.openai.com/v1', apiKey: 'sk-secret-123', model: 'gpt-4.1' });
    const loaded = store.load();
    expect(loaded.apiUrl).toBe('https://api.openai.com/v1');
    expect(loaded.apiKey).toBe('sk-secret-123');
    expect(loaded.model).toBe('gpt-4.1');
    store.save({ provider: 'openai', apiUrl: 'https://example.com/v1', apiKey: 'sk-new', model: 'my-model' });
    expect(store.load().apiKey).toBe('sk-new');
    rmSync(dir, { recursive: true, force: true });
  });

  it('writes file with 0600 permissions and never otherwise exposes the key', () => {
    const dir = tmpDir();
    const store = new LlmSettingsStore(dir);
    store.save({ provider: 'openai', apiUrl: 'https://api.openai.com/v1', apiKey: 'sk-super-secret-value', model: 'gpt-4.1' });
    const file = path.join(dir, 'llm.json');
    expect(existsSync(file)).toBe(true);
    expect(statSync(file).mode & 0o777).toBe(0o600);
    const raw = readFileSync(file, 'utf8');
    expect(raw).toContain('sk-super-secret-value'); // ключ лежит только в этом файле
    rmSync(dir, { recursive: true, force: true });
  });

  it('getPublic never returns the API key', () => {
    const dir = tmpDir();
    const store = new LlmSettingsStore(dir);
    store.save({ provider: 'openai', apiUrl: 'https://api.openai.com/v1', apiKey: 'sk-very-secret', model: 'gpt-4.1' });
    const pub = store.getPublic();
    expect('apiKey' in (pub as object)).toBe(false);
    expect(JSON.stringify(pub)).not.toContain('sk-very-secret');
    expect(pub.configured).toBe(true);
    expect(store.isConfigured()).toBe(true);

    store.save({ provider: 'openai', apiUrl: 'https://api.openai.com/v1', apiKey: '', model: '' });
    expect(store.getPublic().configured).toBe(false);
    expect(store.isConfigured()).toBe(false);
    rmSync(dir, { recursive: true, force: true });
  });

  it('returns defaults when the file is missing', () => {
    const dir = tmpDir();
    const store = new LlmSettingsStore(dir);
    const loaded = store.load();
    expect(loaded.provider).toBe('openai');
    expect(loaded.apiUrl).toBe('https://api.openai.com/v1');
    expect(loaded.apiKey).toBe('');
    rmSync(dir, { recursive: true, force: true });
  });

  it('.gitignore protects data/llm.json and example file exists', () => {
    const gitignore = readFileSync(path.resolve(process.cwd(), '.gitignore'), 'utf8');
    expect(gitignore).toContain('data/llm.json');
    expect(gitignore).toContain('data/pipelines.db');
    expect(gitignore).toContain('data/output');
    const example = path.resolve(process.cwd(), 'data', 'llm.example.json');
    expect(existsSync(example)).toBe(true);
    const exampleRaw = readFileSync(example, 'utf8');
    expect(exampleRaw).not.toContain('sk-');
  });
});