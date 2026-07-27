import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import Dashboard from './Dashboard';

vi.mock('./charts/SkillChart', () => ({
  default: () => <div>Skill chart</div>,
}));

vi.mock('./charts/CategoryChart', () => ({
  default: () => <div>Job taxonomy chart</div>,
}));

const stats = {
  total_jobs: 12,
  enriched_jobs: 7,
  eligible_enriched_jobs: 7,
  pending_enrichment: 3,
  ai_eligible_jobs: 10,
  ineligible_jobs: 2,
};

const aiOverview = {
  active_runs: 0,
  failed_jobs: 0,
  last_completed_run: null,
};

function jsonResponse(payload) {
  return Promise.resolve({
    ok: true,
    status: 200,
    statusText: 'OK',
    json: async () => payload,
  });
}

function installFetch() {
  globalThis.fetch = vi.fn((input) => {
    const url = String(input);
    if (url.includes('/stats/overview')) return jsonResponse(stats);
    if (url.includes('/ai/overview')) return jsonResponse(aiOverview);
    return Promise.reject(new Error(`Unhandled request: ${url}`));
  });
}

describe('Dashboard', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders operational metrics without the retired Governance workspace', async () => {
    installFetch();
    render(<Dashboard onNavigateToAI={vi.fn()} />);

    expect(await screen.findByText('Total Jobs Acquired')).toBeInTheDocument();
    expect(screen.getByText('12')).toBeInTheDocument();
    expect(screen.getByText('Skill chart')).toBeInTheDocument();
    expect(screen.getByText('Job taxonomy chart')).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Job Intelligence Governance' }))
      .not.toBeInTheDocument();
    expect(globalThis.fetch).toHaveBeenCalledTimes(2);
  });
});
