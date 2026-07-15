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
  apiFetchJson.mockResolvedValue({
    items: [listingTask],
    total: 1,
    page: 1,
    page_size: 10,
    refreshed_at: '2026-07-15T12:00:00Z',
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
    await waitFor(() => expect(apiFetchJson).toHaveBeenCalledTimes(2));

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
});
