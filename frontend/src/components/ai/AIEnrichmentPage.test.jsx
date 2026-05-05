import { StrictMode } from 'react';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../charts/SkillChart', () => ({
  default: () => <div>Skill Chart Stub</div>,
}));

vi.mock('../charts/CategoryChart', () => ({
  default: () => <div>Category Chart Stub</div>,
}));

import App from '../../App';
import AIEnrichmentPage from './AIEnrichmentPage';

function mockJsonResponse(payload) {
  return Promise.resolve({
    ok: true,
    json: async () => payload,
  });
}

function mockDelayedJsonResponse(payload, delayMs) {
  return Promise.resolve({
    ok: true,
    json: () =>
      new Promise((resolve) => {
        setTimeout(() => resolve(payload), delayMs);
      }),
  });
}

function mockNeverSettlingJsonResponse() {
  return Promise.resolve({
    ok: true,
    json: () => new Promise(() => {}),
  });
}

describe('AIEnrichmentPage', () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn((input, init = {}) => {
      const url = String(input);

      if (url.includes('/api/v1/stats/overview')) {
        return mockJsonResponse({
          total_jobs: 400,
          enriched_jobs: 4,
          pending_enrichment: 396,
        });
      }

      if (url.includes('/api/v1/stats/skills')) {
        return mockJsonResponse({ skills: [] });
      }

      if (url.includes('/api/v1/stats/categories')) {
        return mockJsonResponse([]);
      }

      if (url.includes('/api/v1/ai/overview')) {
        return mockJsonResponse({
          total_jobs: 400,
          enriched_jobs: 4,
          pending_jobs: 396,
          active_runs: 2,
          failed_jobs: 7,
          failed_items: 11820,
          last_completed_run: { id: 'run-complete-7' },
        });
      }

      if (url.includes('/api/v1/ai/runs')) {
        if (init.method === 'POST' && url.includes('/retry-failed')) {
          return mockJsonResponse({
            id: 'retry-run-1',
            source_type: 'manual_retry',
            status: 'pending',
          });
        }

        if (init.method === 'POST') {
          return mockJsonResponse({
            id: 'pending-run-1',
            source_type: 'manual_pending',
            status: 'pending',
          });
        }

        return mockJsonResponse({
          runs: [
            {
              id: 'run-active-4',
              source_type: 'post_scrape',
              status: 'running',
              created_at: '2026-04-15T12:10:00Z',
              started_at: '2026-04-15T12:10:00Z',
              total_items: 7,
              pending_items: 2,
              completed_items: 4,
              failed_items: 1,
              current_job_title: 'Security Engineer',
              in_progress_items: 2,
              latest_started_job_title: 'Security Engineer',
            },
            {
              id: 'run-terminal-3',
              source_type: 'manual_pending',
              status: 'completed',
              created_at: '2026-04-15T12:00:00Z',
              started_at: '2026-04-15T12:00:00Z',
              completed_at: '2026-04-15T12:05:00Z',
              total_items: 5,
              pending_items: 0,
              completed_items: 5,
              failed_items: 0,
            },
            {
              id: 'run-terminal-2',
              source_type: 'manual_pending',
              status: 'completed_with_failures',
              created_at: '2026-04-15T11:00:00Z',
              started_at: '2026-04-15T11:00:00Z',
              completed_at: '2026-04-15T11:07:00Z',
              total_items: 3,
              pending_items: 0,
              completed_items: 1,
              failed_items: 2,
              last_failed_job_title: 'Platform Analyst',
            },
            {
              id: 'run-terminal-1',
              source_type: 'post_scrape',
              status: 'failed',
              created_at: '2026-04-15T10:00:00Z',
              started_at: '2026-04-15T10:00:00Z',
              completed_at: '2026-04-15T10:02:30Z',
              total_items: 2,
              pending_items: 0,
              completed_items: 0,
              failed_items: 2,
              last_failed_job_title: 'Senior ML Engineer',
            },
            {
              id: 'run-hidden-older-0',
              source_type: 'manual_pending',
              status: 'completed',
              created_at: '2026-04-15T09:00:00Z',
              started_at: '2026-04-15T09:00:00Z',
              completed_at: '2026-04-15T09:01:00Z',
              total_items: 6,
              pending_items: 0,
              completed_items: 6,
              failed_items: 0,
            },
            {
              id: 'run-hidden-older-1',
              source_type: 'manual_pending',
              status: 'completed',
              created_at: '2026-04-15T08:00:00Z',
              started_at: '2026-04-15T08:00:00Z',
              completed_at: '2026-04-15T08:01:00Z',
              total_items: 2,
              pending_items: 0,
              completed_items: 2,
              failed_items: 0,
            },
          ],
        });
      }

      return Promise.reject(new Error(`Unhandled fetch: ${url}`));
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('shows the AI Enrichment sidebar entry and renders the page shell with queue overview data', async () => {
    const user = userEvent.setup();

    render(<App />);

    const aiNavButton = screen.getByRole('button', { name: /ai enrichment/i });
    expect(aiNavButton).toBeInTheDocument();

    await user.click(aiNavButton);

    expect(await screen.findByRole('heading', { name: /ai enrichment/i })).toBeInTheDocument();
    expect(await screen.findByText('396')).toBeInTheDocument();
    expect(screen.getByText(/pending jobs/i)).toBeInTheDocument();
    expect(screen.getByText(/active runs/i, { selector: '.stat-label' })).toBeInTheDocument();
    expect(screen.getAllByText(/failed jobs/i).length).toBeGreaterThan(0);
    expect(screen.queryByText('11,820')).not.toBeInTheDocument();
  });

  it('loads queue data inside StrictMode without getting stuck in the loading state', async () => {
    render(
      <StrictMode>
        <AIEnrichmentPage />
      </StrictMode>,
    );

    await waitFor(() => {
      expect(screen.getByText('396')).toBeInTheDocument();
    });

    expect(screen.queryByText(/loading enrichment queue/i)).not.toBeInTheDocument();
  });

  it('shows the active run count from overview.active_runs instead of the monitor slice', async () => {
    globalThis.fetch = vi.fn((input) => {
      const url = String(input);

      if (url.includes('/api/v1/ai/overview')) {
        return mockJsonResponse({
          total_jobs: 400,
          enriched_jobs: 4,
          pending_jobs: 396,
          active_runs: 7,
          failed_items: 0,
          last_completed_run: null,
        });
      }

      if (url.includes('/api/v1/ai/runs') && !url.includes('/items')) {
        return mockJsonResponse({
          runs: [
            {
              id: 'run-active-pending',
              source_type: 'manual_pending',
              status: 'pending',
              created_at: '2026-04-15T12:00:00Z',
              started_at: '2026-04-15T12:00:00Z',
              total_items: 2,
              pending_items: 2,
              completed_items: 0,
              failed_items: 0,
              current_job_title: 'Title A',
            },
            {
              id: 'run-terminal',
              source_type: 'post_scrape',
              status: 'completed',
              created_at: '2026-04-15T11:00:00Z',
              started_at: '2026-04-15T11:00:00Z',
              completed_at: '2026-04-15T11:03:00Z',
              total_items: 1,
              pending_items: 0,
              completed_items: 1,
              failed_items: 0,
            },
          ],
        });
      }

      return Promise.reject(new Error(`Unhandled fetch: ${url}`));
    });

    render(<AIEnrichmentPage />);

    expect(await screen.findByText(/run-active-pending/i)).toBeInTheDocument();

    const activeRunsSummaryLabel = screen.getByText(/active runs/i, { selector: '.stat-label' });
    const activeRunsSummaryCard = activeRunsSummaryLabel.closest('article');
    expect(activeRunsSummaryCard).not.toBeNull();
    expect(within(activeRunsSummaryCard).getByText('7')).toBeInTheDocument();

    const activeRunsRibbonLabel = screen.getByText(/active runs/i, { selector: '.ai-ribbon-label' });
    const ribbonBlock = activeRunsRibbonLabel.closest('div');
    expect(ribbonBlock).not.toBeNull();
    expect(within(ribbonBlock).getByText(/7\s*runs/i)).toBeInTheDocument();
  });

  it('renders the 2-slot run monitor from mocked API data', async () => {
    render(<AIEnrichmentPage />);

    expect(await screen.findByText('396')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /run pending/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /retry failed/i })).toBeInTheDocument();
    const cards = await screen.findAllByTestId('run-monitor-card');
    expect(cards).toHaveLength(2);
    expect(cards[0]).toHaveTextContent('run-active-4');
    expect(cards[1]).toHaveTextContent('run-terminal-3');
    expect(cards[0]).not.toHaveTextContent('run-terminal-2');
    expect(cards[1]).not.toHaveTextContent('run-terminal-2');
    expect(screen.queryByText('run-terminal-1')).not.toBeInTheDocument();
    expect(screen.queryByText('run-hidden-older-0')).not.toBeInTheDocument();
    expect(screen.queryByText('run-hidden-older-1')).not.toBeInTheDocument();
    expect(screen.queryByText(/failure workbench/i)).not.toBeInTheDocument();
  });

  it('requests the backend-provided monitor slice', async () => {
    render(<AIEnrichmentPage />);

    expect(await screen.findByText('run-active-4')).toBeInTheDocument();
    expect(
      globalThis.fetch.mock.calls.some(
        ([input, init]) => String(input).includes('/api/v1/ai/runs?monitor=true') && init === undefined,
      ),
    ).toBe(true);
  });

  it('renders hidden-active ordering from the backend-provided monitor slice', async () => {
    globalThis.fetch = vi.fn((input) => {
      const url = String(input);

      if (url.includes('/api/v1/ai/overview')) {
        return mockJsonResponse({
          total_jobs: 400,
          enriched_jobs: 4,
          pending_jobs: 396,
          active_runs: 3,
          failed_items: 0,
          last_completed_run: null,
        });
      }

      if (url.includes('/api/v1/ai/runs') && !url.includes('/items')) {
        return mockJsonResponse({
          runs: [
            {
              id: 'run-active-slice-newest',
              source_type: 'post_scrape',
              status: 'running',
              created_at: '2026-04-15T12:10:00Z',
              started_at: '2026-04-15T12:10:00Z',
              total_items: 10,
              pending_items: 8,
              completed_items: 2,
              failed_items: 0,
              current_job_title: 'Newest Slice Title',
            },
            {
              id: 'run-active-slice-previous',
              source_type: 'manual_pending',
              status: 'pending',
              created_at: '2026-04-15T12:05:00Z',
              started_at: '2026-04-15T12:05:00Z',
              total_items: 4,
              pending_items: 4,
              completed_items: 0,
              failed_items: 0,
              current_job_title: 'Previous Slice Title',
            },
          ],
        });
      }

      return Promise.reject(new Error(`Unhandled fetch: ${url}`));
    });

    render(<AIEnrichmentPage />);

    const cards = await screen.findAllByTestId('run-monitor-card');
    expect(cards).toHaveLength(2);
    expect(cards[0]).toHaveTextContent('Current Run');
    expect(cards[0]).toHaveTextContent('run-active-slice-newest');
    expect(cards[1]).toHaveTextContent('Previous Run');
    expect(cards[1]).toHaveTextContent('run-active-slice-previous');

    const activeRunsSummaryLabel = screen.getByText(/active runs/i, { selector: '.stat-label' });
    const activeRunsSummaryCard = activeRunsSummaryLabel.closest('article');
    expect(activeRunsSummaryCard).not.toBeNull();
    expect(within(activeRunsSummaryCard).getByText('3')).toBeInTheDocument();
  });

  it('submits the configured limit when running pending enrichment', async () => {
    const user = userEvent.setup();
    render(<AIEnrichmentPage />);

    const limitInput = await screen.findByLabelText(/pending limit/i);
    await user.clear(limitInput);
    await user.type(limitInput, '25');
    await user.click(screen.getByRole('button', { name: /run pending/i }));

    expect(globalThis.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/v1/ai/runs'),
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ mode: 'pending', limit: 25 }),
      }),
    );
  });

  it('hides the retry target when no visible monitor slot is retryable', async () => {
    render(<AIEnrichmentPage />);

    expect(await screen.findByText('run-active-4')).toBeInTheDocument();
    expect(screen.queryByText(/retry target/i)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /retry failed/i })).toBeDisabled();
    expect(screen.queryByText('run-terminal-2')).not.toBeInTheDocument();
  });

  it('retries a failed run only when that run is visible in the 2-slot monitor', async () => {
    const user = userEvent.setup();

    globalThis.fetch = vi.fn((input, init = {}) => {
      const url = String(input);

      if (url.includes('/api/v1/ai/overview')) {
        return mockJsonResponse({
          total_jobs: 400,
          enriched_jobs: 4,
          pending_jobs: 396,
          active_runs: 1,
          failed_items: 2,
          last_completed_run: { id: 'run-completed-latest' },
        });
      }

      if (url.includes('/api/v1/ai/runs') && init.method === 'POST' && url.includes('/retry-failed')) {
        return mockJsonResponse({
          id: 'retry-run-1',
          source_type: 'manual_retry',
          status: 'pending',
        });
      }

      if (url.includes('/api/v1/ai/runs') && !url.includes('/items')) {
        return mockJsonResponse({
          runs: [
            {
              id: 'run-completed-latest',
              source_type: 'manual_pending',
              status: 'completed',
              created_at: '2026-04-15T12:00:00Z',
              started_at: '2026-04-15T12:00:00Z',
              completed_at: '2026-04-15T12:03:00Z',
              total_items: 3,
              pending_items: 0,
              completed_items: 3,
              failed_items: 0,
            },
            {
              id: 'run-failed-visible',
              source_type: 'post_scrape',
              status: 'completed_with_failures',
              created_at: '2026-04-15T11:00:00Z',
              started_at: '2026-04-15T11:00:00Z',
              completed_at: '2026-04-15T11:08:00Z',
              total_items: 4,
              pending_items: 0,
              completed_items: 2,
              failed_items: 2,
              last_failed_job_title: 'Staff Data Engineer',
            },
            {
              id: 'run-hidden-failed',
              source_type: 'manual_pending',
              status: 'failed',
              created_at: '2026-04-15T10:00:00Z',
              started_at: '2026-04-15T10:00:00Z',
              completed_at: '2026-04-15T10:02:00Z',
              total_items: 2,
              pending_items: 0,
              completed_items: 0,
              failed_items: 2,
            },
          ],
        });
      }

      return Promise.reject(new Error(`Unhandled fetch: ${url}`));
    });

    render(<AIEnrichmentPage />);

    const cards = await screen.findAllByTestId('run-monitor-card');
    expect(cards[1]).toHaveTextContent('run-failed-visible');
    expect(screen.getByText(/retry target/i)).toBeInTheDocument();
    expect(screen.getByText('run-failed-visible', { selector: '.ai-retry-target strong' })).toBeInTheDocument();
    expect(screen.queryByText('run-hidden-failed')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /retry failed/i }));

    expect(globalThis.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/v1/ai/runs/run-failed-visible/retry-failed'),
      expect.objectContaining({
        method: 'POST',
      }),
    );
  });

  it('clamps invalid pending limits before creating a manual run', async () => {
    const user = userEvent.setup();
    render(<AIEnrichmentPage />);

    const limitInput = await screen.findByLabelText(/pending limit/i);
    await user.clear(limitInput);
    await user.type(limitInput, '0');
    await user.click(screen.getByRole('button', { name: /run pending/i }));

    expect(globalThis.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/v1/ai/runs'),
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ mode: 'pending', limit: 1 }),
      }),
    );
  });

  it('shows the operator details required by the design', async () => {
    render(<AIEnrichmentPage />);

    expect(await screen.findByText(/auto-chain runs after scrape persistence/i)).toBeInTheDocument();
    expect(screen.getByText(/run-complete-7/i)).toBeInTheDocument();
    expect(screen.getAllByText(/processed/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/succeeded/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/^Jobs in progress$/i)).toBeInTheDocument();
    expect(screen.getByText(/^2 jobs in progress$/i)).toBeInTheDocument();
    expect(screen.getByText(/latest title:/i)).toBeInTheDocument();
    expect(screen.getByText(/security engineer/i)).toBeInTheDocument();
  });

  it('queues a guaranteed post-action reload even when a poll refresh is already in flight', async () => {
    let runCalls = 0;

    globalThis.fetch = vi.fn((input, init = {}) => {
      const url = String(input);

      if (url.includes('/api/v1/ai/overview')) {
        return mockJsonResponse({
          total_jobs: 400,
          enriched_jobs: 4,
          pending_jobs: 396,
          active_runs: 1,
          failed_items: 0,
          last_completed_run: null,
        });
      }

      if (url.includes('/api/v1/ai/runs') && init.method === 'POST') {
        return mockJsonResponse({
          id: 'pending-run-1',
          source_type: 'manual_pending',
          status: 'pending',
        });
      }

      if (url.includes('/api/v1/ai/runs') && !url.includes('/items')) {
        runCalls += 1;

        if (runCalls === 1) {
          return mockJsonResponse({
            runs: [
              {
                id: 'run-existing',
                source_type: 'post_scrape',
                status: 'running',
                total_items: 4,
                pending_items: 4,
                completed_items: 0,
                failed_items: 0,
                current_job_title: 'Title A',
                created_at: '2026-04-15T12:00:00Z',
                started_at: '2026-04-15T12:00:00Z',
              },
            ],
          });
        }

        if (runCalls === 2) {
          // In-flight poll refresh that completes after the poll interval.
          return mockDelayedJsonResponse(
            {
              runs: [
                {
                  id: 'run-existing',
                  source_type: 'post_scrape',
                  status: 'running',
                  total_items: 4,
                  pending_items: 4,
                  completed_items: 0,
                  failed_items: 0,
                  current_job_title: 'Title A',
                  created_at: '2026-04-15T12:00:00Z',
                  started_at: '2026-04-15T12:00:00Z',
                },
              ],
            },
            3100,
          );
        }

        // Fresh reload after the action finishes should include the new run.
        return mockJsonResponse({
          runs: [
            {
              id: 'pending-run-1',
              source_type: 'manual_pending',
              status: 'pending',
              total_items: 1,
              pending_items: 1,
              completed_items: 0,
              failed_items: 0,
              current_job_title: 'New Run Title',
              created_at: '2026-04-15T12:05:00Z',
              started_at: '2026-04-15T12:05:00Z',
            },
            {
              id: 'run-existing',
              source_type: 'post_scrape',
              status: 'running',
              total_items: 4,
              pending_items: 4,
              completed_items: 0,
              failed_items: 0,
              current_job_title: 'Title A',
              created_at: '2026-04-15T12:00:00Z',
              started_at: '2026-04-15T12:00:00Z',
            },
          ],
        });
      }

      return Promise.reject(new Error(`Unhandled fetch: ${url}`));
    });

    vi.useFakeTimers();
    render(<AIEnrichmentPage />);

    await act(async () => Promise.resolve());
    expect(screen.getByText(/run-existing/i)).toBeInTheDocument();
    expect(runCalls).toBe(1);

    await act(async () => {
      vi.advanceTimersByTime(2100);
    });
    await act(async () => Promise.resolve());
    expect(runCalls).toBe(2);

    await act(async () => {
      screen.getByRole('button', { name: /run pending/i }).click();
    });

    await act(async () => {
      vi.advanceTimersByTime(3100);
    });
    await act(async () => Promise.resolve());

    expect(runCalls).toBe(3);
    expect(screen.getByText(/pending-run-1/i)).toBeInTheDocument();
  });

  it('times out a hung refresh so a queued manual follow-up refresh can still proceed', async () => {
    let overviewCalls = 0;
    let runCalls = 0;

    globalThis.fetch = vi.fn((input, init = {}) => {
      const url = String(input);

      if (url.includes('/api/v1/ai/overview')) {
        overviewCalls += 1;

        if (overviewCalls === 2) {
          return mockNeverSettlingJsonResponse();
        }

        return mockJsonResponse({
          total_jobs: 400,
          enriched_jobs: 4,
          pending_jobs: 396,
          active_runs: 1,
          failed_items: 0,
          last_completed_run: null,
        });
      }

      if (url.includes('/api/v1/ai/runs') && init.method === 'POST') {
        return mockJsonResponse({
          id: 'pending-run-1',
          source_type: 'manual_pending',
          status: 'pending',
        });
      }

      if (url.includes('/api/v1/ai/runs') && !url.includes('/items')) {
        runCalls += 1;

        if (runCalls < 3) {
          return mockJsonResponse({
            runs: [
              {
                id: 'run-existing',
                source_type: 'manual_pending',
                status: 'pending',
                created_at: '2026-04-15T12:00:00Z',
                started_at: '2026-04-15T12:00:00Z',
                total_items: 4,
                pending_items: 4,
                completed_items: 0,
                failed_items: 0,
                current_job_title: 'Title A',
              },
            ],
          });
        }

        return mockJsonResponse({
          runs: [
            {
              id: 'pending-run-1',
              source_type: 'manual_pending',
              status: 'pending',
              created_at: '2026-04-15T12:05:00Z',
              started_at: '2026-04-15T12:05:00Z',
              total_items: 1,
              pending_items: 1,
              completed_items: 0,
              failed_items: 0,
              current_job_title: 'New Run Title',
            },
            {
              id: 'run-existing',
              source_type: 'manual_pending',
              status: 'pending',
              created_at: '2026-04-15T12:00:00Z',
              started_at: '2026-04-15T12:00:00Z',
              total_items: 4,
              pending_items: 4,
              completed_items: 0,
              failed_items: 0,
              current_job_title: 'Title A',
            },
          ],
        });
      }

      return Promise.reject(new Error(`Unhandled fetch: ${url}`));
    });

    vi.useFakeTimers();
    render(<AIEnrichmentPage />);

    await act(async () => Promise.resolve());
    expect(screen.getByText(/run-existing/i)).toBeInTheDocument();
    expect(overviewCalls).toBe(1);
    expect(runCalls).toBe(1);

    await act(async () => {
      vi.advanceTimersByTime(2100);
    });
    await act(async () => Promise.resolve());

    expect(overviewCalls).toBe(2);
    expect(runCalls).toBe(2);

    await act(async () => {
      screen.getByRole('button', { name: /run pending/i }).click();
    });

    await act(async () => {
      vi.advanceTimersByTime(9000);
    });
    await act(async () => Promise.resolve());

    expect(overviewCalls).toBe(3);
    expect(runCalls).toBe(3);
    expect(screen.getByText(/pending-run-1/i)).toBeInTheDocument();
  });

  it('updates runs even when overview refresh fails so the monitor can keep advancing', async () => {
    let overviewCalls = 0;
    let runCalls = 0;

    globalThis.fetch = vi.fn((input) => {
      const url = String(input);

      if (url.includes('/api/v1/ai/overview')) {
        overviewCalls += 1;
        if (overviewCalls === 1) {
          return mockJsonResponse({
            total_jobs: 400,
            enriched_jobs: 4,
            pending_jobs: 396,
            active_runs: 1,
            failed_items: 0,
            last_completed_run: null,
          });
        }

        return Promise.resolve({ ok: false, status: 500, json: async () => ({}) });
      }

      if (url.includes('/api/v1/ai/runs') && !url.includes('/items')) {
        runCalls += 1;
        const runTitle = runCalls < 2 ? 'Title A' : 'Title B';
        const completedItems = runCalls < 2 ? 0 : 2;
        return mockJsonResponse({
          runs: [
            {
              id: 'run-pending',
              source_type: 'manual_pending',
              status: 'pending',
              total_items: 4,
              pending_items: Math.max(0, 4 - completedItems),
              completed_items: completedItems,
              failed_items: 0,
              current_job_title: runTitle,
              created_at: '2026-04-15T12:00:00Z',
              started_at: '2026-04-15T12:00:00Z',
            },
          ],
        });
      }

      return Promise.reject(new Error(`Unhandled fetch: ${url}`));
    });

    vi.useFakeTimers();
    render(<AIEnrichmentPage />);

    await act(async () => Promise.resolve());
    expect(screen.getByText(/title a/i)).toBeInTheDocument();
    expect(screen.getByRole('progressbar', { name: /current run progress/i })).toHaveAttribute(
      'aria-valuenow',
      '0',
    );

    await act(async () => {
      vi.advanceTimersByTime(2100);
    });
    await act(async () => Promise.resolve());

    expect(overviewCalls).toBe(2);
    expect(runCalls).toBe(2);
    expect(screen.getByText(/refresh failed/i)).toBeInTheDocument();
    expect(screen.getByText(/title b/i)).toBeInTheDocument();
    expect(screen.getByRole('progressbar', { name: /current run progress/i })).toHaveAttribute(
      'aria-valuenow',
      '50',
    );
  });

  it('selects the newest active run as Current Run and the immediately previous run as Previous Run, even when both are active', async () => {
    globalThis.fetch = vi.fn((input) => {
      const url = String(input);

      if (url.includes('/api/v1/ai/overview')) {
        return mockJsonResponse({
          total_jobs: 400,
          enriched_jobs: 4,
          pending_jobs: 396,
          active_runs: 2,
          failed_items: 0,
          last_completed_run: null,
        });
      }

      if (url.includes('/api/v1/ai/runs') && !url.includes('/items')) {
        return mockJsonResponse({
          runs: [
            {
              id: 'run-active-newest',
              source_type: 'post_scrape',
              status: 'running',
              created_at: '2026-04-15T12:10:00Z',
              started_at: '2026-04-15T12:10:00Z',
              total_items: 10,
              pending_items: 8,
              completed_items: 2,
              failed_items: 0,
              current_job_title: 'Newest Title',
            },
            {
              id: 'run-active-previous',
              source_type: 'manual_pending',
              status: 'pending',
              created_at: '2026-04-15T12:05:00Z',
              started_at: '2026-04-15T12:05:00Z',
              total_items: 4,
              pending_items: 4,
              completed_items: 0,
              failed_items: 0,
              current_job_title: 'Previous Title',
            },
            {
              id: 'run-terminal-older',
              source_type: 'manual_pending',
              status: 'completed',
              created_at: '2026-04-15T12:00:00Z',
              started_at: '2026-04-15T12:00:00Z',
              completed_at: '2026-04-15T12:01:00Z',
              total_items: 1,
              pending_items: 0,
              completed_items: 1,
              failed_items: 0,
            },
          ],
        });
      }

      return Promise.reject(new Error(`Unhandled fetch: ${url}`));
    });

    render(<AIEnrichmentPage />);

    const cards = await screen.findAllByTestId('run-monitor-card');
    expect(cards).toHaveLength(2);
    expect(cards[0]).toHaveTextContent('Current Run');
    expect(cards[0]).toHaveTextContent('run-active-newest');
    expect(cards[1]).toHaveTextContent('Previous Run');
    expect(cards[1]).toHaveTextContent('run-active-previous');
    expect(cards[0]).not.toHaveTextContent('run-terminal-older');
    expect(cards[1]).not.toHaveTextContent('run-terminal-older');
  });

  it('serializes polling refreshes when refresh responses are slower than the poll interval', async () => {
    let runCalls = 0;

    globalThis.fetch = vi.fn((input) => {
      const url = String(input);

      if (url.includes('/api/v1/ai/overview')) {
        return mockJsonResponse({
          total_jobs: 400,
          enriched_jobs: 4,
          pending_jobs: 396,
          active_runs: 1,
          failed_items: 0,
          last_completed_run: null,
        });
      }

      if (url.includes('/api/v1/ai/runs') && !url.includes('/items')) {
        runCalls += 1;

        if (runCalls === 1) {
          return mockJsonResponse({
            runs: [
              {
                id: 'run-pending',
                source_type: 'manual_pending',
                status: 'pending',
                total_items: 4,
                pending_items: 4,
                completed_items: 0,
                failed_items: 0,
                current_job_title: 'Title A',
                created_at: '2026-04-15T12:00:00Z',
                started_at: '2026-04-15T12:00:00Z',
              },
            ],
          });
        }

        if (runCalls === 2) {
          return mockDelayedJsonResponse(
            {
              runs: [
                {
                  id: 'run-pending',
                  source_type: 'manual_pending',
                  status: 'pending',
                  total_items: 4,
                  pending_items: 3,
                  completed_items: 1,
                  failed_items: 0,
                  current_job_title: 'Title B',
                  created_at: '2026-04-15T12:00:00Z',
                  started_at: '2026-04-15T12:00:00Z',
                },
              ],
            },
            3100,
          );
        }

        return mockJsonResponse({
          runs: [
            {
              id: 'run-pending',
              source_type: 'manual_pending',
              status: 'pending',
              total_items: 4,
              pending_items: 2,
              completed_items: 2,
              failed_items: 0,
              current_job_title: 'Title C',
              created_at: '2026-04-15T12:00:00Z',
              started_at: '2026-04-15T12:00:00Z',
            },
          ],
        });
      }

      return Promise.reject(new Error(`Unhandled fetch: ${url}`));
    });

    vi.useFakeTimers();
    render(<AIEnrichmentPage />);

    await act(async () => Promise.resolve());
    expect(screen.getByText(/title a/i)).toBeInTheDocument();
    expect(runCalls).toBe(1);

    await act(async () => {
      vi.advanceTimersByTime(2100);
    });
    await act(async () => Promise.resolve());
    expect(runCalls).toBe(2);

    await act(async () => {
      vi.advanceTimersByTime(2100);
    });
    await act(async () => Promise.resolve());

    // Under serialized polling, the third refresh should not start while the second is still pending.
    expect(runCalls).toBe(2);

    await act(async () => {
      vi.advanceTimersByTime(3100);
    });
    await act(async () => Promise.resolve());
    expect(screen.getByText(/title b/i)).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(2100);
    });
    await act(async () => Promise.resolve());
    expect(runCalls).toBe(3);
    expect(screen.getByText(/title c/i)).toBeInTheDocument();
  });

  it('preserves already-loaded console data on refresh failures and continues polling active runs', async () => {
    let overviewCalls = 0;
    let runCalls = 0;

    globalThis.fetch = vi.fn((input) => {
      const url = String(input);

      if (url.includes('/api/v1/ai/overview')) {
        overviewCalls += 1;
        return mockJsonResponse({
          total_jobs: 400,
          enriched_jobs: 4,
          pending_jobs: 396,
          active_runs: 1,
          failed_items: 0,
          last_completed_run: null,
        });
      }

      if (url.includes('/api/v1/ai/runs') && !url.includes('/items')) {
        runCalls += 1;

        if (runCalls === 2) {
          return Promise.resolve({ ok: false, status: 500, json: async () => ({}) });
        }

        const runTitle = runCalls < 3 ? 'Title A' : 'Title B';
        const completedItems = runCalls < 3 ? 0 : 2;
        return mockJsonResponse({
          runs: [
            {
              id: 'run-pending',
              source_type: 'manual_pending',
              status: 'pending',
              total_items: 4,
              pending_items: Math.max(0, 4 - completedItems),
              completed_items: completedItems,
              failed_items: 0,
              current_job_title: runTitle,
              created_at: '2026-04-15T12:00:00Z',
              started_at: '2026-04-15T12:00:00Z',
            },
          ],
        });
      }

      return Promise.reject(new Error(`Unhandled fetch: ${url}`));
    });

    vi.useFakeTimers();
    render(<AIEnrichmentPage />);

    await act(async () => Promise.resolve());
    expect(screen.getByText(/run-pending/i)).toBeInTheDocument();
    expect(overviewCalls).toBe(1);
    expect(runCalls).toBe(1);
    expect(screen.getByText(/title a/i)).toBeInTheDocument();
    expect(screen.getByRole('progressbar', { name: /current run progress/i })).toHaveAttribute(
      'aria-valuenow',
      '0',
    );

    const [currentRunCardBefore] = screen.getAllByTestId('run-monitor-card');
    expect(within(currentRunCardBefore).getByText(/processed 0/i)).toBeInTheDocument();
    expect(within(currentRunCardBefore).getByText(/succeeded 0/i)).toBeInTheDocument();
    expect(within(currentRunCardBefore).getByText(/failed 0/i)).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(2100);
    });

    expect(overviewCalls).toBeGreaterThan(1);
    expect(runCalls).toBe(2);
    expect(screen.getByText(/run-pending/i)).toBeInTheDocument();
    expect(screen.getByText(/title a/i)).toBeInTheDocument();
    expect(screen.getByText(/refresh failed/i)).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(2100);
    });
    await act(async () => Promise.resolve());

    expect(runCalls).toBe(3);
    expect(screen.queryByText(/refresh failed/i)).not.toBeInTheDocument();
    expect(screen.getByText(/title b/i)).toBeInTheDocument();
    expect(screen.getByRole('progressbar', { name: /current run progress/i })).toHaveAttribute(
      'aria-valuenow',
      '50',
    );

    const [currentRunCardAfter] = screen.getAllByTestId('run-monitor-card');
    expect(within(currentRunCardAfter).getByText(/processed 2/i)).toBeInTheDocument();
    expect(within(currentRunCardAfter).getByText(/succeeded 2/i)).toBeInTheDocument();
    expect(within(currentRunCardAfter).getByText(/failed 0/i)).toBeInTheDocument();
  }, 8000);

  it('renders the latest two terminal runs when no active run exists and shows richer terminal detail', async () => {
    globalThis.fetch = vi.fn((input) => {
      const url = String(input);

      if (url.includes('/api/v1/ai/overview')) {
        return mockJsonResponse({
          total_jobs: 400,
          enriched_jobs: 4,
          pending_jobs: 396,
          active_runs: 0,
          failed_items: 4,
          last_completed_run: null,
        });
      }

      if (url.includes('/api/v1/ai/runs') && !url.includes('/items')) {
        return mockJsonResponse({
          runs: [
            {
              id: 'run-completed-latest',
              source_type: 'manual_pending',
              status: 'completed',
              created_at: '2026-04-15T12:00:00Z',
              started_at: '2026-04-15T12:00:00Z',
              completed_at: '2026-04-15T12:03:00Z',
              total_items: 3,
              pending_items: 0,
              completed_items: 3,
              failed_items: 0,
            },
            {
              id: 'run-failed-prev',
              source_type: 'post_scrape',
              status: 'completed_with_failures',
              created_at: '2026-04-15T11:00:00Z',
              started_at: '2026-04-15T11:00:00Z',
              completed_at: '2026-04-15T11:08:00Z',
              total_items: 4,
              pending_items: 0,
              completed_items: 2,
              failed_items: 2,
              last_failed_job_title: 'Staff Data Engineer',
            },
            {
              id: 'run-older-hidden',
              source_type: 'manual_pending',
              status: 'failed',
              created_at: '2026-04-15T10:00:00Z',
              started_at: '2026-04-15T10:00:00Z',
              completed_at: '2026-04-15T10:02:00Z',
              total_items: 2,
              pending_items: 0,
              completed_items: 0,
              failed_items: 2,
            },
          ],
        });
      }

      return Promise.reject(new Error(`Unhandled fetch: ${url}`));
    });

    render(<AIEnrichmentPage />);

    const cards = await screen.findAllByTestId('run-monitor-card');
    expect(cards).toHaveLength(2);
    expect(cards[0]).toHaveTextContent('run-completed-latest');
    expect(cards[1]).toHaveTextContent('run-failed-prev');
    expect(screen.queryByText('run-older-hidden')).not.toBeInTheDocument();
    expect(screen.getByText(/completed at/i)).toBeInTheDocument();
    expect(screen.getByText(/duration/i)).toBeInTheDocument();
    expect(screen.getAllByText(/failure count/i).length).toBeGreaterThan(0);
    expect(cards[1]).toHaveTextContent(/last failed/i);
    expect(screen.getByText(/staff data engineer/i)).toBeInTheDocument();
    expect(screen.getByText(/retry available via queue controls/i)).toBeInTheDocument();
  });

  it('shows backend failure detail on terminal failure cards', async () => {
    globalThis.fetch = vi.fn((input) => {
      const url = String(input);

      if (url.includes('/api/v1/ai/overview')) {
        return mockJsonResponse({
          total_jobs: 400,
          enriched_jobs: 4,
          pending_jobs: 396,
          active_runs: 0,
          failed_items: 1,
          last_completed_run: null,
        });
      }

      if (url.includes('/api/v1/ai/runs') && !url.includes('/items')) {
        return mockJsonResponse({
          runs: [
            {
              id: 'run-failed-restart',
              source_type: 'manual_pending',
              status: 'failed',
              created_at: '2026-04-15T12:00:00Z',
              started_at: '2026-04-15T12:00:00Z',
              completed_at: '2026-04-15T12:01:00Z',
              total_items: 1,
              pending_items: 0,
              completed_items: 0,
              failed_items: 1,
              last_failed_job_title: 'Platform Engineer',
              error_message: 'Service restarted before AI enrichment run could finish.',
            },
          ],
        });
      }

      return Promise.reject(new Error(`Unhandled fetch: ${url}`));
    });

    render(<AIEnrichmentPage />);

    expect(await screen.findAllByText(/run-failed-restart/i)).toHaveLength(2);
    expect(screen.getByText(/service restarted before ai enrichment run could finish\./i)).toBeInTheDocument();
  });

  it('keeps the console usable on initial load when overview fails but runs succeed', async () => {
    globalThis.fetch = vi.fn((input) => {
      const url = String(input);

      if (url.includes('/api/v1/ai/overview')) {
        return Promise.resolve({ ok: false, status: 500, json: async () => ({}) });
      }

      if (url.includes('/api/v1/ai/runs') && !url.includes('/items')) {
        return mockJsonResponse({
          runs: [
            {
              id: 'run-initial-partial',
              source_type: 'post_scrape',
              status: 'running',
              created_at: '2026-04-15T12:10:00Z',
              started_at: '2026-04-15T12:10:00Z',
              total_items: 5,
              pending_items: 4,
              completed_items: 1,
              failed_items: 0,
              current_job_title: 'Recovered Title',
            },
          ],
        });
      }

      return Promise.reject(new Error(`Unhandled fetch: ${url}`));
    });

    render(<AIEnrichmentPage />);

    expect(await screen.findByText(/run-initial-partial/i)).toBeInTheDocument();
    expect(screen.getByText(/refresh failed/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /run pending/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /retry failed/i })).toBeInTheDocument();
    expect(screen.getByText(/recovered title/i)).toBeInTheDocument();
    const lastCompletedBlock = screen.getByText(/last completed/i).closest('div');
    expect(lastCompletedBlock).not.toBeNull();
    expect(within(lastCompletedBlock).getByText(/^unavailable$/i)).toBeInTheDocument();

    const pendingJobsLabel = screen.getByText(/pending jobs/i, { selector: '.stat-label' });
    const pendingJobsCard = pendingJobsLabel.closest('article');
    expect(pendingJobsCard).not.toBeNull();
    expect(within(pendingJobsCard).getByText(/^unavailable$/i)).toBeInTheDocument();

    const failedItemsLabel = screen.getByText(/failed jobs/i, { selector: '.stat-label' });
    const failedItemsCard = failedItemsLabel.closest('article');
    expect(failedItemsCard).not.toBeNull();
    expect(within(failedItemsCard).getByText(/^unavailable$/i)).toBeInTheDocument();

    const activeRunsLabel = screen.getByText(/active runs/i, { selector: '.stat-label' });
    const activeRunsCard = activeRunsLabel.closest('article');
    expect(activeRunsCard).not.toBeNull();
    expect(within(activeRunsCard).getByText(/^unavailable$/i)).toBeInTheDocument();

    const backlogWindowBlock = screen.getByText(/backlog window/i, { selector: '.ai-ribbon-label' }).closest('div');
    expect(backlogWindowBlock).not.toBeNull();
    expect(within(backlogWindowBlock).getByText(/^unavailable$/i)).toBeInTheDocument();

    const activeRunsRibbonBlock = screen.getByText(/active runs/i, { selector: '.ai-ribbon-label' }).closest('div');
    expect(activeRunsRibbonBlock).not.toBeNull();
    expect(within(activeRunsRibbonBlock).getByText(/^unavailable$/i)).toBeInTheDocument();
  });

  it('renders available console data before the slower initial endpoint settles', async () => {
    globalThis.fetch = vi.fn((input) => {
      const url = String(input);

      if (url.includes('/api/v1/ai/overview')) {
        return mockDelayedJsonResponse(
          {
            total_jobs: 400,
            enriched_jobs: 4,
            pending_jobs: 396,
            active_runs: 0,
            failed_items: 0,
            last_completed_run: { id: 'run-complete-7' },
          },
          10000,
        );
      }

      if (url.includes('/api/v1/ai/runs') && !url.includes('/items')) {
        return mockJsonResponse({
          runs: [
            {
              id: 'run-terminal-immediate',
              source_type: 'manual_pending',
              status: 'completed',
              created_at: '2026-04-15T12:10:00Z',
              started_at: '2026-04-15T12:10:00Z',
              completed_at: '2026-04-15T12:12:00Z',
              total_items: 2,
              pending_items: 0,
              completed_items: 2,
              failed_items: 0,
            },
          ],
        });
      }

      return Promise.reject(new Error(`Unhandled fetch: ${url}`));
    });

    vi.useFakeTimers();
    render(<AIEnrichmentPage />);

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByText(/run-terminal-immediate/i)).toBeInTheDocument();
    expect(screen.queryByText(/loading enrichment queue/i)).not.toBeInTheDocument();

    const pendingJobsLabel = screen.getByText(/pending jobs/i, { selector: '.stat-label' });
    const pendingJobsCard = pendingJobsLabel.closest('article');
    expect(pendingJobsCard).not.toBeNull();
    expect(within(pendingJobsCard).getByText(/^unavailable$/i)).toBeInTheDocument();
  });

  it('keeps retry polling alive after initial runs failure until a pending run recovers the monitor', async () => {
    let runCalls = 0;

    globalThis.fetch = vi.fn((input) => {
      const url = String(input);

      if (url.includes('/api/v1/ai/overview')) {
        return mockJsonResponse({
          total_jobs: 400,
          enriched_jobs: 4,
          pending_jobs: 396,
          active_runs: 1,
          failed_items: 2,
          last_completed_run: { id: 'run-complete-7' },
        });
      }

      if (url.includes('/api/v1/ai/runs') && !url.includes('/items')) {
        runCalls += 1;

        if (runCalls === 1) {
          return Promise.resolve({ ok: false, status: 500, json: async () => ({}) });
        }

        return mockJsonResponse({
          runs: [
            {
              id: 'run-recovered-later',
              source_type: 'manual_pending',
              status: 'pending',
              created_at: '2026-04-15T12:12:00Z',
              started_at: '2026-04-15T12:12:00Z',
              total_items: 4,
              pending_items: 3,
              completed_items: 1,
              failed_items: 0,
              current_job_title: 'Recovered On Poll',
            },
          ],
        });
      }

      return Promise.reject(new Error(`Unhandled fetch: ${url}`));
    });

    vi.useFakeTimers();
    render(<AIEnrichmentPage />);

    await act(async () => Promise.resolve());
    expect(screen.getByText(/refresh failed/i)).toBeInTheDocument();
    expect(screen.getByText(/run-complete-7/i)).toBeInTheDocument();

    const activeRunsSummaryLabel = screen.getByText(/active runs/i, { selector: '.stat-label' });
    const activeRunsSummaryCard = activeRunsSummaryLabel.closest('article');
    expect(activeRunsSummaryCard).not.toBeNull();
    expect(within(activeRunsSummaryCard).getByText('1')).toBeInTheDocument();

    const activeRunsRibbonLabel = screen.getByText(/active runs/i, { selector: '.ai-ribbon-label' });
    const ribbonBlock = activeRunsRibbonLabel.closest('div');
    expect(ribbonBlock).not.toBeNull();
    expect(within(ribbonBlock).getByText(/1\s*runs/i)).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(2100);
    });
    await act(async () => Promise.resolve());

    expect(runCalls).toBe(2);
    expect(screen.getByText(/run-recovered-later/i)).toBeInTheDocument();
    expect(screen.getByText(/recovered on poll/i)).toBeInTheDocument();
    expect(within(activeRunsSummaryCard).getByText('1')).toBeInTheDocument();
    expect(within(ribbonBlock).getByText(/1\s*runs/i)).toBeInTheDocument();
  });

  it('keeps degraded bootstrap polling until overview recovers after an initial runs-only load', async () => {
    let overviewCalls = 0;
    let runCalls = 0;

    globalThis.fetch = vi.fn((input) => {
      const url = String(input);

      if (url.includes('/api/v1/ai/overview')) {
        overviewCalls += 1;

        if (overviewCalls === 1) {
          return Promise.resolve({ ok: false, status: 500, json: async () => ({}) });
        }

        return mockJsonResponse({
          total_jobs: 400,
          enriched_jobs: 4,
          pending_jobs: 396,
          active_runs: 0,
          failed_items: 2,
          last_completed_run: { id: 'run-complete-7' },
        });
      }

      if (url.includes('/api/v1/ai/runs') && !url.includes('/items')) {
        runCalls += 1;
        return mockJsonResponse({
          runs: [
            {
              id: 'run-terminal-bootstrap',
              source_type: 'manual_pending',
              status: 'completed',
              created_at: '2026-04-15T12:10:00Z',
              started_at: '2026-04-15T12:10:00Z',
              completed_at: '2026-04-15T12:12:00Z',
              total_items: 2,
              pending_items: 0,
              completed_items: 2,
              failed_items: 0,
            },
          ],
        });
      }

      return Promise.reject(new Error(`Unhandled fetch: ${url}`));
    });

    vi.useFakeTimers();
    render(<AIEnrichmentPage />);

    await act(async () => Promise.resolve());
    expect(screen.getByText(/run-terminal-bootstrap/i)).toBeInTheDocument();
    expect(screen.getByText(/refresh failed/i)).toBeInTheDocument();

    const pendingJobsLabel = screen.getByText(/pending jobs/i, { selector: '.stat-label' });
    const pendingJobsCard = pendingJobsLabel.closest('article');
    expect(pendingJobsCard).not.toBeNull();
    expect(within(pendingJobsCard).getByText(/^unavailable$/i)).toBeInTheDocument();

    const activeRunsLabel = screen.getByText(/active runs/i, { selector: '.stat-label' });
    const activeRunsCard = activeRunsLabel.closest('article');
    expect(activeRunsCard).not.toBeNull();
    expect(within(activeRunsCard).getByText(/^unavailable$/i)).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(2100);
    });
    await act(async () => Promise.resolve());

    expect(overviewCalls).toBe(2);
    expect(runCalls).toBe(2);
    expect(screen.queryByText(/refresh failed/i)).not.toBeInTheDocument();
    expect(screen.getByText(/run-terminal-bootstrap/i)).toBeInTheDocument();

    const refreshedPendingJobsCard = screen.getByText(/pending jobs/i, { selector: '.stat-label' }).closest('article');
    expect(refreshedPendingJobsCard).not.toBeNull();
    expect(within(refreshedPendingJobsCard).getByText('396')).toBeInTheDocument();

    const lastCompletedBlock = screen.getByText(/last completed/i).closest('div');
    expect(lastCompletedBlock).not.toBeNull();
    expect(within(lastCompletedBlock).getByText(/run-complete-7/i)).toBeInTheDocument();
  });

});
