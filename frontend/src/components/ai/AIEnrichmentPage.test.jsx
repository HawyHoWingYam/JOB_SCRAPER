import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import AIEnrichmentPage from './AIEnrichmentPage';

const overview = {
  pending_jobs: 396,
  ai_eligible_jobs: 400,
  active_runs: 1,
  failed_jobs: 7,
};

const activeRun = {
  id: 'run-active-4',
  source_type: 'post_scrape',
  status: 'running',
  created_at: '2026-07-18T12:10:00Z',
  started_at: '2026-07-18T12:10:00Z',
  total_items: 7,
  pending_items: 2,
  completed_items: 4,
  failed_items: 0,
  cancelled_items: 0,
  in_progress_items: 1,
  latest_started_job_title: 'Security Engineer',
};

const failedRun = {
  id: 'run-failed-3',
  source_type: 'manual_pending',
  status: 'completed_with_failures',
  created_at: '2026-07-18T12:00:00Z',
  completed_at: '2026-07-18T12:05:00Z',
  total_items: 5,
  pending_items: 0,
  completed_items: 3,
  failed_items: 2,
  cancelled_items: 0,
  last_failed_job_title: 'Platform Analyst',
};

const completedRun = {
  ...failedRun,
  id: 'run-completed-2',
  status: 'completed',
  created_at: '2026-07-18T11:00:00Z',
  completed_items: 5,
  failed_items: 0,
};

const excludedRun = {
  ...completedRun,
  id: 'run-excluded-1',
  status: 'completed_with_exclusions',
  total_items: 4,
  completed_items: 2,
  excluded_items: 2,
  excluded_details: [
    {
      source_classification_id: 'offertoday:113000',
      source_classification_name: 'Farming',
      count: 2,
      reason: 'No defensible internal taxonomy domain is available for this OfferToday source category.',
    },
  ],
};

const sourceQualifiedFilterOptions = {
  sources: [
    {
      source_site: 'jobsdb',
      classification_paths: [
        {
          nodes: [
            { id: 'jobsdb:6281', name: 'Information Technology', source_position: 0 },
            { id: 'jobsdb:6287', name: 'Security', source_position: 1 },
          ],
        },
      ],
      classifications: [
        {
          id: 'jobsdb:6281',
          source_site: 'jobsdb',
          name: 'Information Technology',
          subclassifications: ['Security'],
          subclassification_options: [
            {
              id: 'jobsdb:6287',
              source_site: 'jobsdb',
              name: 'Security',
              breadcrumb: 'Information Technology / Security',
            },
          ],
        },
      ],
    },
    {
      source_site: 'ctgoodjobs',
      classification_paths: [
        {
          nodes: [
            { id: 'ctgoodjobs:021', name: 'Information Technology', source_position: 0 },
            { id: 'ctgoodjobs:022', name: 'Security', source_position: 1 },
          ],
        },
      ],
      classifications: [
        {
          id: 'ctgoodjobs:021',
          source_site: 'ctgoodjobs',
          name: 'Information Technology',
          subclassifications: ['Security'],
          subclassification_options: [
            {
              id: 'ctgoodjobs:022',
              source_site: 'ctgoodjobs',
              name: 'Security',
              breadcrumb: 'Information Technology / Security',
            },
          ],
        },
      ],
    },
  ],
};

function jsonResponse(payload, status = 200) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  });
}

function installFetch({
  overviewPayload = overview,
  runs = [activeRun, failedRun],
  previewCount = 12,
  filterOptions = null,
} = {}) {
  globalThis.fetch = vi.fn((input, init = {}) => {
    const url = String(input);
    if (url.includes('/ai/pending/filter-options')) {
      return jsonResponse(filterOptions || {
        sources: [
          {
            source_site: 'jobsdb',
            classifications: [
              { name: 'Information Technology', subclassifications: ['Software Engineering', 'Security'] },
            ],
          },
          {
            source_site: 'ctgoodjobs',
            classifications: [
              { name: 'Information Technology', subclassifications: ['Software Engineering'] },
            ],
          },
        ],
      });
    }
    if (url.includes('/ai/pending/preview')) {
      return jsonResponse({ matching_pending_count: previewCount, effective_item_count: Math.min(previewCount, 50) });
    }
    if (url.includes('/ai/overview')) {
      return jsonResponse(overviewPayload);
    }
    if (url.includes('/retry-failed')) {
      return jsonResponse({ ...activeRun, id: 'retry-run', status: 'pending' });
    }
    if (url.endsWith('/stop')) {
      return jsonResponse({ ...activeRun, status: 'stopping' });
    }
    if (url.includes('/ai/runs') && init.method === 'POST') {
      return jsonResponse({ ...activeRun, id: 'filtered-run', status: 'pending' });
    }
    if (url.includes('/ai/runs')) {
      return jsonResponse({ runs });
    }
    return Promise.reject(new Error(`Unhandled fetch: ${url}`));
  });
}

describe('AIEnrichmentPage', () => {
  beforeEach(() => {
    window.localStorage.clear();
    Object.defineProperty(document, 'hidden', { configurable: true, value: false });
    installFetch();
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    Object.defineProperty(window.navigator, 'clipboard', {
      configurable: true,
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('renders the compact metrics, monitoring-first panels, and no single-job controls', async () => {
    render(<AIEnrichmentPage />);

    const summary = await screen.findByLabelText('AI enrichment summary');
    expect(within(summary).getByText('Pending / eligible')).toBeInTheDocument();
    expect(within(summary).getByText('396 / 400')).toBeInTheDocument();
    expect(within(summary).getByText('Active runs')).toBeInTheDocument();
    expect(within(summary).getByText('Failed jobs')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Run Monitor' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Filtered Run' })).toBeInTheDocument();
    expect(screen.queryByText(/target job uuid/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /run job/i })).not.toBeInTheDocument();
  });

  it('shows exactly active plus latest terminal monitor slots', async () => {
    render(<AIEnrichmentPage />);
    const cards = await screen.findAllByTestId('run-monitor-card');
    expect(cards).toHaveLength(2);
    expect(within(cards[0]).getByText('run-active-4')).toBeInTheDocument();
    expect(within(cards[1]).getByText('run-failed-3')).toBeInTheDocument();
  });

  it('keeps partial bootstrap truthful when one console request times out', async () => {
    vi.useFakeTimers();
    globalThis.fetch = vi.fn((input) => {
      const url = String(input);
      if (url.includes('/ai/pending/filter-options')) {
        return jsonResponse({ sources: [] });
      }
      if (url.includes('/ai/overview')) {
        return new Promise(() => {});
      }
      if (url.includes('/ai/runs')) {
        return jsonResponse({ runs: [] });
      }
      return Promise.reject(new Error(`Unhandled fetch: ${url}`));
    });

    render(<AIEnrichmentPage />);
    await act(async () => {
      await Promise.resolve();
      await vi.advanceTimersByTimeAsync(8000);
      await Promise.resolve();
    });

    expect(screen.getByText(/Refresh failed: Overview request timed out after 8000ms/)).toBeInTheDocument();
    expect(screen.getByText('Unavailable / Unavailable')).toBeInTheDocument();
    expect(screen.getAllByText('Unavailable')).toHaveLength(2);
    expect(screen.getAllByTestId('run-monitor-card')).toHaveLength(2);
  });

  it('does not fabricate queue metrics when both bootstrap requests fail', async () => {
    vi.useFakeTimers();
    globalThis.fetch = vi.fn((input) => {
      const url = String(input);
      if (url.includes('/ai/pending/filter-options')) {
        return jsonResponse({ sources: [] });
      }
      return Promise.reject(new Error('bootstrap unavailable'));
    });

    render(<AIEnrichmentPage />);
    await act(async () => {
      await Promise.resolve();
      await vi.advanceTimersByTimeAsync(8000);
      await Promise.resolve();
    });

    expect(screen.getByText(/Failed to load AI operations data: bootstrap unavailable/)).toBeInTheDocument();
    expect(screen.queryByLabelText('AI enrichment summary')).not.toBeInTheDocument();
    expect(screen.queryByText('0 / 0')).not.toBeInTheDocument();
  });

  it('shows the latest two terminal runs when there is no active run', async () => {
    installFetch({ overviewPayload: { ...overview, active_runs: 0 }, runs: [failedRun, completedRun] });
    render(<AIEnrichmentPage />);
    const cards = await screen.findAllByTestId('run-monitor-card');
    expect(within(cards[0]).getByText('run-failed-3')).toBeInTheDocument();
    expect(within(cards[1]).getByText('run-completed-2')).toBeInTheDocument();
  });

  it('shows exclusions as a terminal outcome and keeps them out of retry actions', async () => {
    installFetch({ overviewPayload: { ...overview, active_runs: 0 }, runs: [excludedRun] });
    render(<AIEnrichmentPage />);

    const card = within((await screen.findAllByTestId('run-monitor-card'))[0]);
    expect(card.getByText('completed_with_exclusions')).toBeInTheDocument();
    expect(card.getAllByText('Excluded 2')).toHaveLength(2);
    expect(card.getByText(/Farming \(offertoday:113000\)/)).toBeInTheDocument();
    expect(card.getByText(/No defensible internal taxonomy domain/)).toBeInTheDocument();
    expect(card.getByRole('link', { name: 'Review 2 excluded jobs' }))
      .toHaveAttribute('href', '#job-intelligence/job-taxonomy?source_site=offertoday');
    expect(card.queryByRole('button', { name: /Retry failed/i })).not.toBeInTheDocument();
    expect(card.queryByRole('button', { name: /assign|accept|reject/i })).not.toBeInTheDocument();
  });

  it('renders empty placeholders to keep exactly two slots', async () => {
    installFetch({ overviewPayload: { ...overview, active_runs: 0 }, runs: [] });
    render(<AIEnrichmentPage />);
    expect(await screen.findAllByTestId('run-monitor-card')).toHaveLength(2);
    expect(screen.getAllByText('No persisted run available yet.')).toHaveLength(2);
  });

  it('previews filters and submits the normalized filtered pending payload', async () => {
    installFetch({ overviewPayload: { ...overview, active_runs: 0 }, runs: [completedRun] });
    const user = userEvent.setup();
    render(<AIEnrichmentPage />);

    await user.click(await screen.findByLabelText('jobsdb'));
    await waitFor(() => expect(screen.getByText('12 match · 12 will run')).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: 'Run 12 filtered jobs' }));

    const createCall = globalThis.fetch.mock.calls.find(([url, init]) => String(url).includes('/ai/runs') && init?.method === 'POST');
    expect(JSON.parse(createCall[1].body)).toMatchObject({
      mode: 'pending',
      limit: 50,
      filters: { source_sites: ['jobsdb'] },
      all_pending_acknowledged: false,
    });
  });

  it('submits source-qualified path IDs when different Sources reuse a label', async () => {
    installFetch({
      overviewPayload: { ...overview, active_runs: 0 },
      runs: [completedRun],
      filterOptions: sourceQualifiedFilterOptions,
    });
    const user = userEvent.setup();
    render(<AIEnrichmentPage />);

    await user.click(await screen.findByLabelText(
      'jobsdb · Information Technology (jobsdb:6281)',
    ));

    await waitFor(() => {
      const previewCall = globalThis.fetch.mock.calls
        .filter(([url]) => String(url).includes('/ai/pending/preview'))
        .at(-1);
      expect(JSON.parse(previewCall[1].body).filters).toMatchObject({
        source_classification_ids: ['jobsdb:6281'],
        source_subclassification_ids: [],
      });
    });
    expect(screen.getByLabelText(
      'ctgoodjobs · Information Technology (ctgoodjobs:021)',
    )).not.toBeChecked();
  });

  it('requires ephemeral acknowledgement and confirmation for an all-pending run', async () => {
    installFetch({ overviewPayload: { ...overview, active_runs: 0 }, runs: [completedRun] });
    const user = userEvent.setup();
    render(<AIEnrichmentPage />);

    expect(await screen.findByRole('button', { name: 'Run 0 filtered jobs' })).toBeDisabled();
    await user.click(screen.getByText(/I understand this will select/i));
    await waitFor(() => expect(screen.getByText('12 match · 12 will run')).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: 'Run 12 filtered jobs' }));
    expect(window.confirm).toHaveBeenCalledOnce();
    expect(JSON.parse(window.localStorage.getItem('ai-enrichment-filtered-run:v2'))).not.toHaveProperty('all_pending_acknowledged');
  });

  it('persists ordinary filters and Reset clears them', async () => {
    installFetch({ overviewPayload: { ...overview, active_runs: 0 }, runs: [completedRun] });
    const user = userEvent.setup();
    const { unmount } = render(<AIEnrichmentPage />);
    await user.click(await screen.findByLabelText('jobsdb'));
    await waitFor(() => expect(JSON.parse(window.localStorage.getItem('ai-enrichment-filtered-run:v2')).filters.source_sites).toEqual(['jobsdb']));
    unmount();

    render(<AIEnrichmentPage />);
    expect(await screen.findByLabelText('jobsdb')).toBeChecked();
    await user.click(screen.getByRole('button', { name: 'Reset' }));
    expect(screen.getByLabelText('jobsdb')).not.toBeChecked();
    expect(window.localStorage.getItem('ai-enrichment-filtered-run:v2')).toBeNull();
    expect(window.localStorage.getItem('ai-enrichment-filtered-run:v1')).toBeNull();
  });

  it('migrates safe v1 fields and clears ambiguous name-based path filters', async () => {
    window.localStorage.setItem('ai-enrichment-filtered-run:v1', JSON.stringify({
      filters: {
        source_sites: ['jobsdb', 'ctgoodjobs'],
        source_classification_names: ['Information Technology'],
        source_subclassification_names: ['Security'],
        posted_date_from: '2026-07-01',
      },
      limit: 75,
    }));
    installFetch({
      overviewPayload: { ...overview, active_runs: 0 },
      runs: [completedRun],
      filterOptions: sourceQualifiedFilterOptions,
    });

    render(<AIEnrichmentPage />);

    expect(await screen.findByText(/saved name-based Source Classification filters were cleared/i))
      .toBeInTheDocument();
    await waitFor(() => {
      const migrated = JSON.parse(
        window.localStorage.getItem('ai-enrichment-filtered-run:v2'),
      );
      expect(migrated).toMatchObject({
        filters: {
          source_sites: ['jobsdb', 'ctgoodjobs'],
          source_classification_ids: [],
          source_subclassification_ids: [],
          posted_date_from: '2026-07-01',
        },
        limit: 75,
      });
    });
    expect(window.localStorage.getItem('ai-enrichment-filtered-run:v1')).toBeNull();
  });

  it('stops an active run from its card and renders stopping as active', async () => {
    const user = userEvent.setup();
    render(<AIEnrichmentPage />);
    await user.click(await screen.findByRole('button', { name: 'Stop' }));
    expect(globalThis.fetch).toHaveBeenCalledWith('/api/v1/ai/runs/run-active-4/stop', { method: 'POST' });

    installFetch({ runs: [{ ...activeRun, status: 'stopping' }, failedRun] });
    render(<AIEnrichmentPage />);
    expect(await screen.findByRole('button', { name: /Stopping/i })).toBeDisabled();
    expect(screen.getByText('No new jobs will start.')).toBeInTheDocument();
  });

  it('retries failed items inline only when the active slot is free', async () => {
    installFetch({ overviewPayload: { ...overview, active_runs: 0 }, runs: [failedRun, completedRun] });
    const user = userEvent.setup();
    render(<AIEnrichmentPage />);
    await user.click(await screen.findByRole('button', { name: /Retry failed/i }));
    expect(globalThis.fetch).toHaveBeenCalledWith('/api/v1/ai/runs/run-failed-3/retry-failed', { method: 'POST' });
  });

  it('copies the visible run UUID for debugging', async () => {
    const user = userEvent.setup();
    render(<AIEnrichmentPage />);
    await user.click(await screen.findByRole('button', { name: 'Copy run UUID run-active-4' }));
    expect(await screen.findByText('Copied run UUID run-active-4.')).toBeInTheDocument();
  });

  it('polls while a run is active and pauses once the page is hidden', async () => {
    vi.useFakeTimers();
    render(<AIEnrichmentPage />);
    await act(async () => Promise.resolve());
    const initialOverviewCalls = globalThis.fetch.mock.calls.filter(([url]) => String(url).includes('/ai/overview')).length;
    await act(async () => { await vi.advanceTimersByTimeAsync(2100); });
    expect(globalThis.fetch.mock.calls.filter(([url]) => String(url).includes('/ai/overview')).length).toBeGreaterThan(initialOverviewCalls);

    await act(async () => {
      Object.defineProperty(document, 'hidden', { configurable: true, value: true });
      document.dispatchEvent(new Event('visibilitychange'));
      await Promise.resolve();
    });
    const hiddenCallCount = globalThis.fetch.mock.calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(2500); });
    expect(globalThis.fetch).toHaveBeenCalledTimes(hiddenCallCount);
  });
});
