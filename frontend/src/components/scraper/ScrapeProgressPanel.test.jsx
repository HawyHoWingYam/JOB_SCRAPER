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
    expect(screen.getByText(/details completed: 3\/10/i)).toBeInTheDocument();

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
    expect(screen.getByText(/details completed: 4\/12/i)).toBeInTheDocument();

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

  it('shows saved counters during the detail scraping phase', async () => {
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

    expect(await screen.findByText(/details completed: 2\/5/i)).toBeInTheDocument();
    expect(screen.getByText(/saved: 1\/2/i)).toBeInTheDocument();

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
            phase: 2,
            jobs_scraped: 2,
            total_jobs: 12,
            detail_job_index: 3,
            detail_job_total: 12,
            current_job_title: 'Senior Data Analyst',
            jobs_saved: 1,
            save_total: 2,
            elapsed_seconds: 18,
            phase_rate: 1.5,
            eta_seconds: 6,
          },
        },
      });
    });

    expect(await screen.findByText(/details completed: 2\/12/i)).toBeInTheDocument();
    expect(screen.getByText(/current target: 3\/12/i)).toBeInTheDocument();
    expect(screen.getByText(/current title: senior data analyst/i)).toBeInTheDocument();
    expect(screen.getByText(/saved: 1\/2/i)).toBeInTheDocument();
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

    expect(await screen.findByText(/completed with ai failures/i)).toBeInTheDocument();
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
            phase: 4,
            jobs_scraped: 96,
            jobs_saved: 12,
            save_total: 96,
            listings_staged: 96,
            detail_pending: 74,
          },
        },
      });
    });

    expect(await screen.findByText(/downstream backlog/i)).toBeInTheDocument();
    expect(screen.getByText(/ingested: 12\/96/i)).toBeInTheDocument();
    expect(screen.getByText(/pending details: 74/i)).toBeInTheDocument();

    unmount();
  });

  it('renders manual action guidance with a visible browser-launch action and task identity', async () => {
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

    fireEvent.click(screen.getByRole('button', { name: /copy url/i }));
    expect(writeText).toHaveBeenCalledWith(
      'https://jobs.ctgoodjobs.hk/jobs/jobs-in-information-technology?page=52'
    );

    fireEvent.click(screen.getByRole('button', { name: /open verification browser/i }));
    expect(onOpenManualActionBrowser).toHaveBeenCalledWith('crawl-job-123');

    fireEvent.click(screen.getByRole('button', { name: /resume/i }));
    expect(onResumeCrawlJob).toHaveBeenCalledWith('crawl-job-123');

    fireEvent.click(screen.getByRole('button', { name: /cancel/i }));
    expect(onCancelCrawlJob).toHaveBeenCalledWith('crawl-job-123');

    unmount();
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

  it('captures a manual-action screenshot and renders the returned analysis guidance', async () => {
    const onCaptureManualActionAnalysis = vi.fn().mockResolvedValue({
      challenge_type: 'captcha',
      confidence: 0.93,
      summary: 'Visual captcha challenge detected.',
      recommended_actions: [
        'Use the browser window to complete the captcha.',
        'Resume the crawl after the captcha clears.',
      ],
      should_resume: false,
      suggested_action: null,
      auto_apply_supported: false,
      auto_resume_after_action: false,
    });

    const { unmount } = render(
      <ScrapeProgressPanel
        isVisible
        onClose={vi.fn()}
        onCaptureManualActionAnalysis={onCaptureManualActionAnalysis}
      />
    );

    const stream = latestEventSource();
    act(() => {
      stream.emitOpen();
      stream.emitMessage({
        all: {
          'crawl-job-789': {
            crawl_job_id: 'crawl-job-789',
            status: 'manual_action_required',
            source_site: 'ctgoodjobs',
            category_name: 'Information Technology',
            crawl_mode: 'headed',
            manual_action: {
              source_site: 'ctgoodjobs',
              stage: 'category_page',
              blocked_url: 'https://jobs.ctgoodjobs.hk/jobs/jobs-in-information-technology?page=100',
              browser_profile_path: 'C:\\profiles\\ctgoodjobs-headed',
              browser_channel: 'msedge',
              instructions: ['Complete the verification challenge.'],
            },
          },
        },
      });
    });

    fireEvent.click(await screen.findByRole('button', { name: /capture and analyze/i }));

    expect(onCaptureManualActionAnalysis).toHaveBeenCalledWith('crawl-job-789', {
      source_site: 'ctgoodjobs',
      stage: 'category_page',
      blocked_url: 'https://jobs.ctgoodjobs.hk/jobs/jobs-in-information-technology?page=100',
      browser_profile_path: 'C:\\profiles\\ctgoodjobs-headed',
      browser_channel: 'msedge',
      instructions: ['Complete the verification challenge.'],
    });
    expect(await screen.findByText(/challenge type: captcha/i)).toBeInTheDocument();
    expect(screen.getByText(/visual captcha challenge detected/i)).toBeInTheDocument();
    expect(screen.getByText(/use the browser window to complete the captcha/i)).toBeInTheDocument();

    unmount();
  });

  it('applies an auto-supported manual-action fix and resumes the crawl', async () => {
    const onCaptureManualActionAnalysis = vi.fn().mockResolvedValue({
      challenge_type: 'browser_profile_in_use',
      confidence: 0.98,
      summary: 'The automation browser profile is already open in another Edge window.',
      recommended_actions: ['Close the matching profile windows before resuming the crawl.'],
      should_resume: true,
      suggested_action: 'close_profile_windows',
      auto_apply_supported: true,
      auto_resume_after_action: true,
    });
    const onCloseManualActionWindows = vi.fn().mockResolvedValue({ closed_processes: 1 });
    const onResumeCrawlJob = vi.fn().mockResolvedValue({ status: 'dispatching' });

    const { unmount } = render(
      <ScrapeProgressPanel
        isVisible
        onClose={vi.fn()}
        onCaptureManualActionAnalysis={onCaptureManualActionAnalysis}
        onCloseManualActionWindows={onCloseManualActionWindows}
        onResumeCrawlJob={onResumeCrawlJob}
      />
    );

    const stream = latestEventSource();
    act(() => {
      stream.emitOpen();
      stream.emitMessage({
        all: {
          'crawl-job-790': {
            crawl_job_id: 'crawl-job-790',
            status: 'manual_action_required',
            source_site: 'ctgoodjobs',
            category_name: 'Information Technology',
            crawl_mode: 'headed',
            manual_action: {
              source_site: 'ctgoodjobs',
              stage: 'browser_profile_in_use',
              action_type: 'close_browser_window',
              blocked_url: 'https://jobs.ctgoodjobs.hk/jobs',
              browser_profile_path: 'C:\\profiles\\ctgoodjobs-headed',
              browser_channel: 'msedge',
              instructions: ['Close the listed profile windows first.'],
            },
          },
        },
      });
    });

    fireEvent.click(await screen.findByRole('button', { name: /capture and analyze/i }));
    fireEvent.click(await screen.findByRole('button', { name: /apply suggested fix/i }));

    await waitFor(() => {
      expect(onCloseManualActionWindows).toHaveBeenCalledWith('crawl-job-790');
      expect(onResumeCrawlJob).toHaveBeenCalledWith('crawl-job-790');
    });

    unmount();
  });

  it('auto resolves a browser-profile issue with a single button click', async () => {
    const onCaptureManualActionAnalysis = vi.fn().mockResolvedValue({
      challenge_type: 'browser_profile_in_use',
      confidence: 0.98,
      summary: 'The automation browser profile is already open in another Edge window.',
      recommended_actions: ['Close the matching profile windows before resuming the crawl.'],
      should_resume: true,
      suggested_action: 'close_profile_windows',
      auto_apply_supported: true,
      auto_resume_after_action: true,
    });
    const onCloseManualActionWindows = vi.fn().mockResolvedValue({ closed_processes: 1 });
    const onResumeCrawlJob = vi.fn().mockResolvedValue({ status: 'dispatching' });

    const { unmount } = render(
      <ScrapeProgressPanel
        isVisible
        onClose={vi.fn()}
        onCaptureManualActionAnalysis={onCaptureManualActionAnalysis}
        onCloseManualActionWindows={onCloseManualActionWindows}
        onResumeCrawlJob={onResumeCrawlJob}
      />
    );

    const stream = latestEventSource();
    act(() => {
      stream.emitOpen();
      stream.emitMessage({
        all: {
          'crawl-job-791': {
            crawl_job_id: 'crawl-job-791',
            status: 'manual_action_required',
            source_site: 'ctgoodjobs',
            category_name: 'Information Technology',
            crawl_mode: 'headed',
            manual_action: {
              source_site: 'ctgoodjobs',
              stage: 'browser_profile_in_use',
              action_type: 'close_browser_window',
              blocked_url: 'https://jobs.ctgoodjobs.hk/jobs',
              browser_profile_path: 'C:\\profiles\\ctgoodjobs-headed',
              browser_channel: 'msedge',
              instructions: ['Close the listed profile windows first.'],
            },
          },
        },
      });
    });

    fireEvent.click(await screen.findByRole('button', { name: /auto resolve/i }));

    await waitFor(() => {
      expect(onCaptureManualActionAnalysis).toHaveBeenCalledWith('crawl-job-791', {
        source_site: 'ctgoodjobs',
        stage: 'browser_profile_in_use',
        action_type: 'close_browser_window',
        blocked_url: 'https://jobs.ctgoodjobs.hk/jobs',
        browser_profile_path: 'C:\\profiles\\ctgoodjobs-headed',
        browser_channel: 'msedge',
        instructions: ['Close the listed profile windows first.'],
      });
      expect(onCloseManualActionWindows).toHaveBeenCalledWith('crawl-job-791');
      expect(onResumeCrawlJob).toHaveBeenCalledWith('crawl-job-791');
    });

    unmount();
  });

  it('prefers the dedicated auto-resolve handler when one is provided', async () => {
    const onAutoResolveManualAction = vi.fn().mockResolvedValue({
      resolution_status: 'applied_and_resumed',
      analysis: {
        challenge_type: 'browser_profile_in_use',
        suggested_action: 'close_profile_windows',
      },
      applied_actions: ['close_profile_windows', 'resume_crawl_job'],
      crawl_job: { id: 'crawl-job-792', status: 'dispatching' },
    });
    const onCaptureManualActionAnalysis = vi.fn();
    const onCloseManualActionWindows = vi.fn();
    const onResumeCrawlJob = vi.fn();

    const { unmount } = render(
      <ScrapeProgressPanel
        isVisible
        onClose={vi.fn()}
        onAutoResolveManualAction={onAutoResolveManualAction}
        onCaptureManualActionAnalysis={onCaptureManualActionAnalysis}
        onCloseManualActionWindows={onCloseManualActionWindows}
        onResumeCrawlJob={onResumeCrawlJob}
      />
    );

    const stream = latestEventSource();
    act(() => {
      stream.emitOpen();
      stream.emitMessage({
        all: {
          'crawl-job-792': {
            crawl_job_id: 'crawl-job-792',
            status: 'manual_action_required',
            source_site: 'ctgoodjobs',
            category_name: 'Information Technology',
            crawl_mode: 'headed',
            manual_action: {
              source_site: 'ctgoodjobs',
              stage: 'browser_profile_in_use',
              action_type: 'close_browser_window',
              blocked_url: 'https://jobs.ctgoodjobs.hk/jobs',
              browser_profile_path: 'C:\\profiles\\ctgoodjobs-headed',
              browser_channel: 'msedge',
              instructions: ['Close the listed profile windows first.'],
            },
          },
        },
      });
    });

    fireEvent.click(await screen.findByRole('button', { name: /auto resolve/i }));

    await waitFor(() => {
      expect(onAutoResolveManualAction).toHaveBeenCalledWith('crawl-job-792');
    });
    expect(onCaptureManualActionAnalysis).not.toHaveBeenCalled();
    expect(onCloseManualActionWindows).not.toHaveBeenCalled();
    expect(onResumeCrawlJob).not.toHaveBeenCalled();
    expect(screen.getByText(/resolution status: applied_and_resumed/i)).toBeInTheDocument();
    expect(screen.getByText(/applied actions: close_profile_windows, resume_crawl_job/i)).toBeInTheDocument();

    unmount();
  });

  it('renders persisted manual-action resolution details from progress payloads', async () => {
    const { unmount } = render(<ScrapeProgressPanel isVisible onClose={vi.fn()} />);

    const stream = latestEventSource();
    act(() => {
      stream.emitOpen();
      stream.emitMessage({
        all: {
          'crawl-job-793': {
            crawl_job_id: 'crawl-job-793',
            status: 'manual_action_required',
            source_site: 'ctgoodjobs',
            category_name: 'Information Technology',
            crawl_mode: 'headed',
            manual_action: {
              source_site: 'ctgoodjobs',
              stage: 'category_page',
              blocked_url: 'https://jobs.ctgoodjobs.hk/jobs',
            },
            manual_action_resolution: {
              resolution_status: 'opened_browser_for_manual_followup',
              applied_actions: ['open_browser'],
            },
          },
        },
      });
    });

    expect(await screen.findByText(/resolution status: opened_browser_for_manual_followup/i)).toBeInTheDocument();
    expect(screen.getByText(/applied actions: open_browser/i)).toBeInTheDocument();

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
