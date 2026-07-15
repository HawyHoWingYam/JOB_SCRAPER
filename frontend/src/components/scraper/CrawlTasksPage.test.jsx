/** @vitest-environment jsdom */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import userEvent from '@testing-library/user-event';
import { apiFetchJson } from '../../api/client';
import CrawlTasksPage, { AUTO_REFRESH_MS } from './CrawlTasksPage';

vi.mock('../../api/client', () => ({
  apiFetchJson: vi.fn(),
}));

const listingTask = {
  crawl_job_id: 'listing-task',
  status: 'running',
  source_site: 'jobsdb',
  crawl_mode: 'headless',
  phase: 1,
  job_ids_collected: 87,
  raw_job_ids_collected: 96,
  listings_staged: 87,
  detail_target_rows: 87,
  current_page: 2,
  total_pages: 10,
  updated_at: '2026-07-15T12:00:00Z',
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

beforeEach(() => {
  apiFetchJson.mockImplementation(async (url) => {
    if (`${url}`.includes('/capabilities')) {
      return {
        manual_actions: {
          helper_url: 'http://127.0.0.1:47652',
          health_url: 'http://127.0.0.1:47652/health',
          manual_start_workdir: 'backend',
          manual_start_command: 'python -m app.workers.run_manual_action_helper',
        },
      };
    }
    if (`${url}`.includes('/health')) {
      return { status: 'ok' };
    }
    return {
      items: [listingTask],
      total: 1,
      page: 1,
      page_size: 10,
      refreshed_at: '2026-07-15T12:00:00Z',
    };
  });
});

describe('CrawlTasksPage metric summaries', () => {
  it('uses a one-minute refresh interval and keeps the manual refresh action', async () => {
    expect(AUTO_REFRESH_MS).toBe(60_000);
    const setIntervalSpy = vi.spyOn(window, 'setInterval');

    render(<CrawlTasksPage />);

    const refreshButton = await screen.findByRole('button', { name: 'Refresh' });
    expect(refreshButton).toBeInTheDocument();
    expect(setIntervalSpy).toHaveBeenCalledWith(expect.any(Function), AUTO_REFRESH_MS);

    await userEvent.setup().click(refreshButton);
    await waitFor(() => {
      const taskRequests = apiFetchJson.mock.calls.filter(([url]) =>
        `${url}`.includes('/crawl-jobs/tasks')
      );
      expect(taskRequests).toHaveLength(2);
    });

    setIntervalSpy.mockRestore();
  });

  it('shows raw IDs only when the snapshot contains the optional field', async () => {
    render(<CrawlTasksPage />);
    expect(await screen.findByText('Raw IDs 96')).toBeInTheDocument();

    cleanup();
    apiFetchJson.mockResolvedValueOnce({
      items: [{ ...listingTask, raw_job_ids_collected: null }],
      total: 1,
      page: 1,
      page_size: 10,
    });
    render(<CrawlTasksPage />);
    await screen.findByTestId('crawl-task-row-listing-task');
    expect(screen.queryByText('Raw IDs 0')).not.toBeInTheDocument();
    expect(screen.queryByText('Raw IDs 96')).not.toBeInTheDocument();
  });

  it('uses the detail layout for detail snapshots and legacy numeric phase', async () => {
    apiFetchJson.mockResolvedValueOnce({
      items: [{
        crawl_job_id: 'detail-task',
        status: 'running',
        source_site: 'jobsdb',
        crawl_mode: 'headless',
        phase: 2,
        detail_target_rows: 4,
        detail_fetched: 3,
        jobs_saved: 2,
        detail_failed_count: 1,
        updated_at: '2026-07-15T12:00:00Z',
      }],
      total: 1,
      page: 1,
      page_size: 10,
    });
    render(<CrawlTasksPage />);

    expect(await screen.findByText('Detail targets 4')).toBeInTheDocument();
    expect(screen.getByText('Fetched 3')).toBeInTheDocument();
    expect(screen.getByText('Saved 2')).toBeInTheDocument();
    expect(screen.getByText('Failed 1')).toBeInTheDocument();
  });

  it('separates an OfferToday segment from the remaining global backlog', async () => {
    const detailTask = {
        crawl_job_id: 'offertoday-detail-task',
        status: 'running',
        source_site: 'offertoday',
        crawl_mode: 'headless',
        phase: 2,
        request_payload: { crawl_phase: 'detail', detail_scope: 'global' },
        detail_scope: 'global',
        detail_target_rows: 5000,
        detail_segment_index: 2,
        detail_segments_completed: 1,
        detail_segment_target_rows: 5000,
        detail_backlog_remaining: 7431,
        detail_backlog_failed: 20,
        detail_backlog_manual_action_required: 11,
        detail_continuation_state: 'continuing',
        updated_at: '2026-07-15T12:00:00Z',
    };
    apiFetchJson.mockImplementation(async (url) => {
      if (`${url}`.includes('/capabilities')) {
        return { manual_actions: {} };
      }
      return {
        items: [detailTask],
        total: 1,
        page: 1,
        page_size: 10,
      };
    });

    render(<CrawlTasksPage />);

    expect(await screen.findAllByText('Job Detail Crawl · Global backlog')).not.toHaveLength(0);
    expect(screen.getByText('Segment 2 targets 5,000')).toBeInTheDocument();
    expect(screen.getByText('Backlog remaining 7,431')).toBeInTheDocument();
    expect(screen.getByText('Backlog failed 20')).toBeInTheDocument();
    expect(screen.getByText('Manual review 11')).toBeInTheDocument();
  });
});

describe('CrawlTasksPage manual-action helper health', () => {
  it('keeps Fresh available while Open Browser waits for helper recovery', async () => {
    let helperOnline = false;
    const manualTask = {
      crawl_job_id: 'offertoday-manual-task',
      status: 'manual_action_required',
      source_site: 'offertoday',
      crawl_mode: 'headed',
      request_payload: { crawl_phase: 'detail' },
      manual_action: {
        resume_supported: true,
        reuse_open_browser_supported: true,
        classification: 'ip_blocked',
      },
      updated_at: '2026-07-15T12:00:00Z',
    };
    apiFetchJson.mockImplementation(async (url) => {
      if (`${url}`.includes('/capabilities')) {
        return {
          manual_actions: {
            helper_url: 'http://127.0.0.1:47652',
            health_url: 'http://127.0.0.1:47652/health',
            manual_start_workdir: 'backend',
            manual_start_command: 'python -m app.workers.run_manual_action_helper',
          },
        };
      }
      if (`${url}`.includes('/health')) {
        if (!helperOnline) {
          throw new TypeError('Failed to fetch');
        }
        return { status: 'ok' };
      }
      return {
        items: [manualTask],
        total: 1,
        page: 1,
        page_size: 10,
      };
    });

    render(<CrawlTasksPage />);

    expect(await screen.findByText('Helper offline')).toBeInTheDocument();
    expect(screen.getByText('python -m app.workers.run_manual_action_helper')).toBeInTheDocument();
    expect(screen.getByTestId('crawl-task-open-browser')).toBeDisabled();
    expect(screen.getByTestId('crawl-task-resume-fresh')).toBeEnabled();

    helperOnline = true;
    await userEvent.setup().click(screen.getByTestId('crawl-task-retry-helper-health'));
    await waitFor(() => expect(screen.getByTestId('crawl-task-open-browser')).toBeEnabled());
    expect(screen.queryByTestId('crawl-task-helper-offline')).not.toBeInTheDocument();
  });
});
