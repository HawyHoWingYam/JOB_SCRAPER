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
          pending_enrichment: 396,
        });
      }

      if (url.includes('/api/v1/ai/overview')) {
        return mockJsonResponse({
          failed_items: 7,
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
    expect(screen.getByText(/pending enrichment/i)).toBeInTheDocument();
    expect(screen.getByText(/failed items/i)).toBeInTheDocument();
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
    expect(screen.getByText(/pending enrichment/i)).toBeInTheDocument();
    expect(screen.getByText(/failed items unavailable/i)).toBeInTheDocument();
  });
});
