import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { userError } from '../errors.js';

export const DEFAULT_MAX_FILE_BYTES = 1024 * 1024; // 1 MiB

/**
 * Безопасная запись файлов для saveToFile: разрешён только каталог data/output/.
 * Запрещены: абсолютные пути, ../ и Windows-диски. Ограничение размера — 1 MiB.
 */
export class OutputFileService {
  readonly rootDir: string;
  private readonly maxBytes: number;

  constructor(rootDir: string, opts: { maxBytes?: number } = {}) {
    this.rootDir = path.resolve(rootDir);
    this.maxBytes = opts.maxBytes ?? DEFAULT_MAX_FILE_BYTES;
    mkdirSync(this.rootDir, { recursive: true });
  }

  /** Записать содержимое; возвращает относительный путь и размер в байтах. */
  write(filename: string, content: string): { path: string; size: number } {
    if (typeof filename !== 'string' || filename.trim() === '') {
      throw userError('saveToFile: filename is required', 'INVALID_FILENAME');
    }
    const root = this.rootDir;
    const normalized = path.normalize(filename.replace(/\\/g, '/'));
    const segments = normalized.split('/');
    if (path.isAbsolute(normalized) || segments.some((s) => s === '..')) {
      throw userError('saveToFile: filename must not contain path traversal (".." or absolute path)', 'INVALID_FILENAME');
    }
    if (/^[a-zA-Z]:/.test(filename)) {
      throw userError('saveToFile: absolute paths are not allowed', 'INVALID_FILENAME');
    }
    const target = path.join(root, normalized);
    if (!target.startsWith(root + path.sep)) {
      throw userError('saveToFile: filename escapes output directory', 'INVALID_FILENAME');
    }

    const bytes = Buffer.byteLength(String(content ?? ''), 'utf8');
    if (bytes > this.maxBytes) {
      throw userError(`saveToFile: file too large (${bytes} bytes, limit ${this.maxBytes})`, 'FILE_TOO_LARGE');
    }
    mkdirSync(path.dirname(target), { recursive: true });
    writeFileSync(target, String(content ?? ''), 'utf8');
    return { path: path.relative(root, target), size: bytes };
  }
}