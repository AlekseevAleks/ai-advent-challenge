import type { ToolDefinition } from '../../src/core/providers/types.js';
import {
  getFileToolSchema,
  getIssueToolSchema,
  getRepositoryToolSchema,
  listIssuesToolSchema,
  listPullRequestsToolSchema,
  searchRepositoriesToolSchema,
} from './schema.js';

export const GITHUB_TOOLS: ToolDefinition[] = [
  {
    name: 'github_get_repository',
    description: 'Информация о репозитории GitHub: описание, звёзды, форки, язык, лицензия и т.д.',
    inputSchema: getRepositoryToolSchema,
  },
  {
    name: 'github_list_issues',
    description: 'Список issues репозитория GitHub с фильтром по состоянию.',
    inputSchema: listIssuesToolSchema,
  },
  {
    name: 'github_get_issue',
    description: 'Детальная информация об issue GitHub, включая тело и исполнителей.',
    inputSchema: getIssueToolSchema,
  },
  {
    name: 'github_list_pull_requests',
    description: 'Список pull requests репозитория GitHub.',
    inputSchema: listPullRequestsToolSchema,
  },
  {
    name: 'github_search_repositories',
    description: 'Поиск репозиториев GitHub по поисковому запросу.',
    inputSchema: searchRepositoriesToolSchema,
  },
  {
    name: 'github_get_file',
    description: 'Содержимое файла (или список файлов директории) в репозитории GitHub.',
    inputSchema: getFileToolSchema,
  },
];