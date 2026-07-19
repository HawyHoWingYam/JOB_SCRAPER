import { render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import productFixture from '../fixtures/job_intelligence_product_surfaces.json';
import Dashboard from './Dashboard';

vi.mock('./charts/SkillChart', () => ({
  default: () => <div>Skill chart</div>,
}));

vi.mock('./charts/CategoryChart', () => ({
  default: () => <div>Canonical taxonomy chart</div>,
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

function jsonResponse(payload, status = 200) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? 'OK' : 'Service Unavailable',
    json: async () => payload,
  });
}

function installFetch({ governanceStatus = 200 } = {}) {
  globalThis.fetch = vi.fn((input) => {
    const url = String(input);
    if (url.includes('/stats/overview')) return jsonResponse(stats);
    if (url.includes('/ai/overview')) return jsonResponse(aiOverview);
    if (url.includes('/job-intelligence/governance/summary')) {
      return jsonResponse(
        governanceStatus === 200 ? productFixture.summary : { detail: 'offline' },
        governanceStatus,
      );
    }
    return Promise.reject(new Error(`Unhandled request: ${url}`));
  });
}

describe('Dashboard governed coverage', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders assigned, Unassigned, Unknown, reasons, and backend-owned backlog links', async () => {
    installFetch();
    render(<Dashboard onNavigateToAI={vi.fn()} />);

    const governance = await screen.findByRole('region', {
      name: 'Job Intelligence Governance',
    });
    expect(within(governance).getByText('7 of 12')).toBeInTheDocument();
    expect(within(governance).getByText('Unassigned')).toBeInTheDocument();
    expect(within(governance).getByText('2')).toBeInTheDocument();
    expect(within(governance).getByText('Unknown')).toBeInTheDocument();
    expect(within(governance).getByText('3')).toBeInTheDocument();
    expect(within(governance).getByText('Classifier provenance missing')).toBeInTheDocument();
    expect(within(governance).getByText('Unmapped source classification')).toBeInTheDocument();
    expect(within(governance).getByRole('link', { name: /Job Taxonomy Review\s+2 pending/i }))
      .toHaveAttribute('href', '#job-intelligence/job-taxonomy');
    expect(within(governance).getByRole('link', { name: /Skill Candidates\s+3 pending/i }))
      .toHaveAttribute('href', '#job-intelligence/skill-candidates');
    expect(within(governance).queryByRole('button', { name: /assign|accept|reject/i }))
      .not.toBeInTheDocument();
  });

  it('keeps the operational Dashboard usable when governance is unavailable', async () => {
    installFetch({ governanceStatus: 503 });
    render(<Dashboard onNavigateToAI={vi.fn()} />);

    expect(await screen.findByText('Total Jobs Acquired')).toBeInTheDocument();
    expect(screen.getByText(/Governance coverage is temporarily unavailable/i))
      .toBeInTheDocument();
    expect(screen.queryByText(/System Error: Failed to load data streams/i))
      .not.toBeInTheDocument();
  });
});
