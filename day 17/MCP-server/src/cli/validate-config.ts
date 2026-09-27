import path from 'node:path';
import { ConfigManager } from '../core/config/config-manager.js';
import { HttpClient } from '../core/http/http-client.js';
import { Logger } from '../core/logging/logger.js';
import { BUILTIN_PROVIDERS } from '../../providers/index.js';
import { AppError } from '../core/errors.js';
import type { ApiProvider } from '../core/providers/types.js';

type ProviderClass = new (http: HttpClient) => ApiProvider;

/**
 * CLI: проверка JSON-конфигурации без запуска сервера.
 *
 *   npm run validate-config
 *   node dist/src/cli/validate-config.js --config-dir ./config
 *
 * Проверяет: server.json, файлы config/providers/*.json, соответствие провайдеров
 * зарегистрированным классам и валидацию настроек в initialize() (без сети).
 */
async function main(): Promise<void> {
  const args = process.argv.slice(2);
  const readFlag = (name: string): string | undefined => {
    const idx = args.indexOf(name);
    return idx >= 0 && args[idx + 1] ? args[idx + 1] : undefined;
  };
  const configDir = readFlag('--config-dir') ?? process.env.MCP_CONFIG_DIR ?? path.resolve(process.cwd(), 'config');
  const dataDir = readFlag('--data-dir') ?? process.env.MCP_DATA_DIR ?? path.resolve(process.cwd(), 'data');

  const logger = new Logger({ level: 'silent' });
  const configManager = new ConfigManager({ configDir, dataDir });
  const httpClient = new HttpClient({ logger });

  const classes = new Map<string, ProviderClass>();
  for (const cls of BUILTIN_PROVIDERS) {
    const probe = new cls(httpClient);
    classes.set(probe.id, cls);
  }

  let failed = false;
  const fail = (message: string): void => {
    failed = true;
    process.stdout.write(`  [FAIL] ${message}\n`);
  };
  const ok = (message: string): void => {
    process.stdout.write(`  [ OK ] ${message}\n`);
  };

  process.stdout.write(`Validating config directory: ${configDir}\n\n`);

  // server.json
  try {
    const settings = configManager.loadServerConfig();
    ok(`server.json -> host=${settings.host} port=${settings.port} logLevel=${settings.logLevel}`);
  } catch (err) {
    fail(`server.json -> ${describeError(err)}`);
  }

  // config/credentials.json (отдельный файл секретов)
  try {
    const credentials = configManager.loadCredentials();
    const providersWithSecrets = Object.keys(credentials);
    ok(
      providersWithSecrets.length === 0
        ? `credentials.json -> not present or empty (optional)`
        : `credentials.json -> secrets for: ${providersWithSecrets.join(', ')}`,
    );
  } catch (err) {
    fail(`credentials.json -> ${describeError(err)}`);
  }

  // провайдеры
  const providerIds = configManager.listProviderIds();
  if (providerIds.length === 0) {
    process.stdout.write('\nNo provider config files found (directory is empty).\n');
  }
  for (const id of providerIds) {
    try {
      const cfg = configManager.getProviderConfig(id);
      if (!classes.has(id)) {
        fail(`${id}.json -> unknown provider class "${id}" (no registered provider). Check providers/index.ts`);
        continue;
      }
      const instance = new (classes.get(id) as ProviderClass)(httpClient);
      // Используем initialize() как финальную валидацию настроек
      await instance.initialize(cfg as never);
      const toolCount = instance.getTools().length;
      ok(`${id}.json -> valid (${toolCount} tools, enabled=${cfg?.enabled !== false})`);
    } catch (err) {
      if (err instanceof AppError && err.kind === 'config') {
        fail(`${id}.json -> ${err.message}`);
      } else {
        fail(`${id}.json -> ${describeError(err)}`);
      }
    }
  }

  process.stdout.write('\n');
  if (failed) {
    process.stdout.write('Configuration is INVALID.\n');
    process.exit(1);
  }
  process.stdout.write('Configuration is valid.\n');
  process.exit(0);
}

function describeError(err: unknown): string {
  if (err instanceof AppError) return err.message;
  if (err instanceof Error) return err.message;
  return String(err);
}

main().catch((err) => {
  process.stderr.write(`validate-config fatal: ${err instanceof Error ? err.message : String(err)}\n`);
  process.exit(1);
});