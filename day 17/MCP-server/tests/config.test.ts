import { describe, expect, it } from 'vitest';
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { ConfigManager } from '../src/core/config/config-manager.js';
import { AppError } from '../src/core/errors.js';

function makeManager(files: Record<string, unknown>): ConfigManager {
  const tmp = mkdtempSync(path.join(os.tmpdir(), 'mcp-gw-cfg-'));
  const configDir = path.join(tmp, 'config');
  mkdirSync(path.join(configDir, 'providers'), { recursive: true });
  for (const [name, value] of Object.entries(files)) {
    writeFileSync(path.join(configDir, name), typeof value === 'string' ? value : JSON.stringify(value, null, 2));
  }
  const manager = new ConfigManager({ configDir, dataDir: path.join(tmp, 'data') });
  (manager as unknown as { __tmp: string }).__tmp = tmp;
  return manager;
}

function rmManager(manager: ConfigManager): void {
  rmSync((manager as unknown as { __tmp: string }).__tmp, { recursive: true, force: true });
}

describe('ConfigManager', () => {
  it('loads valid server config with defaults', () => {
    const manager = makeManager({ 'server.json': {} });
    const cfg = manager.loadServerConfig();
    expect(cfg.host).toBe('127.0.0.1');
    expect(cfg.port).toBe(3000);
    expect(cfg.maxResponseLogSize).toBe(64 * 1024);
    rmManager(manager);
  });

  it('rejects invalid JSON in server.json', () => {
    const manager = makeManager({ 'server.json': '{not json' });
    let caught: AppError | undefined;
    try {
      manager.loadServerConfig();
    } catch (err) {
      caught = err as AppError;
    }
    expect(caught?.kind).toBe('config');
    expect(caught?.code).toBe('INVALID_JSON');
    rmManager(manager);
  });

  it('rejects invalid typed server config', () => {
    const manager = makeManager({ 'server.json': { port: 'abc' } });
    expect(() => manager.loadServerConfig()).toThrowError(/port/);
    rmManager(manager);
  });

  it('validates provider config files and id consistency', () => {
    const manager = makeManager({ 'providers/github.json': { id: 'github', enabled: true } });
    const cfg = manager.getProviderConfig('github');
    expect(cfg?.id).toBe('github');
    expect(cfg?.enabled).toBe(true);
    rmManager(manager);

    const mismatched = makeManager({ 'providers/github.json': { id: 'weather', enabled: true } });
    let caught: AppError | undefined;
    try {
      mismatched.getProviderConfig('github');
    } catch (err) {
      caught = err as AppError;
    }
    expect(caught?.code).toBe('PROVIDER_ID_MISMATCH');
    rmManager(mismatched);
  });

  it('protects against path traversal in provider ids', () => {
    const manager = makeManager({ 'providers/github.json': { id: 'github', enabled: true } });
    for (const bad of ['../secret', '..%2F..%2Fetc%2Fpasswd', 'a/b', 'a\\b', '', 'toolong'.repeat(20)]) {
      expect(() => manager.resolveProviderPath(bad)).toThrowError(/Invalid provider id/);
      expect(() => manager.getProviderConfig(bad)).toThrowError(/Invalid provider id/);
    }
    rmManager(manager);
  });

  it('updateProviderConfig merges settings and tools, handles empty credential removal', () => {
    const manager = makeManager({ 'providers/github.json': { id: 'github', enabled: true, credentials: { token: 'abc' }, settings: { timeout: 1000 } } });
    manager.updateProviderConfig('github', {
      settings: { retries: 2 },
      credentials: { token: 'new-token' },
    });
    const after = manager.getProviderConfig('github')!;
    expect(after.settings).toEqual({ timeout: 1000, retries: 2 });
    expect(after.credentials?.token).toBe('new-token');

    manager.updateProviderConfig('github', { credentials: { token: '' } });
    expect(manager.getProviderConfig('github')?.credentials?.token).toBeUndefined();
    rmManager(manager);
  });

  it('saves secrets to a separate credentials.json and never writes them into provider files', () => {
    const manager = makeManager({ 'providers/github.json': { id: 'github', enabled: true } });
    manager.updateProviderConfig('github', { credentials: { token: 'very-secret-value' } });

    // В файл провайдера секреты не попадают
    const providerFile = manager.getProviderConfig('github')!;
    expect(providerFile.credentials?.token).toBe('very-secret-value');
    const rawProviderFile = readFileSync(manager.resolveProviderPath('github'), 'utf8');
    expect(rawProviderFile).not.toContain('very-secret-value');

    // Секрет лежит в отдельном файле credentials.json
    const credentialsFile = readFileSync(path.join(manager.configDir, 'credentials.json'), 'utf8');
    expect(credentialsFile).toContain('very-secret-value');
    expect(JSON.parse(credentialsFile)).toEqual({ github: { token: 'very-secret-value' } });
    rmManager(manager);
  });

  it('migrates legacy credentials from provider files into the separate store and cleans them', () => {
    const manager = makeManager({
      'providers/github.json': { id: 'github', enabled: true, credentials: { token: 'legacy-token' } },
      'providers/weather.json': { id: 'weather', enabled: true, credentials: {} },
    });
    const moved = manager.migrateLegacyCredentials();
    expect(moved).toBe(1);

    const credentialsFile = readFileSync(path.join(manager.configDir, 'credentials.json'), 'utf8');
    const stored = JSON.parse(credentialsFile) as Record<string, Record<string, string>>;
    expect(stored.github?.token).toBe('legacy-token');
    expect(stored.weather).toBeUndefined();

    const githubFile = readFileSync(manager.resolveProviderPath('github'), 'utf8');
    expect(githubFile).not.toContain('legacy-token');
    expect(githubFile).not.toContain('"credentials"');
    // После миграции getProviderConfig всё равно возвращает секрет (из стора)
    expect(manager.getProviderConfig('github')?.credentials?.token).toBe('legacy-token');
    rmManager(manager);
  });

  it('gives priority to the credentials store over legacy credentials in provider files', () => {
    const manager = makeManager({ 'providers/github.json': { id: 'github', enabled: true, credentials: { token: 'file-token' } } });
    manager.saveProviderCredentials('github', { token: 'store-token' });
    expect(manager.getProviderConfig('github')?.credentials?.token).toBe('store-token');
    rmManager(manager);
  });

  it('rejects an invalid credentials.json shape', () => {
    const manager = makeManager({ 'credentials.json': { github: { token: 123 } } });
    let caught: AppError | undefined;
    try {
      manager.loadCredentials();
    } catch (err) {
      caught = err as AppError;
    }
    expect(caught?.code).toBe('INVALID_CREDENTIALS');
    rmManager(manager);
  });

  it('applies env overrides for critical server settings', () => {
    const manager = makeManager({ 'server.json': {} });
    const withEnv = new ConfigManager({
      configDir: manager.configDir,
      dataDir: manager.dataDir,
      env: { MCP_HOST: '0.0.0.0', MCP_PORT: '4000', MCP_LOG_LEVEL: 'debug', MCP_DEBUG: 'true' },
    });
    const cfg = withEnv.loadServerConfig();
    expect(cfg.host).toBe('0.0.0.0');
    expect(cfg.port).toBe(4000);
    expect(cfg.logLevel).toBe('debug');
    expect(cfg.debug).toBe(true);
    rmManager(manager);
  });
});