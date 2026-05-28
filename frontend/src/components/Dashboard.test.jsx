import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('./charts/SkillChart', () => ({
  default: () => <div>Skill Chart Stub</div>,
}));

vi.mock('./charts/CategoryChart', () => ({
  default: () => <div>Category Chart Stub</div>,
}));

import Dashboard from './Dashboard';

function mockJsonResponse(payload) {
  return Promise.resolve({
    ok: true,
    json: async () => payload,
  });
}

describe('Dashboard', () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn((input) => {
      const url = String(input);

      if (url.includes('/api/v1/stats/overview')) {
        return mockJsonResponse({
          total_jobs: 400,
          enriched_jobs: 4,
          eligible_enriched_jobs: 4,
          ai_eligible_jobs: 400,
          ineligible_jobs: 0,
          pending_enrichment: 396,
        });
      }

      if (url.includes('/api/v1/ai/overview')) {
        return mockJsonResponse({
          failed_jobs: 7,
          failed_items: 11820,
        });
      }

      if (url.includes('/api/v1/stats/skills')) {
        return mockJsonResponse({ skills: [] });
      }

      if (url.includes('/api/v1/stats/categories')) {
        return mockJsonResponse([]);
      }

      return Promise.reject(new Error(`Unhandled fetch: ${url}`));
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('shows summary-only AI status and links into the AI Enrichment console', async () => {
    const onNavigateToAI = vi.fn();
    const user = userEvent.setup();

    render(<Dashboard onNavigateToAI={onNavigateToAI} />);

    expect(await screen.findByText('396')).toBeInTheDocument();
    expect(screen.getByText(/pending ai-eligible jobs/i)).toBeInTheDocument();
    expect(screen.getByText(/failed jobs/i)).toBeInTheDocument();
    expect(screen.queryByText('11,820')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /run pending/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /retry failed/i })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /open ai enrichment/i }));

    expect(onNavigateToAI).toHaveBeenCalledTimes(1);
  });

  it('keeps the core dashboard visible when ai overview is temporarily unavailable', async () => {
    globalThis.fetch = vi.fn((input) => {
      const url = String(input);

      if (url.includes('/api/v1/stats/overview')) {
        return mockJsonResponse({
          total_jobs: 400,
          enriched_jobs: 4,
          eligible_enriched_jobs: 4,
          ai_eligible_jobs: 400,
          ineligible_jobs: 0,
          pending_enrichment: 396,
        });
      }

      if (url.includes('/api/v1/ai/overview')) {
        return Promise.resolve({
          ok: false,
          status: 503,
          statusText: 'Service Unavailable',
          json: async () => ({}),
        });
      }

      if (url.includes('/api/v1/stats/skills')) {
        return mockJsonResponse({ skills: [] });
      }

      if (url.includes('/api/v1/stats/categories')) {
        return mockJsonResponse([]);
      }

      return Promise.reject(new Error(`Unhandled fetch: ${url}`));
    });

    render(<Dashboard onNavigateToAI={vi.fn()} />);

    expect(await screen.findByText('396')).toBeInTheDocument();
    expect(screen.getByText(/pending ai-eligible jobs/i)).toBeInTheDocument();
    expect(screen.getByText(/failed jobs unavailable/i)).toBeInTheDocument();
  });

  it('shows active run count from ai overview even when those runs are still pending', async () => {
    globalThis.fetch = vi.fn((input) => {
      const url = String(input);

      if (url.includes('/api/v1/stats/overview')) {
        return mockJsonResponse({
          total_jobs: 400,
          enriched_jobs: 5,
          eligible_enriched_jobs: 4,
          ai_eligible_jobs: 115,
          ineligible_jobs: 285,
          pending_enrichment: 111,
        });
      }

      if (url.includes('/api/v1/ai/overview')) {
        return mockJsonResponse({
          active_runs: 2,
          running_runs: 0,
          failed_jobs: 0,
          failed_items: 0,
          last_completed_run: { id: 'run-complete-9' },
        });
      }

      if (url.includes('/api/v1/stats/skills')) {
        return mockJsonResponse({ skills: [] });
      }

      if (url.includes('/api/v1/stats/categories')) {
        return mockJsonResponse([]);
      }

      return Promise.reject(new Error(`Unhandled fetch: ${url}`));
    });

    render(<Dashboard onNavigateToAI={vi.fn()} />);

    expect(await screen.findByText('111')).toBeInTheDocument();
    expect(screen.getByText('3%')).toBeInTheDocument();
    expect(screen.getByText('97%')).toBeInTheDocument();
    expect(screen.getByText(/4 of 115 ai-eligible jobs enriched/i)).toBeInTheDocument();
    expect(screen.getByText(/111 ai-eligible jobs are staged for ai processing/i)).toBeInTheDocument();
    expect(screen.getByText(/285 acquired jobs are not in the ai queue yet/i)).toBeInTheDocument();
    expect(screen.getByText(/^4$/)).toBeInTheDocument();
    expect(screen.getByText(/active runs/i)).toBeInTheDocument();
    expect(screen.getByText(/^2$/)).toBeInTheDocument();
    expect(screen.queryByText(/running runs/i)).not.toBeInTheDocument();
  });

  it('falls back to eligible_enriched_jobs when ai_eligible_jobs is absent from stats overview', async () => {
    globalThis.fetch = vi.fn((input) => {
      const url = String(input);

      if (url.includes('/api/v1/stats/overview')) {
        return mockJsonResponse({
          total_jobs: 400,
          enriched_jobs: 5,
          eligible_enriched_jobs: 4,
          ineligible_jobs: 285,
          pending_enrichment: 111,
        });
      }

      if (url.includes('/api/v1/ai/overview')) {
        return mockJsonResponse({
          active_runs: 2,
          running_runs: 0,
          failed_jobs: 0,
          failed_items: 0,
          last_completed_run: { id: 'run-complete-9' },
        });
      }

      if (url.includes('/api/v1/stats/skills')) {
        return mockJsonResponse({ skills: [] });
      }

      if (url.includes('/api/v1/stats/categories')) {
        return mockJsonResponse([]);
      }

      return Promise.reject(new Error(`Unhandled fetch: ${url}`));
    });

    render(<Dashboard onNavigateToAI={vi.fn()} />);

    expect(await screen.findByText('111')).toBeInTheDocument();
    expect(screen.getByText('3%')).toBeInTheDocument();
    expect(screen.getByText(/4 of 115 ai-eligible jobs enriched/i)).toBeInTheDocument();
    expect(screen.getByText(/ai-eligible jobs enriched/i, { selector: '.stat-label' })).toBeInTheDocument();
    expect(screen.getByText(/pending ai-eligible jobs/i)).toBeInTheDocument();
  });

  it('shows N/A percentages when the current dataset has no AI-eligible jobs', async () => {
    globalThis.fetch = vi.fn((input) => {
      const url = String(input);

      if (url.includes('/api/v1/stats/overview')) {
        return mockJsonResponse({
          total_jobs: 285,
          enriched_jobs: 0,
          eligible_enriched_jobs: 0,
          ai_eligible_jobs: 0,
          ineligible_jobs: 285,
          pending_enrichment: 0,
        });
      }

      if (url.includes('/api/v1/ai/overview')) {
        return mockJsonResponse({
          active_runs: 0,
          failed_jobs: 0,
          failed_items: 0,
          last_completed_run: null,
        });
      }

      if (url.includes('/api/v1/stats/skills')) {
        return mockJsonResponse({ skills: [] });
      }

      if (url.includes('/api/v1/stats/categories')) {
        return mockJsonResponse([]);
      }

      return Promise.reject(new Error(`Unhandled fetch: ${url}`));
    });

    render(<Dashboard onNavigateToAI={vi.fn()} />);

    expect(await screen.findByText('285')).toBeInTheDocument();
    expect(screen.getAllByText('N/A').length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText(/no ai-eligible jobs are in the current dataset/i)).toBeInTheDocument();
    expect(screen.getByText(/285 acquired jobs are not in the ai queue yet/i)).toBeInTheDocument();
  });
});
