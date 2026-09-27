import { describe, expect, it, afterEach } from 'vitest';
import { AppError } from '../src/core/errors.js';
import { createHarness } from './helpers.js';
import type { Harness } from './helpers.js';

let harness: Harness | undefined;
afterEach(() => harness?.cleanup());

const repoPayload = {
  full_name: 'torvalds/linux',
  description: 'Linux kernel source tree',
  default_branch: 'master',
  language: 'C',
  stargazers_count: 100_000,
  forks_count: 30_000,
  open_issues_count: 42,
  size: 400_000,
  archived: false,
  license: { name: 'GPL-2.0' },
  owner: { login: 'torvalds' },
  topics: ['kernel', 'linux'],
  created_at: '2011-07-21T20:13:57Z',
  updated_at: '2026-09-20T10:00:00Z',
  html_url: 'https://github.com/torvalds/linux',
};

function githubHarness(onFetch: (url: string, init?: RequestInit) => Response, token = ''): Harness {
  return createHarness({
    providerConfigs: {
      github: { id: 'github', enabled: true, credentials: { token }, settings: { timeout: 5000 } },
    },
    onFetch,
  });
}

describe('GitHub provider', () => {
  it('sends Authorization: Bearer when token is configured', async () => {
    const captured: Array<RequestInit | undefined> = [];
    harness = githubHarness((_url, init) => {
      captured.push(init);
      return new Response(JSON.stringify(repoPayload), { status: 200 });
    }, 'ghp_testtoken_1234567890');
    await harness.registry.loadProviders();
    await harness.registry.initializeAll();

    const result = await harness.registry.executeTool('github_get_repository', { owner: 'torvalds', repo: 'linux' });
    expect((result as Record<string, unknown>).fullName).toBe('torvalds/linux');
    expect(captured[0]?.headers).toBeDefined();
    const headers = captured[0]?.headers as Record<string, string>;
    expect(headers.authorization).toBe('Bearer ghp_testtoken_1234567890');
    expect(headers['x-github-api-version']).toBe('2022-11-28');
  });

  it('does not send Authorization header without a token', async () => {
    const captured: Array<RequestInit | undefined> = [];
    harness = githubHarness((_url, init) => {
      captured.push(init);
      return new Response(JSON.stringify(repoPayload), { status: 200 });
    });
    await harness.registry.loadProviders();
    await harness.registry.initializeAll();

    await harness.registry.executeTool('github_get_repository', { owner: 'torvalds', repo: 'linux' });
    const headers = captured[0]?.headers as Record<string, string>;
    expect(headers.authorization).toBeUndefined();
  });

  it('parses repository response', async () => {
    harness = githubHarness(() => new Response(JSON.stringify(repoPayload), { status: 200 }));
    await harness.registry.loadProviders();
    await harness.registry.initializeAll();

    const result = (await harness.registry.executeTool('github_get_repository', { owner: 'torvalds', repo: 'linux' })) as Record<string, unknown>;
    expect(result.fullName).toBe('torvalds/linux');
    expect(result.stars).toBe(100_000);
    expect(result.license).toBe('GPL-2.0');
    expect(result.defaultBranch).toBe('master');
  });

  it('maps 404 to an external error with readable message', async () => {
    harness = githubHarness(() => new Response(JSON.stringify({ message: 'Not Found', documentation_url: '...' }), { status: 404 }));
    await harness.registry.loadProviders();
    await harness.registry.initializeAll();

    const err = await harness.registry
      .executeTool('github_get_repository', { owner: 'torvalds', repo: 'linux-missing' })
      .then(() => undefined)
      .catch((e: AppError) => e);
    expect(err?.kind).toBe('external');
    expect(err?.status).toBe(404);
    expect(err?.message.toLowerCase()).toContain('404');
    expect(err?.message).toContain('Not Found');
    expect(err?.message).not.toContain('stack');
  });

  it('maps 429 + Retry-After to a rate limit error', async () => {
    harness = githubHarness(
      () => new Response(JSON.stringify({ message: 'API rate limit exceeded' }), { status: 429, headers: { 'retry-after': '60' } }),
      'ghp_token',
    );
    await harness.registry.loadProviders();
    await harness.registry.initializeAll();

    const err = await harness.registry
      .executeTool('github_list_issues', { owner: 'torvalds', repo: 'linux' })
      .then(() => undefined)
      .catch((e: AppError) => e);
    expect(err?.kind).toBe('rate_limit');
    expect(err?.status).toBe(429);
    expect(err?.retryAfter).toBe(60);
    expect(err?.message).toContain('Retry after 60s');
  });

  it('maps 401 to an authentication error', async () => {
    harness = githubHarness(() => new Response(JSON.stringify({ message: 'Bad credentials' }), { status: 401 }), 'ghp_badtoken');
    await harness.registry.loadProviders();
    await harness.registry.initializeAll();

    const err = await harness.registry
      .executeTool('github_get_repository', { owner: 'torvalds', repo: 'linux' })
      .then(() => undefined)
      .catch((e: AppError) => e);
    expect(err?.kind).toBe('auth');
  });

  it('lists issues without pull requests by default', async () => {
    const payload = [
      { number: 1, title: 'issue one', state: 'open', pull_request: { url: '...' }, user: { login: 'a' }, labels: [{ name: 'bug' }] },
      { number: 2, title: 'issue two', state: 'open', user: { login: 'b' }, labels: [] },
    ];
    harness = githubHarness(() => new Response(JSON.stringify(payload), { status: 200 }));
    await harness.registry.loadProviders();
    await harness.registry.initializeAll();

    const result = (await harness.registry.executeTool('github_list_issues', { owner: 'torvalds', repo: 'linux' })) as { items: Array<{ number: number }> };
    expect(result.items).toHaveLength(1);
    expect(result.items[0].number).toBe(2);
  });

  it('decodes base64 file contents', async () => {
    const content = Buffer.from('# Hello\n').toString('base64');
    harness = githubHarness(() =>
      new Response(JSON.stringify({ name: 'README.md', path: 'README.md', type: 'file', encoding: 'base64', content, sha: 'abc', size: 8, html_url: 'https://github.com/x/y' }), { status: 200 }),
    );
    await harness.registry.loadProviders();
    await harness.registry.initializeAll();

    const result = (await harness.registry.executeTool('github_get_file', { owner: 'torvalds', repo: 'linux', path: 'README.md' })) as {
      content: string;
      type: string;
    };
    expect(result.type).toBe('file');
    expect(result.content).toContain('# Hello');
  });

  it('validates tool inputs (missing owner)', async () => {
    harness = githubHarness(() => new Response('{}', { status: 200 }));
    await harness.registry.loadProviders();
    await harness.registry.initializeAll();
    await expect(harness.registry.executeTool('github_get_repository', { repo: 'linux' })).rejects.toMatchObject({
      kind: 'user',
    });
  });
});