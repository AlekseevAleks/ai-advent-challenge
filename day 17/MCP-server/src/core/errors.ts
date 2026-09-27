import type { AppErrorKind } from './types.js';

/**
 * Типизированная ошибка приложения.
 * Разделяет User/MCP-ошибки, внутренние, внешние API-ошибки, конфигурацию,
 * аутентификацию, rate limit и таймауты.
 */
export class AppError extends Error {
  readonly kind: AppErrorKind;
  readonly code: string;
  readonly status?: number;
  readonly details?: unknown;
  readonly retryAfter?: number;
  override readonly cause?: unknown;

  constructor(opts: {
    message: string;
    kind: AppErrorKind;
    code: string;
    status?: number;
    details?: unknown;
    retryAfter?: number;
    cause?: unknown;
  }) {
    super(opts.message);
    this.name = 'AppError';
    this.kind = opts.kind;
    this.code = opts.code;
    this.status = opts.status;
    this.details = opts.details;
    this.retryAfter = opts.retryAfter;
    this.cause = opts.cause;
  }
}

export const userError = (message: string, code = 'INVALID_INPUT', details?: unknown) =>
  new AppError({ message, kind: 'user', code, details });

export const configError = (message: string, code = 'CONFIG_ERROR', details?: unknown) =>
  new AppError({ message, kind: 'config', code, details });

export const internalError = (message: string, code = 'INTERNAL_ERROR', cause?: unknown) =>
  new AppError({ message, kind: 'internal', code, cause });

export const externalApiError = (
  message: string,
  status?: number,
  details?: unknown,
  code = 'EXTERNAL_API_ERROR',
) => new AppError({ message, kind: 'external', code, status, details });

export const authError = (message: string, code = 'AUTH_ERROR', status?: number, details?: unknown) =>
  new AppError({ message, kind: 'auth', code, status, details });

export const rateLimitError = (message: string, retryAfter?: number, code = 'RATE_LIMIT') =>
  new AppError({ message, kind: 'rate_limit', code, status: 429, retryAfter });

export const timeoutError = (message: string, code = 'TIMEOUT', cause?: unknown) =>
  new AppError({ message, kind: 'timeout', code, cause });

/** Человекочитаемое имя категории для логов и UI. */
export const errorKindName = (kind: AppErrorKind): string => {
  switch (kind) {
    case 'user':
      return 'Invalid input';
    case 'internal':
      return 'Internal error';
    case 'external':
      return 'External API error';
    case 'config':
      return 'Configuration error';
    case 'auth':
      return 'Authentication error';
    case 'rate_limit':
      return 'Rate limit';
    case 'timeout':
      return 'Timeout';
  }
};

/** Привести неизвестную ошибку к AppError (без утечки stack trace наружу). */
export function toAppError(err: unknown): AppError {
  if (err instanceof AppError) return err;
  const message = err instanceof Error ? err.message : String(err);
  return internalError('Internal server error', 'INTERNAL_ERROR', err);
}

/** HTTP-статус для REST API по категории ошибки. */
export function appErrorStatus(err: AppError): number {
  switch (err.kind) {
    case 'user':
    case 'config':
      return 400;
    case 'auth':
      return 401;
    case 'external':
      return 502;
    case 'rate_limit':
      return 429;
    case 'timeout':
      return 504;
    case 'internal':
    default:
      return 500;
  }
}