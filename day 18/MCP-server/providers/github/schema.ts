import { z } from 'zod';
import type { ConfigSchema, ToolInputSchema } from '../../src/core/providers/types.js';
import type { ConfigField } from '../../src/core/providers/types.js';

export const GITHUB_BASE_URL = 'https://api.github.com';
export const GITHUB_TOKEN_ENV = 'GITHUB_TOKEN';
export const GITHUB_VERSION_HEADER = '2022-11-28';

export const GITHUB_CONFIG_SCHEMA: ConfigSchema = {
  fields: [
    {
      key: 'baseUrl',
      label: 'Base URL',
      type: 'string',
      required: true,
      default: GITHUB_BASE_URL,
      description: 'Базовый URL GitHub REST API.',
    },
  ],
  settingsFields: [
    { key: 'timeout', label: 'Timeout', type: 'number', unit: 'ms', default: 10000, description: 'Таймаут HTTP-запроса.' },
  ],
  credentialFields: [
    {
      key: 'token',
      label: 'Personal Access Token',
      type: 'string',
      secret: true,
      env: GITHUB_TOKEN_ENV,
      placeholder: 'ghp_...',
      description: 'GitHub Personal Access Token (read-only достаточно для демо). Можно задать через env GITHUB_TOKEN.',
    },
  ],
};

/** Input schema (zod) по каждому tool. */
export const getRepositorySchema = z.object({
  owner: z.string().min(1, 'owner is required').max(100),
  repo: z.string().min(1, 'repo is required').max(100),
});

export const listIssuesSchema = z.object({
  owner: z.string().min(1).max(100),
  repo: z.string().min(1).max(100),
  state: z.enum(['open', 'closed', 'all']).optional(),
  limit: z.number().int().min(1).max(100).optional(),
  includePullRequests: z.boolean().optional(),
});

export const getIssueSchema = z.object({
  owner: z.string().min(1).max(100),
  repo: z.string().min(1).max(100),
  issueNumber: z.number().int().min(1),
});

export const listPullRequestsSchema = z.object({
  owner: z.string().min(1).max(100),
  repo: z.string().min(1).max(100),
  state: z.enum(['open', 'closed', 'all']).optional(),
  limit: z.number().int().min(1).max(100).optional(),
});

export const searchRepositoriesSchema = z.object({
  query: z.string().min(1, 'query is required').max(256),
  limit: z.number().int().min(1).max(100).optional(),
});

export const getFileSchema = z.object({
  owner: z.string().min(1).max(100),
  repo: z.string().min(1).max(100),
  path: z.string().min(1).max(500),
  ref: z.string().min(1).max(200).optional(),
});

// ------------------------------------------------------- JSON Schema для MCP

const prop = (description: string, type: string, extra: Record<string, unknown> = {}): Record<string, unknown> => ({
  type,
  description,
  ...extra,
});

export const getRepositoryToolSchema: ToolInputSchema = {
  type: 'object',
  properties: {
    owner: prop('Владелец репозитория (например, torvalds)', 'string'),
    repo: prop('Имя репозитория (например, linux)', 'string'),
  },
  required: ['owner', 'repo'],
  additionalProperties: false,
};

export const listIssuesToolSchema: ToolInputSchema = {
  type: 'object',
  properties: {
    owner: prop('Владелец репозитория', 'string'),
    repo: prop('Имя репозитория', 'string'),
    state: prop('Фильтр по состоянию: open, closed, all (по умолчанию open)', 'string'),
    limit: prop('Максимум результатов, 1–100 (по умолчанию 30)', 'number'),
    includePullRequests: prop('Включать pull requests (они попадают в issues API)', 'boolean'),
  },
  required: ['owner', 'repo'],
  additionalProperties: false,
};

export const getIssueToolSchema: ToolInputSchema = {
  type: 'object',
  properties: {
    owner: prop('Владелец репозитория', 'string'),
    repo: prop('Имя репозитория', 'string'),
    issueNumber: prop('Номер issue', 'number'),
  },
  required: ['owner', 'repo', 'issueNumber'],
  additionalProperties: false,
};

export const listPullRequestsToolSchema: ToolInputSchema = {
  type: 'object',
  properties: {
    owner: prop('Владелец репозитория', 'string'),
    repo: prop('Имя репозитория', 'string'),
    state: prop('Фильтр по состоянию: open, closed, all (по умолчанию open)', 'string'),
    limit: prop('Максимум результатов, 1–100 (по умолчанию 30)', 'number'),
  },
  required: ['owner', 'repo'],
  additionalProperties: false,
};

export const searchRepositoriesToolSchema: ToolInputSchema = {
  type: 'object',
  properties: {
    query: prop('Поисковый запрос GitHub (например, "language:typescript stars:>100")', 'string'),
    limit: prop('Максимум результатов, 1–100 (по умолчанию 10)', 'number'),
  },
  required: ['query'],
  additionalProperties: false,
};

export const getFileToolSchema: ToolInputSchema = {
  type: 'object',
  properties: {
    owner: prop('Владелец репозитория', 'string'),
    repo: prop('Имя репозитория', 'string'),
    path: prop('Путь к файлу или директории внутри репозитория (например, README.md)', 'string'),
    ref: prop('Ветка/тег/commit SHA (по умолчанию default branch)', 'string'),
  },
  required: ['owner', 'repo', 'path'],
  additionalProperties: false,
};

export type ConfigFieldExport = ConfigField;