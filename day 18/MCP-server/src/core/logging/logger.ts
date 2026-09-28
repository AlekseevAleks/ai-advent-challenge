import { appendFile } from 'node:fs';
import { redactText, safeStringify } from '../util/redact.js';
import type { LogLevel } from '../types.js';

const LEVEL_WEIGHT: Record<Exclude<LogLevel, 'silent'>, number> = { debug: 0, info: 1, warn: 2, error: 3 };

interface LoggerOptions {
  /** silent подавляет весь вывод (для тестов). */
  level?: LogLevel;
  /** Путь к файлу для дублирования записей (data/logs/server.log). */
  file?: string;
  /** Префикс scope (например, "http", "mcp"). */
  scope?: string;
  /** Писать ли в stdout/stderr (выключено для stdio MCP-режима). */
  consoleOutput?: boolean;
}

/**
 * Лёгкий структурированный логгер приложения.
 * Все сообщения прогоняются через redactText, чтобы типичные секреты
 * не попадали в файловые логи даже в сообщениях об ошибках.
 */
export class Logger {
  private readonly level: LogLevel;
  private readonly file?: string;
  private readonly scope?: string;
  private readonly consoleOutput: boolean;

  constructor(opts: LoggerOptions = {}) {
    this.level = opts.level ?? 'info';
    this.file = opts.file;
    this.scope = opts.scope;
    this.consoleOutput = opts.consoleOutput ?? true;
  }

  setLevel(level: LogLevel): void {
    (this as unknown as { level: LogLevel }).level = level;
  }

  child(scope: string): Logger {
    return new Logger({
      level: this.level,
      file: this.file,
      scope: scope ? (this.scope ? `${this.scope}:${scope}` : scope) : this.scope,
      consoleOutput: this.consoleOutput,
    });
  }

  debug(msg: string, meta?: unknown): void {
    this.write('debug', msg, meta);
  }

  info(msg: string, meta?: unknown): void {
    this.write('info', msg, meta);
  }

  warn(msg: string, meta?: unknown): void {
    this.write('warn', msg, meta);
  }

  error(msg: string, meta?: unknown): void {
    this.write('error', msg, meta);
  }

  private write(level: Exclude<LogLevel, 'silent'>, msg: string, meta?: unknown): void {
    if (this.level === 'silent') return;
    if (LEVEL_WEIGHT[level] < LEVEL_WEIGHT[this.level]) return;

    const safeMeta = meta === undefined ? '' : ` ${redactText(safeStringify(meta))}`;
    const line = `[${new Date().toISOString()}] [${level}]${this.scope ? ` [${this.scope}]` : ''} ${redactText(msg)}${safeMeta}`;

    if (this.consoleOutput) {
      if (level === 'error' || level === 'warn') process.stderr.write(`${line}\n`);
      else process.stdout.write(`${line}\n`);
    }
    if (this.file) {
      appendFile(this.file, `${line}\n`, () => {
        /* fire-and-forget, никогда не роняем приложение из-за лога */
      });
    }
  }
}

/** Логгер без вывода — удобен в тестах и CLI. */
export const nullLogger = new Logger({ level: 'silent' });