import type { ProviderConfig, ProviderToolConfig } from '../../src/core/types.js';
import type { ProviderHealth, ToolDefinition } from '../../src/core/providers/types.js';
import { BaseProvider } from '../../src/core/providers/base-provider.js';
import { userError } from '../../src/core/errors.js';
import { GITHUB_TOOLS } from './tools.js';
import {
  GITHUB_BASE_URL,
  GITHUB_CONFIG_SCHEMA,
  GITHUB_TOKEN_ENV,
  GITHUB_VERSION_HEADER,
  getFileSchema,
  getIssueSchema,
  getRepositorySchema,
  listIssuesSchema,
  listPullRequestsSchema,
  searchRepositoriesSchema,
} from './schema.js';
import type { z } from 'zod';
import type { HttpLogContext } from '../../src/core/http/http-client.js';

interface GitHubErrorBody {
  message?: string;
  documentation_url?: string;
}

interface GitHubIssue {
  number?: number;
  title?: string;
  state?: string;
  body?: string | null;
  html_url?: string;
  created_at?: string;
  updated_at?: string;
  comments?: number;
  pull_request?: { url?: string } | null;
  user?: { login?: string } | null;
  assignees?: Array<{ login?: string }> | null;
  labels?: Array<{ name?: string }> | null;
  milestone?: { title?: string } | null;
}

interface GitHubRepo {
  full_name?: string;
  description?: string | null;
  default_branch?: string;
  language?: string | null;
  stargazers_count?: number;
  forks_count?: number;
  open_issues_count?: number;
  size?: number;
  topics?: string[];
  created_at?: string;
  updated_at?: string;
  html_url?: string;
  archived?: boolean;
  license?: { name?: string } | null;
  owner?: { login?: string } | null;
}

interface GitHubContentItem {
  name?: string;
  path?: string;
  type?: string;
  size?: number;
  content?: string;
  encoding?: string;
  sha?: string;
  html_url?: string;
  download_url?: string | null;
}

const MAX_FILE_CONTENT_CHARS = 200_000;

/**
 * GitHub Provider: GitHub REST API с Personal Access Token (опционально).
 * Работает с публичными endpoint'ами и без токена.
 */
export class GitHubProvider extends BaseProvider {
  constructor(http: ConstructorParameters<typeof BaseProvider>[0]['http']) {
    super({
      id: 'github',
      name: 'GitHub',
      description: 'GitHub REST API: repositories, issues, pull requests, search, file contents. Опциональный Personal Access Token.',
      version: '1.0.0',
      http,
      defaultBaseUrl: GITHUB_BASE_URL,
    });
  }

  override getConfigSchema() {
    return GITHUB_CONFIG_SCHEMA;
  }

  override getDefaultConfig(): ProviderConfig {
    return {
      id: this.id,
      enabled: true,
      name: this.name,
      baseUrl: this.defaultBaseUrl ?? GITHUB_BASE_URL,
      credentials: { token: '' },
      settings: { timeout: 10000 },
    };
  }

  override getCredentialEnv(): Record<string, string> {
    return { token: GITHUB_TOKEN_ENV };
  }

  getTools(): ToolDefinition[] {
    return GITHUB_TOOLS;
  }

  private get token(): string {
    return this.config.credentials?.token ?? '';
  }

  private get isAuthenticated(): boolean {
    return !!this.token;
  }

  private apiHeaders(): Record<string, string> {
    const headers: Record<string, string> = {
      accept: 'application/vnd.github+json',
      'x-github-api-version': GITHUB_VERSION_HEADER,
      'user-agent': 'mcp-gateway',
    };
    if (this.isAuthenticated) headers.authorization = `Bearer ${this.token}`;
    return headers;
  }

  private githubErrorExtractor = (status: number, body: unknown): string | null => {
    const msg = (body as GitHubErrorBody)?.message;
    if (msg) return `GitHub API returned HTTP ${status}: ${msg}`;
    return null;
  };

  private logCtx(tool: string, direction: 'mcp' | 'health' = 'mcp'): HttpLogContext {
    return { provider: this.id, providerName: this.name, tool, direction };
  }

  async healthCheck(): Promise<ProviderHealth> {
    try {
      const res = await this.http.get<{ resources?: { core?: { limit?: number; remaining?: number } } }>(this.url('/rate_limit'), {
        headers: this.apiHeaders(),
        timeoutMs: this.getTimeoutMs(),
        log: this.logCtx('health_check', 'health'),
      });
      const limit = res.data?.resources?.core?.limit;
      const authNote = this.isAuthenticated ? ` (authenticated, limit=${limit ?? '?'}/h)` : '';
      return this.health('ok', `Connected to GitHub API (HTTP ${res.status})${authNote}`, res.status);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      return this.health('error', message);
    }
  }

  async executeTool(toolName: string, input: unknown, _toolConfig: ProviderToolConfig): Promise<unknown> {
    switch (toolName) {
      case 'github_get_repository':
        return this.getRepository(input);
      case 'github_list_issues':
        return this.listIssues(input);
      case 'github_get_issue':
        return this.getIssue(input);
      case 'github_list_pull_requests':
        return this.listPullRequests(input);
      case 'github_search_repositories':
        return this.searchRepositories(input);
      case 'github_get_file':
        return this.getFile(input);
      default:
        throw userError(`Unknown tool: ${toolName}`, 'UNKNOWN_TOOL');
    }
  }

  private async getRepository(input: unknown): Promise<Record<string, unknown>> {
    const args = this.parse(getRepositorySchema, input);
    const res = await this.http.get<GitHubRepo>(this.url(`/repos/${encode(args.owner)}/${encode(args.repo)}`), {
      headers: this.apiHeaders(),
      timeoutMs: this.getTimeoutMs(),
      log: this.logCtx('github_get_repository'),
      errorMessageExtractor: this.githubErrorExtractor,
    });
    const repo = res.data;
    return {
      fullName: repo.full_name ?? `${args.owner}/${args.repo}`,
      description: repo.description ?? null,
      defaultBranch: repo.default_branch ?? null,
      language: repo.language ?? null,
      stars: repo.stargazers_count ?? 0,
      forks: repo.forks_count ?? 0,
      openIssues: repo.open_issues_count ?? 0,
      sizeKb: repo.size ?? 0,
      archived: repo.archived ?? false,
      license: repo.license?.name ?? null,
      owner: repo.owner?.login ?? args.owner,
      topics: repo.topics ?? [],
      createdAt: repo.created_at ?? null,
      updatedAt: repo.updated_at ?? null,
      htmlUrl: repo.html_url ?? null,
    };
  }

  private async listIssues(input: unknown): Promise<Record<string, unknown>> {
    const args = this.parse(listIssuesSchema, input);
    const res = await this.http.get<GitHubIssue[]>(this.url(`/repos/${encode(args.owner)}/${encode(args.repo)}/issues`), {
      query: { state: args.state ?? 'open', per_page: args.limit ?? 30, page: 1 },
      headers: this.apiHeaders(),
      timeoutMs: this.getTimeoutMs(),
      log: this.logCtx('github_list_issues'),
      errorMessageExtractor: this.githubErrorExtractor,
    });
    const items = res.data
      .filter((i) => args.includePullRequests || !i.pull_request)
      .map((i) => ({
        number: i.number ?? null,
        title: i.title ?? '',
        state: i.state ?? null,
        user: i.user?.login ?? null,
        labels: (i.labels ?? []).map((l) => l.name ?? '').filter(Boolean),
        comments: i.comments ?? 0,
        createdAt: i.created_at ?? null,
        updatedAt: i.updated_at ?? null,
        url: i.html_url ?? null,
      }));
    return { owner: args.owner, repo: args.repo, state: args.state ?? 'open', count: items.length, items };
  }

  private async getIssue(input: unknown): Promise<Record<string, unknown>> {
    const args = this.parse(getIssueSchema, input);
    const res = await this.http.get<GitHubIssue>(this.url(`/repos/${encode(args.owner)}/${encode(args.repo)}/issues/${args.issueNumber}`), {
      headers: this.apiHeaders(),
      timeoutMs: this.getTimeoutMs(),
      log: this.logCtx('github_get_issue'),
      errorMessageExtractor: this.githubErrorExtractor,
    });
    const i = res.data;
    return {
      number: i.number ?? args.issueNumber,
      title: i.title ?? '',
      state: i.state ?? null,
      user: i.user?.login ?? null,
      body: i.body ?? null,
      labels: (i.labels ?? []).map((l) => l.name ?? '').filter(Boolean),
      assignees: (i.assignees ?? []).map((a) => a.login ?? '').filter(Boolean),
      milestone: i.milestone?.title ?? null,
      comments: i.comments ?? 0,
      createdAt: i.created_at ?? null,
      updatedAt: i.updated_at ?? null,
      url: i.html_url ?? null,
      isPullRequest: !!i.pull_request,
    };
  }

  private async listPullRequests(input: unknown): Promise<Record<string, unknown>> {
    const args = this.parse(listPullRequestsSchema, input);
    const res = await this.http.get<GitHubIssue[]>(this.url(`/repos/${encode(args.owner)}/${encode(args.repo)}/pulls`), {
      query: { state: args.state ?? 'open', per_page: args.limit ?? 30, page: 1 },
      headers: this.apiHeaders(),
      timeoutMs: this.getTimeoutMs(),
      log: this.logCtx('github_list_pull_requests'),
      errorMessageExtractor: this.githubErrorExtractor,
    });
    const items = res.data.map((pr) => ({
      number: pr.number ?? null,
      title: pr.title ?? '',
      state: pr.state ?? null,
      user: pr.user?.login ?? null,
      createdAt: pr.created_at ?? null,
      updatedAt: pr.updated_at ?? null,
      url: pr.html_url ?? null,
    }));
    return { owner: args.owner, repo: args.repo, state: args.state ?? 'open', count: items.length, items };
  }

  private async searchRepositories(input: unknown): Promise<Record<string, unknown>> {
    const args = this.parse(searchRepositoriesSchema, input);
    const res = await this.http.get<{ total_count?: number; incomplete_results?: boolean; items?: GitHubRepo[] }>(
      this.url('/search/repositories'),
      {
        query: { q: args.query, per_page: args.limit ?? 10 },
        headers: this.apiHeaders(),
        timeoutMs: this.getTimeoutMs(),
        log: this.logCtx('github_search_repositories'),
        errorMessageExtractor: this.githubErrorExtractor,
      },
    );
    const data = res.data;
    const items = (data.items ?? []).map((repo) => ({
      fullName: repo.full_name ?? '',
      description: repo.description ?? null,
      stars: repo.stargazers_count ?? 0,
      language: repo.language ?? null,
      archived: repo.archived ?? false,
      url: repo.html_url ?? null,
    }));
    return { query: args.query, totalCount: data.total_count ?? items.length, incompleteResults: data.incomplete_results ?? false, items };
  }

  private async getFile(input: unknown): Promise<Record<string, unknown>> {
    const args = this.parse(getFileSchema, input);
    const res = await this.http.get<GitHubContentItem | GitHubContentItem[]>(
      this.url(`/repos/${encode(args.owner)}/${encode(args.repo)}/contents/${encodePath(args.path)}`),
      {
        query: args.ref ? { ref: args.ref } : undefined,
        headers: this.apiHeaders(),
        timeoutMs: this.getTimeoutMs(),
        log: this.logCtx('github_get_file'),
        errorMessageExtractor: this.githubErrorExtractor,
      },
    );

    if (Array.isArray(res.data)) {
      return {
        owner: args.owner,
        repo: args.repo,
        path: args.path,
        type: 'directory',
        entries: res.data.map((item) => ({
          name: item.name ?? '',
          type: item.type ?? 'file',
          size: item.size ?? 0,
          path: item.path ?? '',
        })),
      };
    }

    const file = res.data as GitHubContentItem;
    let content: string | null = null;
    let truncated = false;
    if (file.encoding === 'base64' && file.content) {
      try {
        const decoded = Buffer.from(file.content.replace(/\s+/g, ''), 'base64').toString('utf8');
        truncated = decoded.length > MAX_FILE_CONTENT_CHARS;
        content = truncated ? `${decoded.slice(0, MAX_FILE_CONTENT_CHARS)}\n[Content truncated]` : decoded;
      } catch {
        content = null;
      }
    }
    return {
      owner: args.owner,
      repo: args.repo,
      path: args.path,
      type: 'file',
      name: file.name ?? args.path,
      sha: file.sha ?? null,
      size: file.size ?? 0,
      content,
      truncated,
      htmlUrl: file.html_url ?? null,
      downloadUrl: file.download_url ?? null,
    };
  }

  private parse<T>(schema: z.ZodType<T>, input: unknown): T {
    const result = schema.safeParse(input);
    if (!result.success) {
      const issues = result.error.issues.map((i) => `${i.path.join('.') || 'input'}: ${i.message}`).join('; ');
      throw userError(`Invalid input: ${issues}`, 'INVALID_TOOL_INPUT', result.error.issues);
    }
    return result.data;
  }
}

function encode(value: string): string {
  return encodeURIComponent(value);
}

function encodePath(value: string): string {
  return value
    .split('/')
    .map((segment) => encodeURIComponent(segment))
    .join('/');
}