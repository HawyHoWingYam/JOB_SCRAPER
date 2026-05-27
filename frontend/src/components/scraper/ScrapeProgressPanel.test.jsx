import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import ScrapeProgressPanel from './ScrapeProgressPanel';

class MockEventSource {
  static instances = [];

  constructor(url) {
    this.url = url;
    this.onopen = null;
    this.onmessage = null;
    this.onerror = null;
    this.close = vi.fn();
    MockEventSource.instances.push(this);
  }

  emitOpen() {
    this.onopen?.();
  }

  emitMessage(payload) {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }

  emitError() {
    this.onerror?.(new Event('error'));
  }
}

function latestEventSource() {
  return MockEventSource.instances.at(-1);
}

describe('ScrapeProgressPanel', () => {
  beforeEach(() => {
    MockEventSource.instances = [];
    vi.stubGlobal('EventSource', MockEventSource);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('renders initial progress immediately before the first SSE payload arrives', () => {
    const { unmount } = render(
      <ScrapeProgressPanel
        isVisible
        initialProgress={{
          engineering: {
            status: 'running',
            category_name: 'Engineering',
            phase: 2,
            jobs_scraped: 3,
            total_jobs: 10,
            elapsed_seconds: 12,
            phase_rate: 0.4,
          },
        }}
        onClose={vi.fn()}
      />
    );

    expect(screen.getByText('Engineering')).toBeInTheDocument();
    expect(screen.getByText(/detail crawled: 3\/10/i)).toBeInTheDocument();

    unmount();
  });

  it('hydrates from initialProgress updates while visible if no progress has been received yet', () => {
    const { rerender, unmount } = render(
      <ScrapeProgressPanel isVisible initialProgress={{}} onClose={vi.fn()} />
    );

    expect(screen.getByText(/no active scraping tasks/i)).toBeInTheDocument();

    rerender(
      <ScrapeProgressPanel
        isVisible
        initialProgress={{
          engineering: {
            status: 'running',
            category_name: 'Engineering',
            phase: 2,
            jobs_scraped: 4,
            total_jobs: 12,
            elapsed_seconds: 10,
            phase_rate: 0.8,
          },
        }}
        onClose={vi.fn()}
      />
    );

    expect(screen.getByText('Engineering')).toBeInTheDocument();
    expect(screen.getByText(/detail crawled: 4\/12/i)).toBeInTheDocument();

    unmount();
  });

  it('renders chained AI progress after the save phase and exposes a run jump action', async () => {
    const onNavigateToAI = vi.fn();
    const user = userEvent.setup();

    const { unmount } = render(
      <ScrapeProgressPanel isVisible onClose={vi.fn()} onNavigateToAI={onNavigateToAI} />
    );

    const stream = latestEventSource();
    expect(stream.url).toBe('/api/v1/scrape/progress/stream');
    act(() => {
      stream.emitOpen();
      stream.emitMessage({
        all: {
          engineering: {
            status: 'ai_running',
            category_name: 'Engineering',
            phase: 5,
            jobs_scraped: 6,
            ai_run_id: 'run-123',
            ai_completed_items: 2,
            ai_failed_items: 1,
            ai_total_items: 6,
            elapsed_seconds: 42,
            phase_rate: 0.5,
          },
        },
      });
    });

    expect(await screen.findByRole('button', { name: /view ai run/i })).toBeInTheDocument();
    expect(screen.getByText(/items processed: 3\/6/i)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /view ai run/i }));

    expect(onNavigateToAI).toHaveBeenCalledWith('run-123');

    unmount();
  });

  it('does not mix ingest counters into the detail scraping phase', async () => {
    const { unmount } = render(<ScrapeProgressPanel isVisible onClose={vi.fn()} />);

    const stream = latestEventSource();
    act(() => {
      stream.emitOpen();
      stream.emitMessage({
        all: {
          engineering: {
            status: 'running',
            category_name: 'Engineering',
            phase: 2,
            jobs_scraped: 2,
            total_jobs: 5,
            jobs_saved: 1,
            save_total: 2,
            elapsed_seconds: 18,
            phase_rate: 0.5,
          },
        },
      });
    });

    expect(await screen.findByText(/detail crawled: 2\/5/i)).toBeInTheDocument();
    expect(screen.queryByText(/saved:/i)).not.toBeInTheDocument();

    unmount();
  });

  it('shows accurate listing counters with elapsed time only during job id crawling', async () => {
    const { unmount } = render(<ScrapeProgressPanel isVisible onClose={vi.fn()} />);

    const stream = latestEventSource();
    act(() => {
      stream.emitOpen();
      stream.emitMessage({
        all: {
          engineering: {
            crawl_job_id: 'crawl-job-listing-1',
            status: 'running',
            source_site: 'jobsdb',
            category_name: 'Engineering',
            phase: 1,
            current_page: 2,
            total_pages: 8,
            job_ids_collected: 49,
            jobs_skipped_existing: 7,
            elapsed_seconds: 11,
          },
        },
      });
    });

    expect(await screen.findByText(/pages: 2\/8/i)).toBeInTheDocument();
    expect(screen.getByText(/ids found: 49/i)).toBeInTheDocument();
    expect(screen.getByText(/existing skipped: 7/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /diagnostics/i }));
    expect(screen.getByText(/elapsed: 11s/i)).toBeInTheDocument();
    expect(screen.queryByText(/rate:/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/eta:/i)).not.toBeInTheDocument();

    unmount();
  });

  it('shows accurate detail counters with elapsed time only and no progress bar', async () => {
    const { container, unmount } = render(<ScrapeProgressPanel isVisible onClose={vi.fn()} />);

    const stream = latestEventSource();
    act(() => {
      stream.emitOpen();
      stream.emitMessage({
        all: {
          engineering: {
            status: 'running',
            category_name: 'Engineering',
            metric_scope: 'detail_run',
            phase: 2,
            detail_selected_rows: 12,
            detail_skipped_existing_rows: 2,
            detail_target_rows: 10,
            jobs_scraped: 2,
            total_jobs: 12,
            detail_job_index: 3,
            detail_job_total: 12,
            current_job_title: 'Senior Data Analyst',
            queued_at: '2026-05-27T09:00:00Z',
            started_at: '2026-05-27T09:01:00Z',
            jobs_saved: 1,
            save_total: 2,
            elapsed_seconds: 18,
            phase_rate: 1.5,
            eta_seconds: 6,
          },
        },
      });
    });

    expect(await screen.findByText(/rows checked: 12/i)).toBeInTheDocument();
    expect(screen.getByText(/skipped existing: 2/i)).toBeInTheDocument();
    expect(screen.getByText(/detail crawled: 2\/10/i)).toBeInTheDocument();
    expect(screen.getByText(/current target: 3\/12/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /diagnostics/i }));
    expect(screen.getByText(/current title: senior data analyst/i)).toBeInTheDocument();
    expect(screen.getByText(/queued:/i)).toBeInTheDocument();
    expect(screen.getByText(/started:/i)).toBeInTheDocument();
    expect(screen.getByText(/ended: -/i)).toBeInTheDocument();
    expect(screen.getByText(/elapsed: 18s/i)).toBeInTheDocument();

    expect(container.querySelector('.progress-bar-fill')).toBeNull();
    expect(screen.queryByText(/rate:/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/eta:/i)).not.toBeInTheDocument();

    unmount();
  });

  it('renders completed_with_ai_failures as a distinct terminal state', async () => {
    const { unmount } = render(<ScrapeProgressPanel isVisible onClose={vi.fn()} />);

    const stream = latestEventSource();
    act(() => {
      stream.emitOpen();
      stream.emitMessage({
        all: {
          design: {
            status: 'completed_with_ai_failures',
            category_name: 'Design',
            phase: 5,
            jobs_scraped: 4,
            ai_run_id: 'run-456',
            ai_completed_items: 3,
            ai_failed_items: 1,
            ai_total_items: 4,
            completed_at: '2026-04-15T12:00:00Z',
          },
        },
      });
    });

    expect(
      await screen.findByText(/completed with ai failures/i, { selector: '.status-badge' })
    ).toBeInTheDocument();
    expect(screen.getByText(/succeeded: 3/i)).toBeInTheDocument();
    expect(screen.getByText(/failed: 1/i)).toBeInTheDocument();

    unmount();
  });

  it('renders completed crawls with downstream backlog as a warning state', async () => {
    const { unmount } = render(<ScrapeProgressPanel isVisible onClose={vi.fn()} />);

    const stream = latestEventSource();
    act(() => {
      stream.emitOpen();
      stream.emitMessage({
        all: {
          engineering: {
            status: 'completed',
            operator_state: 'completed_with_downstream_backlog',
            category_name: 'Engineering',
            metric_scope: 'backlog_pool',
            phase: 1,
            listings_staged: 96,
            detail_pending: 74,
            detail_completed: 22,
            queued_at: '2026-05-27T09:00:00Z',
            started_at: '2026-05-27T09:01:00Z',
            completed_at: '2026-05-27T09:05:00Z',
          },
        },
      });
    });

    expect(
      await screen.findByText(/downstream backlog/i, { selector: '.status-badge' })
    ).toBeInTheDocument();
    expect(screen.getByText(/staged listings: 96/i)).toBeInTheDocument();
    expect(screen.getByText(/pending details: 74/i)).toBeInTheDocument();
    expect(screen.getByText(/completed details: 22/i)).toBeInTheDocument();
    expect(screen.queryByText(/ingested:/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /diagnostics/i }));
    expect(screen.getByText(/ended:/i)).toBeInTheDocument();

    unmount();
  });

  it('hides backlog cards already linked to a live detail task', async () => {
    render(<ScrapeProgressPanel isVisible onClose={vi.fn()} />);

    const stream = latestEventSource();
    act(() => {
      stream.emitOpen();
      stream.emitMessage({
        all: {
          'detail-run-1': {
            crawl_job_id: 'detail-run-1',
            status: 'running',
            source_site: 'ctgoodjobs',
            category_name: 'Information Technology',
            crawl_mode: 'headed',
            phase: 2,
            jobs_scraped: 10,
            detail_target_rows: 50,
            request_payload: {
              source_listing_crawl_job_id: 'linked-batch-1',
            },
          },
          'linked-batch-1': {
            crawl_job_id: 'linked-batch-1',
            status: 'completed',
            operator_state: 'completed_with_downstream_backlog',
            metric_scope: 'backlog_pool',
            source_site: 'ctgoodjobs',
            category_name: 'Information Technology',
            crawl_mode: 'headed',
            listings_staged: 300,
            detail_pending: 120,
            completed_at: '2026-05-26T10:00:00Z',
          },
          'unlinked-batch-2': {
            crawl_job_id: 'unlinked-batch-2',
            status: 'completed',
            operator_state: 'completed_with_downstream_backlog',
            metric_scope: 'backlog_pool',
            source_site: 'ctgoodjobs',
            category_name: 'Information Technology',
            crawl_mode: 'headed',
            listings_staged: 180,
            detail_pending: 45,
            completed_at: '2026-05-26T09:00:00Z',
          },
        },
      });
    });

    fireEvent.click(screen.getAllByRole('button', { name: /diagnostics/i })[0]);
    expect(await screen.findByText(/listing batch: ctgoodjobs batch linked-batch-1/i)).toBeInTheDocument();
    expect(screen.queryByText(/task linked-batch-1/i)).not.toBeInTheDocument();
    expect(screen.getByText(/task unlinked-batch-2/i)).toBeInTheDocument();
  });

  it('keeps backlog card order stable when only updated_at changes', async () => {
    const { container } = render(<ScrapeProgressPanel isVisible onClose={vi.fn()} />);

    const stream = latestEventSource();
    act(() => {
      stream.emitOpen();
      stream.emitMessage({
        all: {
          'batch-newer': {
            crawl_job_id: 'batch-newer',
            status: 'completed',
            operator_state: 'completed_with_downstream_backlog',
            metric_scope: 'backlog_pool',
            source_site: 'jobsdb',
            category_name: 'Engineering',
            crawl_mode: 'headed',
            listings_staged: 96,
            detail_pending: 74,
            completed_at: '2026-05-27T10:05:00Z',
            updated_at: '2026-05-27T10:05:00Z',
          },
          'batch-older': {
            crawl_job_id: 'batch-older',
            status: 'completed',
            operator_state: 'completed_with_downstream_backlog',
            metric_scope: 'backlog_pool',
            source_site: 'jobsdb',
            category_name: 'Engineering',
            crawl_mode: 'headed',
            listings_staged: 88,
            detail_pending: 55,
            completed_at: '2026-05-27T09:05:00Z',
            updated_at: '2026-05-27T09:05:00Z',
          },
        },
      });
    });

    act(() => {
      stream.emitMessage({
        all: {
          'batch-newer': {
            crawl_job_id: 'batch-newer',
            status: 'completed',
            operator_state: 'completed_with_downstream_backlog',
            metric_scope: 'backlog_pool',
            source_site: 'jobsdb',
            category_name: 'Engineering',
            crawl_mode: 'headed',
            listings_staged: 96,
            detail_pending: 70,
            completed_at: '2026-05-27T10:05:00Z',
            updated_at: '2026-05-27T10:05:00Z',
          },
          'batch-older': {
            crawl_job_id: 'batch-older',
            status: 'completed',
            operator_state: 'completed_with_downstream_backlog',
            metric_scope: 'backlog_pool',
            source_site: 'jobsdb',
            category_name: 'Engineering',
            crawl_mode: 'headed',
            listings_staged: 88,
            detail_pending: 40,
            completed_at: '2026-05-27T09:05:00Z',
            updated_at: '2026-05-27T10:10:00Z',
          },
        },
      });
    });

    const backlogSection = Array.from(container.querySelectorAll('.progress-section')).find((section) =>
      section.textContent?.includes('Backlog Follow-up')
    );
    expect(backlogSection).toBeTruthy();
    const taskIds = Array.from(backlogSection.querySelectorAll('.progress-task-id')).map((node) => node.textContent);

    expect(taskIds).toEqual(['Task batch-newer', 'Task batch-older']);
  });

  it('renders manual action guidance with split resume actions and task identity', async () => {
    const writeText = vi.fn();
    Object.defineProperty(Object.getPrototypeOf(window.navigator), 'clipboard', {
      configurable: true,
      value: { writeText },
    });
    Object.defineProperty(window.navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    });
    Object.defineProperty(globalThis.navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    });
    const onResumeCrawlJob = vi.fn();
    const onCancelCrawlJob = vi.fn();
    const onOpenManualActionBrowser = vi.fn();

    const { unmount } = render(
      <ScrapeProgressPanel
        isVisible
        onClose={vi.fn()}
        onResumeCrawlJob={onResumeCrawlJob}
        onCancelCrawlJob={onCancelCrawlJob}
        onOpenManualActionBrowser={onOpenManualActionBrowser}
      />
    );

    const stream = latestEventSource();
    act(() => {
      stream.emitOpen();
      stream.emitMessage({
        all: {
          'crawl-job-123': {
            crawl_job_id: 'crawl-job-123',
            status: 'manual_action_required',
            category_name: 'Information Technology',
            crawl_mode: 'headed',
            queued_at: '2026-05-27T09:00:00Z',
            started_at: '2026-05-27T09:02:00Z',
            manual_action: {
              stage: 'category_page',
              blocked_url: 'https://jobs.ctgoodjobs.hk/jobs/jobs-in-information-technology?page=52',
              browser_profile_path: 'C:\\profiles\\ctgoodjobs-headed',
              browser_channel: 'msedge',
              instructions: [
                'Open the headed browser profile.',
                'Complete the human verification challenge.',
              ],
            },
          },
        },
      });
    });

    expect(await screen.findByText(/manual action required/i)).toBeInTheDocument();
    expect(screen.getByText(/task crawl-job-123/i)).toBeInTheDocument();
    expect(screen.getByText(/information technology/i)).toBeInTheDocument();
    expect(screen.getByText(/stage: category_page/i)).toBeInTheDocument();
    expect(
      screen.getByText('https://jobs.ctgoodjobs.hk/jobs/jobs-in-information-technology?page=52')
    ).toBeInTheDocument();
    expect(screen.getByText(/c:\\profiles\\ctgoodjobs-headed/i)).toBeInTheDocument();
    expect(screen.getByText(/queued:/i)).toBeInTheDocument();
    expect(screen.getByText(/started:/i)).toBeInTheDocument();
    expect(screen.getByText(/ended: -/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /copy url/i }));
    expect(writeText).toHaveBeenCalledWith(
      'https://jobs.ctgoodjobs.hk/jobs/jobs-in-information-technology?page=52'
    );

    fireEvent.click(screen.getByRole('button', { name: /open verification browser/i }));
    expect(onOpenManualActionBrowser).toHaveBeenCalledWith('crawl-job-123');

    expect(screen.getByRole('button', { name: /resume using open browser/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /resume fresh/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /capture and analyze/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /auto resolve/i })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /cancel/i }));
    expect(onCancelCrawlJob).toHaveBeenCalledWith('crawl-job-123');

    unmount();
  });

  it('sends the reuse_open_browser strategy when resuming with an open browser', async () => {
    const onResumeCrawlJob = vi.fn().mockResolvedValue({ status: 'dispatching' });
    const onGetManualActionReuseStatus = vi.fn().mockResolvedValue({
      available: true,
      reuse_open_browser_supported: true,
      live_session: {
        browser_channel: 'msedge',
        attached_at: '2026-05-27T08:30:00Z',
      },
    });

    render(
      <ScrapeProgressPanel
        isVisible
        onClose={vi.fn()}
        onResumeCrawlJob={onResumeCrawlJob}
        onGetManualActionReuseStatus={onGetManualActionReuseStatus}
      />
    );

    const stream = latestEventSource();
    act(() => {
      stream.emitOpen();
      stream.emitMessage({
        all: {
          'crawl-job-555': {
            crawl_job_id: 'crawl-job-555',
            status: 'manual_action_required',
            source_site: 'ctgoodjobs',
            category_name: 'Information Technology',
            crawl_mode: 'headed',
            manual_action: {
              source_site: 'ctgoodjobs',
              stage: 'category_page',
              blocked_url: 'https://jobs.ctgoodjobs.hk/jobs',
              browser_profile_path: 'C:\\profiles\\ctgoodjobs-headed',
              browser_channel: 'msedge',
              instructions: ['Keep the manual browser open after verification clears.'],
            },
          },
        },
      });
    });

    fireEvent.click(await screen.findByRole('button', { name: /resume using open browser/i }));

    await waitFor(() => {
      expect(onGetManualActionReuseStatus).toHaveBeenCalledWith('crawl-job-555');
      expect(onResumeCrawlJob).toHaveBeenCalledWith('crawl-job-555', 'reuse_open_browser');
    });
    expect(screen.getByText(/live session browser: msedge/i)).toBeInTheDocument();
  });

  it('renders retry attach and resume fresh when open-browser reuse is unavailable', async () => {
    const onResumeCrawlJob = vi.fn();
    const onGetManualActionReuseStatus = vi.fn().mockResolvedValue({
      available: false,
      reuse_open_browser_supported: true,
      reason: 'No attachable browser session found.',
    });

    render(
      <ScrapeProgressPanel
        isVisible
        onClose={vi.fn()}
        onResumeCrawlJob={onResumeCrawlJob}
        onGetManualActionReuseStatus={onGetManualActionReuseStatus}
      />
    );

    const stream = latestEventSource();
    act(() => {
      stream.emitOpen();
      stream.emitMessage({
        all: {
          'crawl-job-556': {
            crawl_job_id: 'crawl-job-556',
            status: 'manual_action_required',
            category_name: 'Information Technology',
            crawl_mode: 'headed',
            manual_action: {
              stage: 'category_page',
              blocked_url: 'https://jobs.ctgoodjobs.hk/jobs',
              browser_profile_path: 'C:\\profiles\\ctgoodjobs-headed',
              browser_channel: 'msedge',
              instructions: ['Keep the manual browser open after verification clears.'],
            },
          },
        },
      });
    });

    fireEvent.click(await screen.findByRole('button', { name: /resume using open browser/i }));

    expect(await screen.findByText(/no attachable browser session found/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /retry attach/i })).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: /resume fresh/i })[0]).toBeInTheDocument();
    expect(onResumeCrawlJob).not.toHaveBeenCalled();
  });

  it('shows the fresh warning path and still resumes with the fresh_profile strategy', async () => {
    const onResumeCrawlJob = vi.fn().mockResolvedValue({ status: 'dispatching' });

    render(
      <ScrapeProgressPanel
        isVisible
        onClose={vi.fn()}
        onResumeCrawlJob={onResumeCrawlJob}
      />
    );

    const stream = latestEventSource();
    act(() => {
      stream.emitOpen();
      stream.emitMessage({
        all: {
          'crawl-job-557': {
            crawl_job_id: 'crawl-job-557',
            status: 'manual_action_required',
            source_site: 'ctgoodjobs',
            category_name: 'Information Technology',
            crawl_mode: 'headed',
            manual_action: {
              source_site: 'ctgoodjobs',
              stage: 'category_page',
              blocked_url: 'https://jobs.ctgoodjobs.hk/jobs',
              browser_profile_path: 'C:\\profiles\\ctgoodjobs-headed',
              browser_channel: 'msedge',
              instructions: ['Keep the manual browser open after verification clears.'],
            },
          },
        },
      });
    });

    fireEvent.click(await screen.findByRole('button', { name: /^resume fresh$/i }));

    expect(
      await screen.findByText(/close any profile windows first before starting a fresh browser session/i)
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /resume fresh now/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /resume fresh now/i }));

    await waitFor(() => {
      expect(onResumeCrawlJob).toHaveBeenCalledWith('crawl-job-557', 'fresh_profile');
    });
  });

  it('shows only the latest five tasks based on update time', async () => {
    const { unmount } = render(<ScrapeProgressPanel isVisible onClose={vi.fn()} />);

    const stream = latestEventSource();
    act(() => {
      stream.emitOpen();
      stream.emitMessage({
        all: {
          'crawl-job-001': {
            crawl_job_id: 'crawl-job-001',
            status: 'running',
            source_site: 'jobsdb',
            category_name: 'Task 1',
            crawl_mode: 'headed',
            phase: 1,
            current_page: 1,
            total_pages: 3,
            updated_at: '2026-05-26T10:00:01.000Z',
          },
          'crawl-job-002': {
            crawl_job_id: 'crawl-job-002',
            status: 'running',
            source_site: 'jobsdb',
            category_name: 'Task 2',
            crawl_mode: 'headed',
            phase: 1,
            current_page: 1,
            total_pages: 3,
            updated_at: '2026-05-26T10:00:02.000Z',
          },
          'crawl-job-003': {
            crawl_job_id: 'crawl-job-003',
            status: 'running',
            source_site: 'jobsdb',
            category_name: 'Task 3',
            crawl_mode: 'headed',
            phase: 1,
            current_page: 1,
            total_pages: 3,
            updated_at: '2026-05-26T10:00:03.000Z',
          },
          'crawl-job-004': {
            crawl_job_id: 'crawl-job-004',
            status: 'running',
            source_site: 'jobsdb',
            category_name: 'Task 4',
            crawl_mode: 'headed',
            phase: 1,
            current_page: 1,
            total_pages: 3,
            updated_at: '2026-05-26T10:00:04.000Z',
          },
          'crawl-job-005': {
            crawl_job_id: 'crawl-job-005',
            status: 'running',
            source_site: 'jobsdb',
            category_name: 'Task 5',
            crawl_mode: 'headed',
            phase: 1,
            current_page: 1,
            total_pages: 3,
            updated_at: '2026-05-26T10:00:05.000Z',
          },
          'crawl-job-006': {
            crawl_job_id: 'crawl-job-006',
            status: 'running',
            source_site: 'jobsdb',
            category_name: 'Task 6',
            crawl_mode: 'headed',
            phase: 1,
            current_page: 1,
            total_pages: 3,
            updated_at: '2026-05-26T10:00:06.000Z',
          },
        },
      });
    });

    expect(await screen.findByText(/task crawl-job-006/i)).toBeInTheDocument();
    expect(screen.getByText(/task crawl-job-005/i)).toBeInTheDocument();
    expect(screen.getByText(/task crawl-job-004/i)).toBeInTheDocument();
    expect(screen.getByText(/task crawl-job-003/i)).toBeInTheDocument();
    expect(screen.getByText(/task crawl-job-002/i)).toBeInTheDocument();
    expect(screen.queryByText(/task crawl-job-001/i)).not.toBeInTheDocument();

    unmount();
  });

  it('renders action-required work separately from recent terminal tasks', async () => {
    render(<ScrapeProgressPanel isVisible onClose={vi.fn()} />);

    const stream = latestEventSource();
    act(() => {
      stream.emitOpen();
      stream.emitMessage({
        all: {
          'crawl-job-manual': {
            crawl_job_id: 'crawl-job-manual',
            status: 'manual_action_required',
            source_site: 'ctgoodjobs',
            category_name: 'Information Technology',
            crawl_mode: 'headed',
            updated_at: '2026-05-27T11:00:00.000Z',
            manual_action: {
              stage: 'category_page',
              blocked_url: 'https://jobs.ctgoodjobs.hk/jobs',
              browser_profile_path: 'C:\\profiles\\ctgoodjobs-headed',
              browser_channel: 'msedge',
              instructions: ['Complete the verification challenge.'],
            },
          },
          'crawl-job-cancelled': {
            crawl_job_id: 'crawl-job-cancelled',
            status: 'cancelled',
            source_site: 'jobsdb',
            category_name: 'Engineering',
            crawl_mode: 'headed',
            queued_at: '2026-05-27T10:55:00.000Z',
            started_at: '2026-05-27T10:56:00.000Z',
            completed_at: '2026-05-27T10:59:00.000Z',
            updated_at: '2026-05-27T10:59:00.000Z',
            error: 'Cancelled by operator',
          },
        },
      });
    });

    expect(await screen.findByText(/needs attention/i)).toBeInTheDocument();
    expect(screen.getByText(/recent terminal/i)).toBeInTheDocument();
    expect(screen.getByText(/task crawl-job-manual/i)).toBeInTheDocument();
    expect(screen.getByText(/task crawl-job-cancelled/i)).toBeInTheDocument();
    expect(screen.getAllByText(/ended:/i).length).toBeGreaterThan(0);
  });

  it('orders needs-attention tasks by severity before recency', async () => {
    const { container } = render(<ScrapeProgressPanel isVisible onClose={vi.fn()} />);

    const stream = latestEventSource();
    act(() => {
      stream.emitOpen();
      stream.emitMessage({
        all: {
          'crawl-job-warning-newer': {
            crawl_job_id: 'crawl-job-warning-newer',
            status: 'running',
            source_site: 'ctgoodjobs',
            category_name: 'Information Technology',
            crawl_mode: 'headless',
            phase: 2,
            jobs_scraped: 3,
            detail_target_rows: 12,
            proxy_enabled: true,
            proxy_provider: 'static',
            proxy_requests_network_fail: 1,
            updated_at: '2026-05-27T12:05:00.000Z',
          },
          'crawl-job-manual-older': {
            crawl_job_id: 'crawl-job-manual-older',
            status: 'manual_action_required',
            source_site: 'ctgoodjobs',
            category_name: 'Information Technology',
            crawl_mode: 'headed',
            updated_at: '2026-05-27T12:00:00.000Z',
            manual_action: {
              stage: 'browser_profile_in_use',
              blocked_url: 'https://jobs.ctgoodjobs.hk/jobs',
              browser_profile_path: 'C:\\profiles\\ctgoodjobs-headed',
              browser_channel: 'msedge',
              instructions: ['Close all Edge windows that use the listed automation profile.'],
            },
          },
        },
      });
    });

    await screen.findByText(/needs attention/i);

    const section = Array.from(container.querySelectorAll('.progress-section')).find((element) =>
      element.textContent?.includes('Needs Attention')
    );
    const taskLabels = Array.from(section.querySelectorAll('.progress-task-id')).map((node) => node.textContent);

    expect(taskLabels).toEqual([
      'Task crawl-job-manual-older',
      'Task crawl-job-warning-newer',
    ]);
  });

  it('auto-expands diagnostics for manual-action runs and exposes a diagnostics toggle', async () => {
    render(<ScrapeProgressPanel isVisible onClose={vi.fn()} />);

    const stream = latestEventSource();
    act(() => {
      stream.emitOpen();
      stream.emitMessage({
        all: {
          'crawl-job-manual': {
            crawl_job_id: 'crawl-job-manual',
            status: 'manual_action_required',
            source_site: 'ctgoodjobs',
            category_name: 'Information Technology',
            crawl_mode: 'headed',
            updated_at: '2026-05-27T11:00:00.000Z',
            manual_action: {
              stage: 'category_page',
              blocked_url: 'https://jobs.ctgoodjobs.hk/jobs',
              browser_profile_path: 'C:\\profiles\\ctgoodjobs-headed',
              browser_channel: 'msedge',
              instructions: ['Complete the verification challenge.'],
            },
          },
        },
      });
    });

    expect(await screen.findByText(/manual action required/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /diagnostics/i })).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText(/stage: category_page/i)).toBeInTheDocument();
  });

  it('shows listing batch identity on detail task cards', async () => {
    render(<ScrapeProgressPanel isVisible onClose={vi.fn()} />);

    const stream = latestEventSource();
    act(() => {
      stream.emitOpen();
      stream.emitMessage({
        all: {
          'crawl-job-detail': {
            crawl_job_id: 'crawl-job-detail',
            status: 'running',
            source_site: 'jobsdb',
            category_name: 'Engineering',
            crawl_mode: 'headed',
            phase: 2,
            jobs_scraped: 8,
            total_jobs: 24,
            request_payload: {
              source_listing_crawl_job_id: '11111111-1111-4111-8111-111111111111',
            },
          },
        },
      });
    });

    fireEvent.click(await screen.findByRole('button', { name: /diagnostics/i }));

    expect(
      await screen.findByText(/listing batch: jobsdb batch 11111111-1111-4111-8111-111111111111/i)
    ).toBeInTheDocument();
  });

  it('keeps running proxy-warning items collapsed by default and surfaces a warning chip', async () => {
    render(<ScrapeProgressPanel isVisible onClose={vi.fn()} />);

    const stream = latestEventSource();
    act(() => {
      stream.emitOpen();
      stream.emitMessage({
        all: {
          'crawl-job-proxy': {
            crawl_job_id: 'crawl-job-proxy',
            status: 'running',
            source_site: 'ctgoodjobs',
            category_name: 'Information Technology',
            crawl_mode: 'headless',
            phase: 2,
            jobs_scraped: 5,
            detail_target_rows: 24,
            proxy_enabled: true,
            proxy_provider: 'static',
            proxy_requests_total: 8,
            proxy_requests_success: 6,
            proxy_requests_challenge: 0,
            proxy_requests_network_fail: 1,
            proxy_requests_http_fail: 1,
            proxy_quarantined_total: 0,
          },
        },
      });
    });

    expect(await screen.findByText(/proxy unstable/i)).toBeInTheDocument();
    expect(screen.getByText(/needs attention/i)).toBeInTheDocument();
    expect(screen.queryByText(/^running or queued$/i)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /diagnostics/i })).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText(/proxy requests: 8/i)).not.toBeInTheDocument();
  });

  it('prefers a challenge-specific chip when proxy challenge counts are present without quarantines', async () => {
    render(<ScrapeProgressPanel isVisible onClose={vi.fn()} />);

    const stream = latestEventSource();
    act(() => {
      stream.emitOpen();
      stream.emitMessage({
        all: {
          'crawl-job-proxy-challenge': {
            crawl_job_id: 'crawl-job-proxy-challenge',
            status: 'running',
            source_site: 'ctgoodjobs',
            category_name: 'Information Technology',
            crawl_mode: 'headless',
            phase: 2,
            jobs_scraped: 5,
            detail_target_rows: 24,
            proxy_enabled: true,
            proxy_provider: 'static',
            proxy_requests_total: 8,
            proxy_requests_success: 6,
            proxy_requests_challenge: 2,
            proxy_requests_network_fail: 0,
            proxy_requests_http_fail: 0,
            proxy_quarantined_total: 0,
          },
        },
      });
    });

    expect(await screen.findByText(/challenge spike/i)).toBeInTheDocument();
    expect(screen.queryByText(/proxy unstable/i)).not.toBeInTheDocument();
  });

  it('prefers a quarantine-specific chip when proxy leases have been quarantined', async () => {
    render(<ScrapeProgressPanel isVisible onClose={vi.fn()} />);

    const stream = latestEventSource();
    act(() => {
      stream.emitOpen();
      stream.emitMessage({
        all: {
          'crawl-job-proxy-quarantine': {
            crawl_job_id: 'crawl-job-proxy-quarantine',
            status: 'running',
            source_site: 'ctgoodjobs',
            category_name: 'Information Technology',
            crawl_mode: 'headless',
            phase: 2,
            jobs_scraped: 5,
            detail_target_rows: 24,
            proxy_enabled: true,
            proxy_provider: 'static',
            proxy_requests_total: 8,
            proxy_requests_success: 6,
            proxy_requests_challenge: 1,
            proxy_requests_network_fail: 1,
            proxy_requests_http_fail: 0,
            proxy_quarantined_total: 1,
          },
        },
      });
    });

    expect(await screen.findByText(/lease quarantined/i)).toBeInTheDocument();
    expect(screen.queryByText(/proxy unstable/i)).not.toBeInTheDocument();
  });

  it('shows proxy runtime details when the backend includes proxy metadata', async () => {
    render(<ScrapeProgressPanel isVisible onClose={vi.fn()} />);

    const stream = latestEventSource();
    act(() => {
      stream.emitOpen();
      stream.emitMessage({
        all: {
          'crawl-job-proxy': {
            crawl_job_id: 'crawl-job-proxy',
            status: 'running',
            source_site: 'ctgoodjobs',
            category_name: 'Information Technology',
            crawl_mode: 'headless',
            phase: 2,
            jobs_scraped: 5,
            detail_target_rows: 24,
            proxy_enabled: true,
            proxy_provider: 'static',
            proxy_requests_total: 8,
            proxy_requests_success: 6,
            proxy_requests_challenge: 1,
            proxy_requests_network_fail: 1,
            proxy_quarantined_total: 1,
          },
        },
      });
    });

    fireEvent.click(await screen.findByRole('button', { name: /diagnostics/i }));

    expect(await screen.findByText(/proxy: static/i)).toBeInTheDocument();
    expect(screen.getByText(/proxy requests: 8/i)).toBeInTheDocument();
    expect(screen.getByText(/proxy success: 6/i)).toBeInTheDocument();
    expect(screen.getByText(/proxy challenges: 1/i)).toBeInTheDocument();
    expect(screen.getByText(/proxy network fail: 1/i)).toBeInTheDocument();
    expect(screen.getByText(/proxy quarantined: 1/i)).toBeInTheDocument();
  });

  it('renders a recovery decision panel for manual-action jobs with a primary resume action', async () => {
    render(<ScrapeProgressPanel isVisible onClose={vi.fn()} />);

    const stream = latestEventSource();
    act(() => {
      stream.emitOpen();
      stream.emitMessage({
        all: {
          'crawl-job-456': {
            crawl_job_id: 'crawl-job-456',
            status: 'manual_action_required',
            source_site: 'ctgoodjobs',
            category_name: 'Information Technology',
            crawl_mode: 'headed',
            manual_action: {
              stage: 'browser_profile_in_use',
              blocked_url: 'https://jobs.ctgoodjobs.hk/jobs',
              browser_profile_path: 'C:\\profiles\\ctgoodjobs-headed',
              browser_channel: 'msedge',
              instructions: [
                'Close all Edge windows that use the listed automation profile.',
                'Return to the app and click Resume.',
              ],
            },
          },
        },
      });
    });

    expect(await screen.findByText(/next step/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /resume using open browser/i })).toHaveClass('progress-primary-action');
    expect(screen.getByRole('button', { name: /close profile windows/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /diagnostics/i })).toHaveAttribute('aria-expanded', 'true');
  });

  it('suppresses browser-reuse actions for proxy_unavailable manual-action runs', async () => {
    const onResumeCrawlJob = vi.fn();

    render(
      <ScrapeProgressPanel
        isVisible
        onClose={vi.fn()}
        onResumeCrawlJob={onResumeCrawlJob}
      />
    );

    const stream = latestEventSource();
    act(() => {
      stream.emitOpen();
      stream.emitMessage({
        all: {
          'crawl-job-proxy-missing': {
            crawl_job_id: 'crawl-job-proxy-missing',
            status: 'manual_action_required',
            source_site: 'ctgoodjobs',
            category_name: 'Information Technology',
            crawl_mode: 'headed',
            manual_action: {
              stage: 'proxy_unavailable',
              blocked_url: 'https://jobs.ctgoodjobs.hk/jobs',
              browser_profile_path: 'C:\\profiles\\ctgoodjobs-headed',
              browser_channel: 'msedge',
              instructions: [
                'Verify the CTGoodJobs proxy settings and provider availability.',
                'Return to the app and click Resume after proxy availability is restored.',
              ],
            },
          },
        },
      });
    });

    expect(await screen.findByText(/stage: proxy_unavailable/i)).toBeInTheDocument();
    expect(screen.getByText(/proxy configuration or provider availability must be restored before retrying/i)).toBeInTheDocument();
    expect(screen.getByText(/proxy unavailable/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /resume using open browser/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /open verification browser/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /close profile windows/i })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^resume fresh$/i })).toBeInTheDocument();
  });

  it('renders browser_profile_in_use recovery action and closes the profile windows', async () => {
    const onCloseManualActionWindows = vi.fn();

    const { unmount } = render(
      <ScrapeProgressPanel
        isVisible
        onClose={vi.fn()}
        onCloseManualActionWindows={onCloseManualActionWindows}
      />
    );

    const stream = latestEventSource();
    act(() => {
      stream.emitOpen();
      stream.emitMessage({
        all: {
          'crawl-job-456': {
            crawl_job_id: 'crawl-job-456',
            status: 'manual_action_required',
            category_name: 'Information Technology',
            crawl_mode: 'headed',
            manual_action: {
              stage: 'browser_profile_in_use',
              blocked_url: 'https://jobs.ctgoodjobs.hk/jobs',
              browser_profile_path: 'C:\\profiles\\ctgoodjobs-headed',
              browser_channel: 'msedge',
              instructions: [
                'Close all Edge windows that use the listed automation profile.',
                'Return to the app and click Resume.',
              ],
            },
          },
        },
      });
    });

    expect(await screen.findByText(/stage: browser_profile_in_use/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /close profile windows/i }));
    expect(onCloseManualActionWindows).toHaveBeenCalledWith('crawl-job-456');

    unmount();
  });


  it('does not reconnect after the panel is hidden', () => {
    vi.useFakeTimers();
    const { rerender, unmount } = render(<ScrapeProgressPanel isVisible onClose={vi.fn()} />);

    const stream = latestEventSource();

    act(() => {
      stream.emitError();
    });

    rerender(<ScrapeProgressPanel isVisible={false} onClose={vi.fn()} />);

    act(() => {
      vi.advanceTimersByTime(3000);
    });

    expect(MockEventSource.instances).toHaveLength(1);

    unmount();
    vi.useRealTimers();
  });

  it('calls onClose with "closed" when the server closes the stream', () => {
    const onClose = vi.fn();

    const { unmount } = render(<ScrapeProgressPanel isVisible onClose={onClose} />);

    const stream = latestEventSource();
    act(() => {
      stream.emitOpen();
      stream.emitMessage({ closed: true });
    });

    expect(onClose).toHaveBeenCalledWith('closed');

    unmount();
  });

  it('does not fire recovery timeout after the server has already closed the stream', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-04-30T12:00:00.000Z'));
    const onClose = vi.fn();

    const { unmount } = render(
      <ScrapeProgressPanel
        isVisible
        recoveryStartedAt="2026-04-30T11:59:56.000Z"
        recoveryWindowMs={5000}
        onClose={onClose}
      />
    );

    const stream = latestEventSource();
    act(() => {
      stream.emitOpen();
      stream.emitMessage({ closed: true });
      vi.advanceTimersByTime(2000);
    });

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledWith('closed');

    unmount();
    vi.useRealTimers();
  });

  it('ignores late errors from a stream after it has already closed', () => {
    vi.useFakeTimers();
    const onClose = vi.fn();

    const { unmount } = render(<ScrapeProgressPanel isVisible onClose={onClose} />);

    const stream = latestEventSource();
    act(() => {
      stream.emitOpen();
      stream.emitMessage({ closed: true });
      stream.emitError();
      vi.advanceTimersByTime(3000);
    });

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledWith('closed');
    expect(MockEventSource.instances).toHaveLength(1);

    unmount();
    vi.useRealTimers();
  });

  it('ignores late callbacks from an errored stream before reconnect completes', () => {
    vi.useFakeTimers();

    const { unmount } = render(<ScrapeProgressPanel isVisible onClose={vi.fn()} />);

    const stream = latestEventSource();
    act(() => {
      stream.emitError();
      stream.emitError();
      vi.advanceTimersByTime(3000);
    });

    expect(MockEventSource.instances).toHaveLength(2);

    unmount();
    vi.useRealTimers();
  });

  it('pauses the SSE stream while the page is hidden and reconnects when visible again', () => {
    let isHidden = false;
    vi.spyOn(document, 'hidden', 'get').mockImplementation(() => isHidden);

    const { unmount } = render(<ScrapeProgressPanel isVisible onClose={vi.fn()} />);

    const firstStream = latestEventSource();
    act(() => {
      firstStream.emitOpen();
    });

    expect(MockEventSource.instances).toHaveLength(1);

    act(() => {
      isHidden = true;
      document.dispatchEvent(new Event('visibilitychange'));
    });

    expect(firstStream.close).toHaveBeenCalledTimes(1);
    expect(MockEventSource.instances).toHaveLength(1);

    act(() => {
      isHidden = false;
      document.dispatchEvent(new Event('visibilitychange'));
    });

    expect(MockEventSource.instances).toHaveLength(2);
    expect(latestEventSource()).not.toBe(firstStream);

    unmount();
  });

  it('renders recovery copy while reconnecting without any recovered progress yet', () => {
    vi.useFakeTimers();

    const { unmount } = render(
      <ScrapeProgressPanel
        isVisible
        recoveryStartedAt="2026-04-30T12:00:00.000Z"
        recoveryWindowMs={15000}
        onClose={vi.fn()}
      />
    );

    expect(
      screen.getByText('Reconnecting to active Direct Override...')
    ).toBeInTheDocument();

    unmount();
    vi.useRealTimers();
  });

  it('closes with "recovery_timeout" when the recovery grace window expires without progress', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-04-30T12:00:00.000Z'));
    const onClose = vi.fn();

    const { unmount } = render(
      <ScrapeProgressPanel
        isVisible
        recoveryStartedAt="2026-04-30T11:59:56.000Z"
        recoveryWindowMs={5000}
        onClose={onClose}
      />
    );

    act(() => {
      vi.advanceTimersByTime(999);
    });
    expect(onClose).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(1);
    });

    expect(onClose).toHaveBeenCalledWith('recovery_timeout');

    unmount();
    vi.useRealTimers();
  });

  it('does not close by default when recoveryWindowMs is missing', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-04-30T12:00:00.000Z'));
    const onClose = vi.fn();

    const { unmount } = render(
      <ScrapeProgressPanel
        isVisible
        recoveryStartedAt="2026-04-30T11:59:00.000Z"
        onClose={onClose}
      />
    );

    act(() => {
      vi.advanceTimersByTime(30000);
    });

    expect(onClose).not.toHaveBeenCalled();

    unmount();
    vi.useRealTimers();
  });

  it('does not trigger recovery timeout once progress is already available', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-04-30T12:00:00.000Z'));
    const onClose = vi.fn();

    const { unmount } = render(
      <ScrapeProgressPanel
        isVisible
        initialProgress={{
          engineering: {
            status: 'running',
            category_name: 'Engineering',
            phase: 1,
            current_page: 1,
            total_pages: 4,
            job_ids_collected: 25,
            elapsed_seconds: 5,
            phase_rate: 1.2,
          },
        }}
        recoveryStartedAt="2026-04-30T11:59:50.000Z"
        recoveryWindowMs={5000}
        onClose={onClose}
      />
    );

    act(() => {
      vi.advanceTimersByTime(10000);
    });

    expect(onClose).not.toHaveBeenCalled();

    unmount();
    vi.useRealTimers();
  });

  it('does not reconnect the stream when onClose gets a new function identity', () => {
    const firstOnClose = vi.fn();
    const secondOnClose = vi.fn();
    const { rerender, unmount } = render(
      <ScrapeProgressPanel isVisible onClose={firstOnClose} />
    );

    const firstStream = latestEventSource();

    rerender(<ScrapeProgressPanel isVisible onClose={secondOnClose} />);

    expect(MockEventSource.instances).toHaveLength(1);
    expect(firstStream.close).not.toHaveBeenCalled();

    unmount();
  });
});
