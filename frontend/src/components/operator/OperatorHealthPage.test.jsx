import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { fetchOperatorHealthMock } = vi.hoisted(() => ({
  fetchOperatorHealthMock: vi.fn(),
}));

vi.mock('../../api/operatorHealth', () => ({
  fetchOperatorHealth: (...args) => fetchOperatorHealthMock(...args),
}));

import OperatorHealthPage from './OperatorHealthPage';

function buildPayload(overrides = {}) {
  return {
    status: 'degraded',
    generated_at: '2026-05-22T03:04:05+00:00',
    issues: [
      'stream.job.ingest.dead_letter has 2 messages',
      'scheduler-worker heartbeat is stale',
    ],
    scheduler: {
      heartbeat_status: 'stale',
      available: false,
      manual_run_available: true,
      last_heartbeat_at: '2026-05-22T02:55:00+00:00',
      last_reconcile_at: '2026-05-22T02:54:00+00:00',
      active_schedule_count: 3,
      registered_job_count: 3,
      reason: 'scheduler_worker_stale',
    },
    headed_runtime: {
      configured: false,
      browser_channel: 'msedge',
      browser_user_data_dir_configured: true,
      browser_user_data_dir_exists: false,
      lock_port: 47651,
      worker_group: 'crawl-headed-workers',
      worker_status: 'misconfigured',
      reason: 'browser_user_data_dir_missing',
    },
    backlogs: {
      pending_detail_rows: 11,
      failed_detail_rows: 3,
      manual_action_detail_rows: 2,
      outbox_pending: 4,
      outbox_failed: 1,
      dead_letter_count: 2,
      missing_current_embeddings: 3,
      ai_backlog_jobs: 6,
    },
    freshness: {
      crawl_job_listings: {
        pending: 11,
        failed: 3,
        manual_action_required: 2,
      },
    },
    ...overrides,
  };
}

describe('OperatorHealthPage', () => {
  beforeEach(() => {
    fetchOperatorHealthMock.mockReset();
  });

  it('fetches operator health on mount and renders the grouped summaries', async () => {
    fetchOperatorHealthMock.mockResolvedValue(buildPayload());

    render(<OperatorHealthPage />);

    expect(fetchOperatorHealthMock).toHaveBeenCalledTimes(1);
    expect(await screen.findByText(/^degraded$/i)).toBeInTheDocument();
    expect(screen.getByText(/stream\.job\.ingest\.dead_letter has 2 messages/i)).toBeInTheDocument();
    expect(screen.getByText(/scheduler-worker heartbeat is stale/i)).toBeInTheDocument();

    const schedulerSection = screen.getByRole('region', { name: /scheduler summary/i });
    expect(within(schedulerSection).getByText(/heartbeat status/i)).toBeInTheDocument();
    expect(within(schedulerSection).getByText(/^stale$/i)).toBeInTheDocument();

    const runtimeSection = screen.getByRole('region', { name: /headed runtime summary/i });
    expect(within(runtimeSection).getByText(/worker status/i)).toBeInTheDocument();
    expect(within(runtimeSection).getByText(/^misconfigured$/i)).toBeInTheDocument();

    const backlogSection = screen.getByRole('region', { name: /backlog metrics/i });
    expect(within(backlogSection).getByText(/pending detail rows/i)).toBeInTheDocument();
    expect(within(backlogSection).getByText(/^11$/)).toBeInTheDocument();

    expect(screen.getByRole('heading', { name: /operator health/i })).toBeInTheDocument();
    expect(screen.getByTestId('operator-health-last-updated')).toHaveAttribute(
      'datetime',
      '2026-05-22T03:04:05+00:00',
    );
  });

  it('supports manual refresh without exposing remediation actions', async () => {
    fetchOperatorHealthMock
      .mockResolvedValueOnce(buildPayload({ status: 'degraded' }))
      .mockResolvedValueOnce(buildPayload({ status: 'healthy', issues: [] }));

    const user = userEvent.setup();
    render(<OperatorHealthPage />);

    expect(await screen.findByText(/^degraded$/i)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /^refresh$/i }));

    await waitFor(() => {
      expect(fetchOperatorHealthMock).toHaveBeenCalledTimes(2);
    });
    expect(await screen.findByText(/^healthy$/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /retry|resume|recover|run now/i })).not.toBeInTheDocument();
  });

  it('degrades gracefully when optional fields are absent or null', async () => {
    fetchOperatorHealthMock.mockResolvedValue(
      buildPayload({
        generated_at: null,
        issues: null,
        scheduler: {
          heartbeat_status: null,
          available: null,
          manual_run_available: null,
        },
        headed_runtime: null,
        backlogs: {
          pending_detail_rows: null,
        },
      }),
    );

    render(<OperatorHealthPage />);

    const schedulerSection = await screen.findByRole('region', { name: /scheduler summary/i });
    expect(screen.getByText(/no active issues reported/i)).toBeInTheDocument();
    expect(screen.getAllByText(/^unavailable$/i).length).toBeGreaterThan(0);
    expect(within(schedulerSection).getAllByText(/^unavailable$/i).length).toBeGreaterThan(0);
    const runtimeSection = screen.getByRole('region', { name: /headed runtime summary/i });
    expect(within(runtimeSection).getAllByText(/^unavailable$/i).length).toBeGreaterThan(0);
  });

  it('shows an explicit unavailable state when the initial request fails without payload data', async () => {
    fetchOperatorHealthMock.mockRejectedValueOnce(new Error('redis offline'));

    render(<OperatorHealthPage />);

    expect(await screen.findByText(/failed to load operator health: redis offline/i)).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /operator data unavailable/i })).toBeInTheDocument();
    expect(screen.getByText(/operator health data is currently unavailable/i)).toBeInTheDocument();
    expect(screen.queryByText(/^clear$/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/no active issues reported/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: /issues/i })).not.toBeInTheDocument();
  });

  it('shows an error banner when refresh fails after data has already loaded and allows retry', async () => {
    fetchOperatorHealthMock
      .mockResolvedValueOnce(buildPayload({ status: 'healthy', issues: [] }))
      .mockRejectedValueOnce(new Error('redis offline'))
      .mockResolvedValueOnce(buildPayload({ status: 'degraded' }));

    const user = userEvent.setup();
    render(<OperatorHealthPage />);

    expect(await screen.findByText(/^healthy$/i)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /^refresh$/i }));

    expect(await screen.findByText(/failed to load operator health: redis offline/i)).toBeInTheDocument();
    expect(screen.getByRole('region', { name: /issues/i })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /^refresh$/i }));

    await waitFor(() => {
      expect(fetchOperatorHealthMock).toHaveBeenCalledTimes(3);
    });
    expect(await screen.findByText(/^degraded$/i)).toBeInTheDocument();
    expect(screen.queryByText(/failed to load operator health: redis offline/i)).not.toBeInTheDocument();
  });
});
