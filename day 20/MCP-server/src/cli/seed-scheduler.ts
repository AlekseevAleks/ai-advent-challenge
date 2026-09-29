import { buildRuntime } from '../server/runtime.js';

/**
 * Seed демо-задач Scheduler:
 *   npm run seed:scheduler
 *
 * Создаёт:
 *   demo-weather-berlin       — каждый час weather_current(Берлин)
 *   demo-github-linux-issues  — каждые 30 минут github_list_issues(torvalds/linux)
 *
 * Идемпотентно: при повторном запуске существующие задачи не пересоздаются.
 */
async function main(): Promise<void> {
  const runtime = await buildRuntime({ consoleOutput: false });
  const created = await runtime.taskManager.createDemoTasks();
  if (created.length > 0) {
    process.stdout.write(`Created demo scheduled tasks: ${created.join(', ')}\n`);
  } else {
    process.stdout.write('Demo scheduled tasks already exist (nothing to create).\n');
  }
  runtime.taskStorage.close();
  process.exit(0);
}

main().catch((err) => {
  process.stderr.write(`seed:scheduler fatal: ${err instanceof Error ? err.message : String(err)}\n`);
  process.exit(1);
});