import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { scrapeProgressPanelSpy } = vi.hoisted(() => ({
  scrapeProgressPanelSpy: vi.fn(),
}));

vi.mock('./ScheduleForm', () => ({
  default: ({ onSubmit, categories, sourceSite, onSourceScopedDirtyChange }) => (
    <div>
      <div>Schedule Form Source: {sourceSite}</div>
      <button
        type="button"
        onClick={() => {
          onSourceScopedDirtyChange?.(true);
          onSubmit({
            name: `${sourceSite} automation`,
            cron_expression: '0 2 * * *',
            crawl_phase: 'listing',
            crawl_mode: 'headed',
            category_ids: categories.slice(0, 1).map((category) => category.id),
            max_pages: 4,
            detail_limit: 100,
          });
        }}
      >
        Submit Schedule Stub
      </button>
    </div>
  ),
}));

vi.mock('./ScheduleHistory', () => ({
  default: () => <div>Schedule History Stub</div>,
}));

vi.mock('./ScrapeProgressPanel', () => ({
  default: (props) => {
    scrapeProgressPanelSpy(props);

    return (
      <div>
        <div>Scrape Progress Stub</div>
        <div data-testid="progress-initial">{JSON.stringify(props.initialProgress ?? null)}</div>
        <div data-testid="progress-recovery-started-at">{props.recoveryStartedAt ?? ''}</div>
        <div data-testid="progress-recovery-window">{String(props.recoveryWindowMs ?? '')}</div>
        <div data-testid="progress-has-resume-handler">
          {String(typeof props.onResumeCrawlJob === 'function')}
        </div>
        <div data-testid="progress-has-cancel-handler">
          {String(typeof props.onCancelCrawlJob === 'function')}
        </div>
        <div data-testid="progress-has-open-browser-handler">
          {String(typeof props.onOpenManualActionBrowser === 'function')}
        </div>
        <div data-testid="progress-has-close-windows-handler">
          {String(typeof props.onCloseManualActionWindows === 'function')}
        </div>
        <div data-testid="progress-has-reuse-status-handler">
          {String(typeof props.onGetManualActionReuseStatus === 'function')}
        </div>
        <button
          type="button"
          onClick={() => props.onResumeCrawlJob?.('crawl-job-123', 'reuse_open_browser')}
        >
          Resume Reuse Progress Stub
        </button>
        <button
          type="button"
          onClick={() => props.onResumeCrawlJob?.('crawl-job-123', 'fresh_profile')}
        >
          Resume Fresh Progress Stub
        </button>
        <button type="button" onClick={() => props.onCancelCrawlJob?.('crawl-job-123')}>
          Cancel Progress Stub
        </button>
        <button type="button" onClick={() => props.onOpenManualActionBrowser?.('crawl-job-123')}>
          Open Browser Progress Stub
        </button>
        <button type="button" onClick={() => props.onGetManualActionReuseStatus?.('crawl-job-123')}>
          Reuse Status Progress Stub
        </button>
        <button type="button" onClick={() => props.onCloseManualActionWindows?.('crawl-job-123')}>
          Close Windows Progress Stub
        </button>
        <button type="button" onClick={() => props.onClose?.('manual_close')}>
          Close Progress Stub
        </button>
      </div>
    );
  },
}));

import ScheduleManager from './ScheduleManager';

const FIXED_NOW = new Date('2026-04-30T08:00:00.000Z').getTime();
const DIRECT_OVERRIDE_MARKER_KEY = 'scheduler.directOverrideRun';

function mockJsonResponse(payload) {
  return Promise.resolve({
    ok: true,
    json: async () => payload,
  });
}

function createDeferred() {
  let resolve;
  let reject;

  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });

  return { promise, resolve, reject };
}

const JOBSDB_CATEGORIES = [{ id: 1200, name: 'Engineering' }];
const CTGOODJOBS_CATEGORIES = [{ id: 'ctgoodjobs:021', name: 'Information Technology' }];
const MIXED_SCHEDULES = [
  {
    id: 'jobsdb-nightly',
    name: 'JobsDB Nightly',
    cron_expression: '0 2 * * *',
    category_ids: [1200],
    source_site: 'jobsdb',
    is_active: true,
    last_run_at: null,
    next_run_at: null,
  },
  {
    id: 'ctgoodjobs-nightly',
    name: 'CTgoodjobs Nightly',
    cron_expression: '0 2 * * *',
    category_ids: ['ctgoodjobs:021'],
    source_site: 'ctgoodjobs',
    is_active: true,
    last_run_at: null,
    next_run_at: null,
  },
];

function createFetchMock({
  schedules = MIXED_SCHEDULES,
  jobsdbCategories = JOBSDB_CATEGORIES,
  ctgoodjobsCategories = CTGOODJOBS_CATEGORIES,
  ctgoodjobsCategoryErrorDetail = null,
  capabilities = { scheduler: { available: true, manual_run_available: true, owner: 'scheduler-worker', worker_name: 'scheduler-worker', heartbeat_status: 'fresh', reason: null } },
  listingBatches = [],
  scrapeProgress = { active: {}, all: {}, has_active: false },
  scrapeProgressError = null,
  crawlJobId = 'crawl-job-123',
} = {}) {
  return vi.fn((input, init) => {
    const url = String(input);

    if (url === '/api/v1/schedules') {
      return mockJsonResponse({ schedules });
    }

    if (url === '/api/categories') {
      return mockJsonResponse({ categories: jobsdbCategories });
    }

    if (url === '/api/categories?source_site=jobsdb') {
      return mockJsonResponse({ categories: jobsdbCategories });
    }

    if (url === '/api/categories?source_site=ctgoodjobs') {
      if (ctgoodjobsCategoryErrorDetail) {
        return Promise.resolve({
          ok: false,
          json: async () => ({ detail: ctgoodjobsCategoryErrorDetail }),
        });
      }
      return mockJsonResponse({ categories: ctgoodjobsCategories });
    }

    if (url === '/api/v1/scrape/progress') {
      if (scrapeProgressError) {
        return Promise.reject(scrapeProgressError);
      }

      return mockJsonResponse(scrapeProgress);
    }

    if (url === '/api/v1/capabilities') {
      return mockJsonResponse(capabilities);
    }

    if (url.startsWith('/api/v1/crawl-jobs/listing-batches')) {
      return mockJsonResponse({ batches: listingBatches });
    }

    if (url === '/api/v1/crawl-jobs' && init?.method === 'POST') {
      return mockJsonResponse({ id: crawlJobId, status: 'queued' });
    }

    if (/^\/api\/v1\/schedules\/[^/]+\/run$/.test(url) && init?.method === 'POST') {
      return mockJsonResponse({ id: crawlJobId, status: 'queued' });
    }

    if (url === '/api/v1/crawl-jobs/crawl-job-123/resume' && init?.method === 'POST') {
      return mockJsonResponse({ id: 'crawl-job-123', status: 'dispatching' });
    }

    if (url === '/api/v1/crawl-jobs/crawl-job-123/cancel' && init?.method === 'POST') {
      return mockJsonResponse({ id: 'crawl-job-123', status: 'cancelled' });
    }

    if (url === 'http://127.0.0.1:47652/manual-actions/open-browser' && init?.method === 'POST') {
      return mockJsonResponse({ browser_channel: 'msedge' });
    }

    if (url === 'http://127.0.0.1:47652/manual-actions/reuse-status' && init?.method === 'POST') {
      return mockJsonResponse({
        available: true,
        reuse_open_browser_supported: true,
        live_session: { browser_channel: 'msedge' },
      });
    }

    if (url === 'http://127.0.0.1:47652/manual-actions/close-profile-windows' && init?.method === 'POST') {
      return mockJsonResponse({ closed_processes: 1 });
    }

    if (url === '/api/v1/schedules' && init?.method === 'POST') {
      return mockJsonResponse({ id: 'created-schedule' });
    }

    return Promise.reject(new Error(`Unhandled fetch: ${url}`));
  });
}

describe('ScheduleManager', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', createFetchMock());

    vi.spyOn(window, 'confirm').mockReturnValue(true);
    vi.spyOn(Date, 'now').mockReturnValue(FIXED_NOW);
    sessionStorage.clear();
    scrapeProgressPanelSpy.mockClear();
  });

  afterEach(() => {
    sessionStorage.clear();
    vi.restoreAllMocks();
  });

  it('loads jobsdb categories by default and only renders jobsdb schedules', async () => {
    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith('/api/categories?source_site=jobsdb');
    });

    expect(await screen.findByRole('heading', { name: /scheduled automation/i })).toBeInTheDocument();
    expect(screen.getByText(/immediate run for backlog recovery/i)).toBeInTheDocument();
    expect(await screen.findByText('JobsDB Nightly')).toBeInTheDocument();
    expect(screen.queryByText('CTgoodjobs Nightly')).not.toBeInTheDocument();
  });

  it('switches source, reloads categories, and filters the list to ctgoodjobs', async () => {
    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    fireEvent.change(screen.getByRole('combobox', { name: /data source/i }), {
      target: { value: 'ctgoodjobs' },
    });

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith('/api/categories?source_site=ctgoodjobs');
    });

    expect(await screen.findByText('CTgoodjobs Nightly')).toBeInTheDocument();
    expect(screen.queryByText('JobsDB Nightly')).not.toBeInTheDocument();
  });

  it('shows backend category error detail when ctgoodjobs categories fail to load', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.stubGlobal(
      'fetch',
      createFetchMock({
        ctgoodjobsCategoryErrorDetail: 'CTgoodjobs category registry unavailable',
      }),
    );

    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    fireEvent.change(screen.getByRole('combobox', { name: /data source/i }), {
      target: { value: 'ctgoodjobs' },
    });

    expect(await screen.findByText('CTgoodjobs category registry unavailable')).toBeInTheDocument();
  });

  it('shows a scheduler warning when runtime capabilities report scheduler dispatch unavailable', async () => {
    vi.stubGlobal(
      'fetch',
      createFetchMock({
        capabilities: {
          scheduler: {
            available: false,
            manual_run_available: false,
            owner: 'scheduler-worker',
            worker_name: 'scheduler-worker',
            heartbeat_status: 'missing',
            reason: 'scheduler_not_running',
          },
        },
      }),
    );

    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    expect(
      await screen.findByText('Scheduler dispatch is unavailable in the current runtime profile.'),
    ).toBeInTheDocument();
  });

  it('disables manual and scheduled controls when runtime capabilities explicitly disable scheduler dispatch', async () => {
    vi.stubGlobal(
      'fetch',
      createFetchMock({
        capabilities: {
          scheduler: {
            available: false,
            manual_run_available: false,
            owner: 'scheduler-worker',
            worker_name: 'scheduler-worker',
            heartbeat_status: 'missing',
            reason: 'scheduler_not_running',
          },
        },
      }),
    );

    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    expect(
      await screen.findByText('Scheduler dispatch is unavailable in the current runtime profile.'),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /new automation/i })).toBeDisabled();
    expect(screen.getAllByRole('button', { name: /run now/i })[0]).toBeDisabled();
    expect(screen.getByRole('button', { name: /direct override/i })).toBeDisabled();
  });

  it('keeps manual actions available when the scheduler worker heartbeat is stale', async () => {
    vi.stubGlobal(
      'fetch',
      createFetchMock({
        capabilities: {
          scheduler: {
            available: false,
            manual_run_available: true,
            owner: 'scheduler-worker',
            worker_name: 'scheduler-worker',
            heartbeat_status: 'stale',
            last_heartbeat_at: '2026-05-21T23:58:00+00:00',
            reason: 'scheduler_worker_stale',
          },
        },
      }),
    );

    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    expect(await screen.findByText(/manual runs are still available/i)).toBeInTheDocument();
    expect(screen.getByText(/scheduler owner: scheduler-worker/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /new automation/i })).toBeDisabled();
    expect(screen.getAllByRole('button', { name: /run now/i })[0]).not.toBeDisabled();
    expect(screen.getByRole('button', { name: /direct override/i })).not.toBeDisabled();

    fireEvent.click(screen.getAllByRole('button', { name: /run now/i })[0]);

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith('/api/v1/schedules/jobsdb-nightly/run', {
        method: 'POST',
      });
    });
  });

  it('posts jobsdb crawl-job payloads with integer category ids and source_site', async () => {
    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await screen.findByText('Task Control Board');
    fireEvent.click(screen.getByRole('button', { name: /direct override/i }));
    const summaryPanel = screen.getByText(/this run will start a job id crawl/i).closest('.override-summary-panel');
    expect(summaryPanel).not.toBeNull();
    expect(within(summaryPanel).getByText(/^JobsDB$/i)).toBeInTheDocument();
    expect(screen.getByText(/0 sectors selected/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('checkbox', { name: /engineering/i }));
    expect(screen.getByText(/1 sector selected/i)).toBeInTheDocument();
    expect(screen.getByText(/3 pages per sector/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /start job id crawl/i }));

    await waitFor(() => {
      const crawlJobCall = globalThis.fetch.mock.calls.find(
        ([url, request]) => url === '/api/v1/crawl-jobs' && request?.method === 'POST',
      );

      expect(crawlJobCall).toBeTruthy();
      expect(JSON.parse(crawlJobCall[1].body)).toEqual({
        source_site: 'jobsdb',
        crawl_phase: 'listing',
        crawl_mode: 'headed',
        category_ids: [1200],
        max_pages: 3,
        detail_limit: 100,
        skip_existing: true,
      });
    });
  });

  it('stores a direct override session marker and opens progress with recovery props after launch', async () => {
    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await screen.findByText('Task Control Board');
    fireEvent.click(screen.getByRole('button', { name: /direct override/i }));
    fireEvent.click(screen.getByRole('checkbox', { name: /engineering/i }));
    fireEvent.click(screen.getByRole('button', { name: /start job id crawl/i }));

    await screen.findByText('Scrape Progress Stub');

    expect(JSON.parse(sessionStorage.getItem(DIRECT_OVERRIDE_MARKER_KEY))).toEqual({
      crawlJobId: 'crawl-job-123',
      sourceSite: 'jobsdb',
      startedAt: new Date(FIXED_NOW).toISOString(),
    });
    expect(screen.queryByText('Direct Override Sequence')).not.toBeInTheDocument();
    expect(screen.getByTestId('progress-initial')).toHaveTextContent('{}');
    expect(screen.getByTestId('progress-recovery-started-at')).toHaveTextContent(
      new Date(FIXED_NOW).toISOString(),
    );
    expect(screen.getByTestId('progress-recovery-window')).toHaveTextContent('20000');
  });

  it('posts ctgoodjobs crawl-job payloads with string category ids and source_site', async () => {
    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    fireEvent.change(screen.getByRole('combobox', { name: /data source/i }), {
      target: { value: 'ctgoodjobs' },
    });
    fireEvent.click(screen.getByRole('button', { name: /direct override/i }));
    fireEvent.click(await screen.findByRole('checkbox', { name: /information technology/i }));
    fireEvent.click(screen.getByRole('button', { name: /start job id crawl/i }));

    await waitFor(() => {
      const crawlJobCall = globalThis.fetch.mock.calls.find(
        ([url, request]) => url === '/api/v1/crawl-jobs' && request?.method === 'POST',
      );

      expect(crawlJobCall).toBeTruthy();
      expect(JSON.parse(crawlJobCall[1].body)).toEqual({
        source_site: 'ctgoodjobs',
        crawl_phase: 'listing',
        crawl_mode: 'headed',
        category_ids: ['ctgoodjobs:021'],
        max_pages: 3,
        detail_limit: 100,
        skip_existing: true,
      });
    });
  });

  it('restores the progress panel from active scrape progress on mount', async () => {
    vi.stubGlobal(
      'fetch',
      createFetchMock({
        scrapeProgress: {
          active: { 1200: { status: 'running' } },
          all: {
            1200: { status: 'running', category_name: 'Engineering', phase: 2, total_jobs: 5 },
          },
          has_active: true,
        },
      }),
    );

    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await screen.findByText('Scrape Progress Stub');

    expect(screen.getByTestId('progress-initial')).toHaveTextContent(
      JSON.stringify({
        1200: { status: 'running', category_name: 'Engineering', phase: 2, total_jobs: 5 },
      }),
    );
    expect(screen.getByTestId('progress-recovery-started-at')).toHaveTextContent('');
  });

  it('passes manual-action handlers into the scrape progress panel', async () => {
    vi.stubGlobal(
      'fetch',
      createFetchMock({
        scrapeProgress: {
          active: { 'crawl-job-123': { status: 'manual_action_required' } },
          all: {
            'crawl-job-123': {
              crawl_job_id: 'crawl-job-123',
              status: 'manual_action_required',
              category_name: 'Engineering',
              crawl_mode: 'headed',
            },
          },
          has_active: true,
        },
      }),
    );

    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await screen.findByText('Scrape Progress Stub');

    expect(screen.getByTestId('progress-has-resume-handler')).toHaveTextContent('true');
    expect(screen.getByTestId('progress-has-cancel-handler')).toHaveTextContent('true');
    expect(screen.getByTestId('progress-has-open-browser-handler')).toHaveTextContent('true');
    expect(screen.getByTestId('progress-has-close-windows-handler')).toHaveTextContent('true');
    expect(screen.getByTestId('progress-has-reuse-status-handler')).toHaveTextContent('true');
  });

  it('posts progress action requests when the progress panel invokes its handlers', async () => {
    vi.stubGlobal(
      'fetch',
      createFetchMock({
        scrapeProgress: {
          active: { 'crawl-job-123': { status: 'manual_action_required' } },
          all: {
            'crawl-job-123': {
              crawl_job_id: 'crawl-job-123',
              status: 'manual_action_required',
              category_name: 'Engineering',
              crawl_mode: 'headed',
            },
          },
          has_active: true,
        },
      }),
    );

    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await screen.findByText('Scrape Progress Stub');

    fireEvent.click(screen.getByRole('button', { name: /resume reuse progress stub/i }));
    fireEvent.click(screen.getByRole('button', { name: /resume fresh progress stub/i }));
    fireEvent.click(screen.getByRole('button', { name: /cancel progress stub/i }));
    fireEvent.click(screen.getByRole('button', { name: /open browser progress stub/i }));
    fireEvent.click(screen.getByRole('button', { name: /reuse status progress stub/i }));
    fireEvent.click(screen.getByRole('button', { name: /close windows progress stub/i }));

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith('/api/v1/crawl-jobs/crawl-job-123/resume', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ strategy: 'reuse_open_browser' }),
      });
      expect(globalThis.fetch).toHaveBeenCalledWith('/api/v1/crawl-jobs/crawl-job-123/resume', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ strategy: 'fresh_profile' }),
      });
      expect(globalThis.fetch).toHaveBeenCalledWith('/api/v1/crawl-jobs/crawl-job-123/cancel', {
        method: 'POST',
      });
      expect(globalThis.fetch).toHaveBeenCalledWith('http://127.0.0.1:47652/manual-actions/open-browser', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ crawl_job_id: 'crawl-job-123' }),
      });
      expect(globalThis.fetch).toHaveBeenCalledWith(
        'http://127.0.0.1:47652/manual-actions/reuse-status',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ crawl_job_id: 'crawl-job-123' }),
        },
      );
      expect(globalThis.fetch).toHaveBeenCalledWith(
        'http://127.0.0.1:47652/manual-actions/close-profile-windows',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ crawl_job_id: 'crawl-job-123' }),
        },
      );
    });
  });

  it('surfaces helper-specific copy when the manual-action helper is unavailable', async () => {
    const baseFetch = createFetchMock({
      scrapeProgress: {
        active: { 'crawl-job-123': { status: 'manual_action_required' } },
        all: {
          'crawl-job-123': {
            crawl_job_id: 'crawl-job-123',
            status: 'manual_action_required',
            category_name: 'Engineering',
            crawl_mode: 'headed',
          },
        },
        has_active: true,
      },
    });

    vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.stubGlobal(
      'fetch',
      vi.fn((input, init) => {
        const url = String(input);
        if (url === 'http://127.0.0.1:47652/manual-actions/open-browser' && init?.method === 'POST') {
          return Promise.reject(new TypeError('Failed to fetch'));
        }
        return baseFetch(input, init);
      }),
    );

    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await screen.findByText('Scrape Progress Stub');
    fireEvent.click(screen.getByRole('button', { name: /open browser progress stub/i }));

    expect(await screen.findByText(/manual-action helper is unavailable/i)).toBeInTheDocument();
  });

  it('restores recovery mode on mount when progress is empty but the marker is fresh', async () => {
    const startedAt = new Date(FIXED_NOW - 10_000).toISOString();
    sessionStorage.setItem(
      DIRECT_OVERRIDE_MARKER_KEY,
      JSON.stringify({ crawlJobId: 'crawl-job-123', sourceSite: 'jobsdb', startedAt }),
    );

    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await screen.findByText('Scrape Progress Stub');

    expect(screen.getByTestId('progress-initial')).toHaveTextContent('{}');
    expect(screen.getByTestId('progress-recovery-started-at')).toHaveTextContent(startedAt);
    expect(sessionStorage.getItem(DIRECT_OVERRIDE_MARKER_KEY)).not.toBeNull();
  });

  it('does not restore recovery mode for a stale marker and clears storage', async () => {
    sessionStorage.setItem(
      DIRECT_OVERRIDE_MARKER_KEY,
      JSON.stringify({
        crawlJobId: 'crawl-job-123',
        sourceSite: 'jobsdb',
        startedAt: new Date(FIXED_NOW - 20_001).toISOString(),
      }),
    );

    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await waitFor(() => {
      expect(screen.queryByText('Scrape Progress Stub')).not.toBeInTheDocument();
      expect(sessionStorage.getItem(DIRECT_OVERRIDE_MARKER_KEY)).toBeNull();
    });
  });

  it('restores recovery mode when progress bootstrap fails but the marker is fresh', async () => {
    const startedAt = new Date(FIXED_NOW - 5_000).toISOString();
    vi.spyOn(console, 'error').mockImplementation(() => {});
    sessionStorage.setItem(
      DIRECT_OVERRIDE_MARKER_KEY,
      JSON.stringify({ crawlJobId: 'crawl-job-123', sourceSite: 'jobsdb', startedAt }),
    );
    vi.stubGlobal(
      'fetch',
      createFetchMock({
        scrapeProgressError: new Error('network down'),
      }),
    );

    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await screen.findByText('Scrape Progress Stub');

    expect(screen.getByTestId('progress-initial')).toHaveTextContent('{}');
    expect(screen.getByTestId('progress-recovery-started-at')).toHaveTextContent(startedAt);
  });

  it('does not wipe a newer recovery state when an in-flight bootstrap finishes after crawl-job success', async () => {
    const progressDeferred = createDeferred();
    vi.stubGlobal(
      'fetch',
      vi.fn((input, init) => {
        const url = String(input);

        if (url === '/api/v1/scrape/progress') {
          return progressDeferred.promise;
        }

        return createFetchMock()(input, init);
      }),
    );

    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await screen.findByText('Task Control Board');
    fireEvent.click(screen.getByRole('button', { name: /direct override/i }));
    fireEvent.click(screen.getByRole('checkbox', { name: /engineering/i }));
    fireEvent.click(screen.getByRole('button', { name: /start job id crawl/i }));

    await screen.findByText('Scrape Progress Stub');

    await act(async () => {
      progressDeferred.resolve({
        ok: true,
        json: async () => ({ active: {}, all: {}, has_active: false }),
      });
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByText('Scrape Progress Stub')).toBeInTheDocument();
    expect(screen.getByTestId('progress-recovery-started-at')).toHaveTextContent(
      new Date(FIXED_NOW).toISOString(),
    );
    expect(JSON.parse(sessionStorage.getItem(DIRECT_OVERRIDE_MARKER_KEY))).toEqual({
      crawlJobId: 'crawl-job-123',
      sourceSite: 'jobsdb',
      startedAt: new Date(FIXED_NOW).toISOString(),
    });
  });

  it('still shows progress after crawl-job success when sessionStorage.setItem throws', async () => {
    const originalSetItem = Storage.prototype.setItem;
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(function setItem(key, value) {
      if (key === DIRECT_OVERRIDE_MARKER_KEY) {
        throw new Error('storage unavailable');
      }

      return Reflect.apply(originalSetItem, this, [key, value]);
    });

    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await screen.findByText('Task Control Board');
    fireEvent.click(screen.getByRole('button', { name: /direct override/i }));
    fireEvent.click(screen.getByRole('checkbox', { name: /engineering/i }));
    fireEvent.click(screen.getByRole('button', { name: /start job id crawl/i }));

    await screen.findByText('Scrape Progress Stub');

    expect(screen.getByTestId('progress-recovery-started-at')).toHaveTextContent(
      new Date(FIXED_NOW).toISOString(),
    );
    expect(screen.queryByText('storage unavailable')).not.toBeInTheDocument();
    expect(screen.queryByText('Direct Override Sequence')).not.toBeInTheDocument();
  });

  it('clears the stored marker and hides the progress panel when the panel closes', async () => {
    const startedAt = new Date(FIXED_NOW - 5_000).toISOString();
    sessionStorage.setItem(
      DIRECT_OVERRIDE_MARKER_KEY,
      JSON.stringify({ crawlJobId: 'crawl-job-123', sourceSite: 'jobsdb', startedAt }),
    );

    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await screen.findByText('Scrape Progress Stub');
    fireEvent.click(screen.getByRole('button', { name: /close progress stub/i }));

    await waitFor(() => {
      expect(screen.queryByText('Scrape Progress Stub')).not.toBeInTheDocument();
      expect(sessionStorage.getItem(DIRECT_OVERRIDE_MARKER_KEY)).toBeNull();
    });
  });

  it('shows an interrupted-run banner when recovery mode times out', async () => {
    const startedAt = new Date(FIXED_NOW - 5_000).toISOString();
    sessionStorage.setItem(
      DIRECT_OVERRIDE_MARKER_KEY,
      JSON.stringify({ crawlJobId: 'crawl-job-123', sourceSite: 'jobsdb', startedAt }),
    );

    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await screen.findByText('Scrape Progress Stub');

    const latestProps = scrapeProgressPanelSpy.mock.calls.at(-1)?.[0];
    expect(latestProps).toBeTruthy();

    await act(async () => {
      latestProps.onClose?.('recovery_timeout');
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(screen.queryByText('Scrape Progress Stub')).not.toBeInTheDocument();
    });
    expect(screen.getByText(/direct override recovery timed out after reconnecting/i)).toBeInTheDocument();
    expect(screen.getByText(/the run was likely interrupted by a restart or connection loss/i)).toBeInTheDocument();
  });

  it('includes source_site when creating schedules', async () => {
    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    fireEvent.change(screen.getByRole('combobox', { name: /data source/i }), {
      target: { value: 'ctgoodjobs' },
    });
    fireEvent.click(screen.getByRole('button', { name: /new automation/i }));
    fireEvent.click(await screen.findByRole('button', { name: /submit schedule stub/i }));

    await waitFor(() => {
      const createCall = globalThis.fetch.mock.calls.find(
        ([url, request]) => url === '/api/v1/schedules' && request?.method === 'POST',
      );

      expect(createCall).toBeTruthy();
      expect(JSON.parse(createCall[1].body)).toEqual({
        name: 'ctgoodjobs automation',
        cron_expression: '0 2 * * *',
        source_site: 'ctgoodjobs',
        crawl_phase: 'listing',
        crawl_mode: 'headed',
        category_ids: ['ctgoodjobs:021'],
        max_pages: 4,
        detail_limit: 100,
      });
    });
  });

  it('posts detail crawl payloads with detail_limit and selected listing batch id', async () => {
    vi.stubGlobal(
      'fetch',
      createFetchMock({
        listingBatches: [
          {
            crawl_job_id: '11111111-1111-4111-8111-111111111111',
            source_site: 'jobsdb',
            status: 'completed',
            category_ids: [1200],
            queued_at: '2026-05-21T08:17:57Z',
            completed_at: '2026-05-21T08:18:57Z',
            listings_staged: 96,
            detail_pending: 74,
            detail_running: 0,
            detail_completed: 22,
            detail_failed: 0,
            detail_manual_action_required: 0,
          },
        ],
      }),
    );

    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await screen.findByText('Task Control Board');
    fireEvent.click(screen.getByRole('button', { name: /direct override/i }));
    fireEvent.change(screen.getByRole('combobox', { name: /crawl phase/i }), {
      target: { value: 'detail' },
    });
    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/api/v1/crawl-jobs/listing-batches?source_site=jobsdb&limit=20',
      );
    });
    fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '250' } });
    fireEvent.change(screen.getByRole('combobox', { name: /listing batch/i }), {
      target: { value: '11111111-1111-4111-8111-111111111111' },
    });
    expect(
      screen.getByText(/this run will recover detail backlog from the selected source and sectors/i)
    ).toBeInTheDocument();
    expect(screen.getByText(/up to 250 job details to crawl/i)).toBeInTheDocument();
    expect(screen.getByText(/eligible backlog: pending, failed, manual review/i)).toBeInTheDocument();
    expect(screen.getByText(/sectors: none selected/i)).toBeInTheDocument();
    expect(
      screen.getByText(/legacy batch filter: jobsdb batch 11111111-1111-4111-8111-111111111111/i)
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /start job detail crawl/i }));

    await waitFor(() => {
      const crawlJobCall = globalThis.fetch.mock.calls.find(
        ([url, request]) => url === '/api/v1/crawl-jobs' && request?.method === 'POST',
      );

      expect(crawlJobCall).toBeTruthy();
      expect(JSON.parse(crawlJobCall[1].body)).toEqual({
        source_site: 'jobsdb',
        crawl_phase: 'detail',
        crawl_mode: 'headed',
        category_ids: [],
        max_pages: 3,
        detail_limit: 250,
        source_listing_crawl_job_id: '11111111-1111-4111-8111-111111111111',
        skip_existing: true,
      });
    });
  });

  it('shows detail backlog guidance with selected listing batch counts', async () => {
    vi.stubGlobal(
      'fetch',
      createFetchMock({
        listingBatches: [
          {
            crawl_job_id: '11111111-1111-4111-8111-111111111111',
            source_site: 'jobsdb',
            status: 'completed',
            category_ids: [1200],
            queued_at: '2026-05-21T08:17:57Z',
            completed_at: '2026-05-21T08:18:57Z',
            listings_staged: 96,
            detail_pending: 74,
            detail_running: 0,
            detail_completed: 22,
            detail_failed: 0,
            detail_manual_action_required: 0,
          },
        ],
      }),
    );

    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await screen.findByText('Task Control Board');
    fireEvent.click(screen.getByRole('button', { name: /direct override/i }));
    fireEvent.change(screen.getByRole('combobox', { name: /crawl phase/i }), {
      target: { value: 'detail' },
    });

    expect(await screen.findByText(/category-scoped backlog recovery/i)).toBeInTheDocument();
    expect(
      screen.getByText(/recover pending, failed, and manual-review detail backlog/i)
    ).toBeInTheDocument();
    expect(
      screen.getByRole('option', { name: /jobsdb batch 11111111-1111-4111-8111-111111111111/i })
    ).toBeInTheDocument();

    fireEvent.change(screen.getByRole('combobox', { name: /listing batch/i }), {
      target: { value: '11111111-1111-4111-8111-111111111111' },
    });

    expect(screen.getAllByText(/jobsdb batch 11111111-1111-4111-8111-111111111111/i).length).toBeGreaterThan(0);
    expect(screen.getByText('74 pending')).toBeInTheDocument();
    expect(screen.getByText('96 staged')).toBeInTheDocument();
    expect(screen.getByText('22 completed')).toBeInTheDocument();
  });

  it('renders source-specific empty copy when the current source has no schedules', async () => {
    vi.stubGlobal(
      'fetch',
      createFetchMock({
        schedules: [MIXED_SCHEDULES[0]],
      }),
    );

    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    fireEvent.change(screen.getByRole('combobox', { name: /data source/i }), {
      target: { value: 'ctgoodjobs' },
    });

    expect(await screen.findByText('No CTgoodjobs automated tasks')).toBeInTheDocument();
  });

  it('shows a source badge on each rendered schedule card', async () => {
    vi.stubGlobal(
      'fetch',
      createFetchMock({
        schedules: [
          {
            id: 'jobsdb-neutral',
            name: 'Nightly Import',
            cron_expression: '0 2 * * *',
            category_ids: [1200],
            source_site: 'jobsdb',
            is_active: true,
            last_run_at: null,
            next_run_at: null,
          },
        ],
      }),
    );

    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    const scheduleTitle = await screen.findByText('Nightly Import');
    const scheduleCard = scheduleTitle.closest('.schedule-card');

    expect(scheduleCard).not.toBeNull();
    expect(within(scheduleCard).getByText('JobsDB')).toBeInTheDocument();
  });
});
