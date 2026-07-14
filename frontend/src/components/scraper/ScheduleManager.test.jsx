import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { scrapeProgressPanelSpy } = vi.hoisted(() => ({
  scrapeProgressPanelSpy: vi.fn(),
}));

const { monitoringSpies } = vi.hoisted(() => ({
  monitoringSpies: {
    createMonitoringId: vi.fn(() => 'req-fixed'),
    logError: vi.fn(),
  },
}));

vi.mock('../../monitoring', () => monitoringSpies);

vi.mock('./ScheduleForm', () => ({
  default: ({ onSubmit, categories, sourceSite, onSourceScopedDirtyChange, sourceCatalog = {} }) => (
    <div>
      <div>Schedule Form Source: {sourceSite}</div>
      <div>Schedule Form Source Label: {sourceCatalog[sourceSite]?.label ?? ''}</div>
      <div>
        Schedule Form Source Modes: {(sourceCatalog[sourceSite]?.supported_crawl_modes ?? []).join(',')}
      </div>
      <div>
        Schedule Form Source Default Max Pages: {String(sourceCatalog[sourceSite]?.default_max_pages ?? '')}
      </div>
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
  default: ({ scheduleName, executions = [], onClose }) => (
    <div>
      <div>Schedule History Stub</div>
      <div data-testid="history-schedule-name">{scheduleName}</div>
      <div data-testid="history-execution-count">{String(executions.length)}</div>
      <button type="button" onClick={onClose}>
        Close History Stub
      </button>
    </div>
  ),
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
        <button
          type="button"
          onClick={() => {
            Promise.resolve(props.onOpenManualActionBrowser?.('crawl-job-123')).catch(() => {});
          }}
        >
          Open Browser Progress Stub
        </button>
        <button
          type="button"
          onClick={() => {
            Promise.resolve(props.onGetManualActionReuseStatus?.('crawl-job-123')).catch(() => {});
          }}
        >
          Reuse Status Progress Stub
        </button>
        <button
          type="button"
          onClick={() => {
            Promise.resolve(props.onCloseManualActionWindows?.('crawl-job-123')).catch(() => {});
          }}
        >
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

function mockErrorResponse(detail, status = 500) {
  return Promise.resolve({
    ok: false,
    status,
    json: async () => ({ detail }),
  });
}

async function waitForSourceCatalogOptions() {
  await waitFor(() => {
    expect(screen.getByRole('option', { name: SOURCE_CATALOG.jobsdb.label })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: SOURCE_CATALOG.ctgoodjobs.label })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: SOURCE_CATALOG.offertoday.label })).toBeInTheDocument();
  });
}

function changeSource(sourceSite) {
  fireEvent.change(screen.getByRole('combobox', { name: /data source/i }), {
    target: { value: sourceSite },
  });
}

function expectFetchCalledWithUrl(url) {
  expect(globalThis.fetch.mock.calls.some(([input]) => input === url)).toBe(true);
}

function getFetchCallsForUrl(url) {
  return globalThis.fetch.mock.calls.filter(([input]) => input === url);
}

function getHeaderValue(headers, name) {
  if (headers instanceof Headers) {
    return headers.get(name);
  }

  if (!headers || typeof headers !== 'object') {
    return null;
  }

  return headers[name] || headers[name.toLowerCase()] || null;
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
const OFFERTODAY_CATEGORIES = [{ id: 118000, name: 'Information Technology' }];
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

const SOURCE_CATALOG = {
  jobsdb: {
    supported_crawl_modes: ['headless', 'headed'],
    default_crawl_mode: 'headed',
    default_max_pages: 3,
    label: 'JobsDB Live',
  },
  ctgoodjobs: {
    supported_crawl_modes: ['headed'],
    default_crawl_mode: 'headed',
    default_max_pages: 3,
    label: 'CTGoodJobs Live',
  },
  offertoday: {
    supported_crawl_modes: ['headless', 'headed'],
    default_crawl_mode: 'headless',
    default_max_pages: 50,
    label: 'OfferToday Live',
  },
};

function createFetchMock({
  schedules = MIXED_SCHEDULES,
  jobsdbCategories = JOBSDB_CATEGORIES,
  ctgoodjobsCategories = CTGOODJOBS_CATEGORIES,
  offertodayCategories = OFFERTODAY_CATEGORIES,
  ctgoodjobsCategoryErrorDetail = null,
  capabilities = null,
  capabilitiesError = null,
  listingBatches = [],
  listingBatchesError = null,
  scrapeProgress = { active: {}, all: {}, has_active: false },
  scrapeProgressError = null,
  schedulesErrorDetail = null,
  createScheduleErrorDetail = null,
  toggleScheduleErrorDetail = null,
  deleteScheduleErrorDetail = null,
  runScheduleErrorDetail = null,
  scheduleHistoryErrorDetail = null,
  directOverrideErrorDetail = null,
  crawlJobId = 'crawl-job-123',
  scheduleHistories = {
    'jobsdb-nightly': {
      executions: [
        {
          id: 'exec-1',
          status: 'completed',
          started_at: '2026-05-21T02:00:00Z',
          completed_at: '2026-05-21T02:05:00Z',
          duration_seconds: 300,
          jobs_scraped: 24,
          jobs_saved: 20,
        },
      ],
    },
  },
  createdSchedule = {
    id: 'created-schedule',
    name: 'jobsdb automation',
    cron_expression: '0 2 * * *',
    category_ids: [1200],
    source_site: 'jobsdb',
    crawl_phase: 'listing',
    crawl_mode: 'headed',
    is_active: true,
    last_run_at: null,
    next_run_at: null,
  },
  toggledSchedule = {
    id: 'jobsdb-nightly',
    is_active: false,
    next_run_at: null,
  },
} = {}) {
  const runtimeCapabilities = {
    ...(capabilities || {}),
    scheduler: {
      available: true,
      manual_run_available: true,
      owner: 'scheduler-worker',
      worker_name: 'scheduler-worker',
      heartbeat_status: 'fresh',
      reason: null,
      ...(capabilities?.scheduler || {}),
    },
    sources: capabilities?.sources ?? SOURCE_CATALOG,
  };

  return vi.fn((input, init) => {
    const url = String(input);

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

    if (url === '/api/categories?source_site=offertoday') {
      return mockJsonResponse({ categories: offertodayCategories });
    }

    if (url === '/api/v1/scrape/progress') {
      if (scrapeProgressError) {
        return Promise.reject(scrapeProgressError);
      }

      return mockJsonResponse(scrapeProgress);
    }

    if (url === '/api/v1/capabilities') {
      if (capabilitiesError) {
        return Promise.reject(capabilitiesError);
      }
      return mockJsonResponse(runtimeCapabilities);
    }

    if (url.startsWith('/api/v1/crawl-jobs/listing-batches')) {
      if (listingBatchesError) {
        return Promise.reject(listingBatchesError);
      }
      return mockJsonResponse({ batches: listingBatches });
    }

    if (url === '/api/v1/crawl-jobs' && init?.method === 'POST') {
      if (directOverrideErrorDetail) {
        return mockErrorResponse(directOverrideErrorDetail);
      }
      return mockJsonResponse({ id: crawlJobId, status: 'queued' });
    }

    if (/^\/api\/v1\/schedules\/[^/]+\/run$/.test(url) && init?.method === 'POST') {
      if (runScheduleErrorDetail) {
        return mockErrorResponse(runScheduleErrorDetail);
      }
      return mockJsonResponse({ id: crawlJobId, status: 'queued' });
    }

    if (/^\/api\/v1\/schedules\/[^/]+\/history$/.test(url)) {
      if (scheduleHistoryErrorDetail) {
        return mockErrorResponse(scheduleHistoryErrorDetail);
      }
      const scheduleId = url.split('/')[4];
      return mockJsonResponse(scheduleHistories[scheduleId] || { executions: [] });
    }

    if (url === '/api/v1/crawl-jobs/crawl-job-123/resume' && init?.method === 'POST') {
      return mockJsonResponse({ id: 'crawl-job-123', status: 'dispatching' });
    }

    if (url === '/api/v1/crawl-jobs/crawl-job-123/cancel' && init?.method === 'POST') {
      return mockJsonResponse({ id: 'crawl-job-123', status: 'cancelled' });
    }

    if (/^\/api\/v1\/schedules\/[^/]+\/toggle$/.test(url) && init?.method === 'POST') {
      if (toggleScheduleErrorDetail) {
        return mockErrorResponse(toggleScheduleErrorDetail);
      }
      return mockJsonResponse(toggledSchedule);
    }

    if (/^\/api\/v1\/schedules\/[^/]+$/.test(url) && init?.method === 'DELETE') {
      if (deleteScheduleErrorDetail) {
        return mockErrorResponse(deleteScheduleErrorDetail);
      }
      return mockJsonResponse({ message: 'Schedule deleted' });
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
      if (createScheduleErrorDetail) {
        return mockErrorResponse(createScheduleErrorDetail);
      }
      return mockJsonResponse(createdSchedule);
    }

    if (url === '/api/v1/schedules') {
      if (schedulesErrorDetail) {
        return mockErrorResponse(schedulesErrorDetail);
      }
      return mockJsonResponse({ schedules });
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
    monitoringSpies.logError.mockClear();
    scrapeProgressPanelSpy.mockClear();
  });

  afterEach(() => {
    sessionStorage.clear();
    vi.restoreAllMocks();
  });

  it('loads jobsdb categories by default and only renders jobsdb schedules', async () => {
    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await waitFor(() => {
      expectFetchCalledWithUrl('/api/categories?source_site=jobsdb');
    });

    expect(await screen.findByRole('heading', { name: /scheduled automation/i })).toBeInTheDocument();
    expect(screen.getByText(/immediate run for backlog recovery/i)).toBeInTheDocument();
    expect(await screen.findByText('JobsDB Nightly')).toBeInTheDocument();
    expect(screen.queryByText('CTgoodjobs Nightly')).not.toBeInTheDocument();
  });

  it('renders source labels from runtime capabilities and passes source metadata into ScheduleForm', async () => {
    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await waitForSourceCatalogOptions();
    changeSource('offertoday');
    fireEvent.click(screen.getByRole('button', { name: /new automation/i }));

    expect(await screen.findByText('Schedule Form Source Label: OfferToday Live')).toBeInTheDocument();
    expect(screen.getByText('Schedule Form Source Modes: headless,headed')).toBeInTheDocument();
    expect(screen.getByText('Schedule Form Source Default Max Pages: 50')).toBeInTheDocument();
  });

  it('makes empty source metadata explicit when runtime capabilities omit the source catalog', async () => {
    vi.stubGlobal(
      'fetch',
      createFetchMock({
        capabilities: {
          sources: {},
        },
      }),
    );

    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    expect(
      await screen.findByText(/source metadata is unavailable for this runtime/i),
    ).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: /data source/i })).toBeDisabled();
    expect(screen.getByRole('option', { name: 'JobsDB' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'CTGoodJobs Live' })).not.toBeInTheDocument();
  });

  it('switches source, reloads categories, and filters the list to ctgoodjobs', async () => {
    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await waitForSourceCatalogOptions();
    changeSource('ctgoodjobs');

    await waitFor(() => {
      expectFetchCalledWithUrl('/api/categories?source_site=ctgoodjobs');
    });

    expect(await screen.findByText('CTgoodjobs Nightly')).toBeInTheDocument();
    expect(screen.queryByText('JobsDB Nightly')).not.toBeInTheDocument();
  });

  it('does not refetch shared schedules, runtime capabilities, or progress bootstrap when switching source', async () => {
    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await waitFor(() => {
      const urls = globalThis.fetch.mock.calls.map(([url]) => url);

      expect(urls).toContain('/api/v1/schedules');
      expect(urls).toContain('/api/v1/capabilities');
      expect(urls).toContain('/api/v1/scrape/progress');
      expect(urls).toContain('/api/categories?source_site=jobsdb');
    });

    await waitForSourceCatalogOptions();
    changeSource('ctgoodjobs');

    await waitFor(() => {
      expectFetchCalledWithUrl('/api/categories?source_site=ctgoodjobs');
    });

    const urls = globalThis.fetch.mock.calls.map(([url]) => url);

    expect(urls.filter((url) => url === '/api/v1/schedules')).toHaveLength(1);
    expect(urls.filter((url) => url === '/api/v1/capabilities')).toHaveLength(1);
    expect(urls.filter((url) => url === '/api/v1/scrape/progress')).toHaveLength(1);
    expect(urls.filter((url) => url === '/api/categories?source_site=jobsdb')).toHaveLength(1);
    expect(urls.filter((url) => url === '/api/categories?source_site=ctgoodjobs')).toHaveLength(1);
  });

  it('reuses cached categories when switching back to a previously visited source', async () => {
    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await screen.findByText('JobsDB Nightly');
    await waitForSourceCatalogOptions();

    changeSource('ctgoodjobs');
    expect(await screen.findByText('CTgoodjobs Nightly')).toBeInTheDocument();

    changeSource('jobsdb');
    expect(await screen.findByText('JobsDB Nightly')).toBeInTheDocument();

    changeSource('ctgoodjobs');
    expect(await screen.findByText('CTgoodjobs Nightly')).toBeInTheDocument();

    const urls = globalThis.fetch.mock.calls.map(([url]) => url);
    expect(urls.filter((url) => url === '/api/categories?source_site=jobsdb')).toHaveLength(1);
    expect(urls.filter((url) => url === '/api/categories?source_site=ctgoodjobs')).toHaveLength(1);
  });

  it('logs contextual monitoring details when category bootstrap fails', async () => {
    vi.stubGlobal(
      'fetch',
      createFetchMock({
        ctgoodjobsCategoryErrorDetail: 'CTgoodjobs category registry unavailable',
      }),
    );

    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await waitForSourceCatalogOptions();
    changeSource('ctgoodjobs');

    expect(await screen.findByText('CTgoodjobs category registry unavailable')).toBeInTheDocument();
    expect(monitoringSpies.logError).toHaveBeenCalledWith(
      'schedule_manager.categories_failed',
      expect.objectContaining({
        sourceSite: 'ctgoodjobs',
        requestId: 'req-fixed',
        detail: 'CTgoodjobs category registry unavailable',
      }),
    );
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

  it('logs contextual monitoring details when runtime capability bootstrap fails', async () => {
    vi.stubGlobal(
      'fetch',
      createFetchMock({
        capabilitiesError: new Error('capabilities offline'),
      }),
    );

    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await screen.findByText('Task Control Board');

    await waitFor(() => {
      expect(monitoringSpies.logError).toHaveBeenCalledWith(
        'schedule_manager.runtime_capabilities_failed',
        expect.objectContaining({
          requestId: 'req-fixed',
          detail: 'capabilities offline',
        }),
      );
    });
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
      const runCall = getFetchCallsForUrl('/api/v1/schedules/jobsdb-nightly/run')[0];
      expect(runCall?.[1]?.method).toBe('POST');
      expect(getHeaderValue(runCall?.[1]?.headers, 'X-Request-ID')).toBe('req-fixed');
    });
  });

  it('posts jobsdb crawl-job payloads with integer category ids and source_site', async () => {
    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await screen.findByText('Task Control Board');
    await waitForSourceCatalogOptions();
    fireEvent.click(screen.getByRole('button', { name: /direct override/i }));
    await waitFor(() => {
      expect(screen.getByRole('combobox', { name: /crawl mode/i })).toHaveValue('headed');
    });
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

  it('blocks headed direct override launches when runtime capabilities report the headed worker offline', async () => {
    vi.stubGlobal(
      'fetch',
      createFetchMock({
        capabilities: {
          scheduler: {
            available: true,
            manual_run_available: true,
            owner: 'scheduler-worker',
            worker_name: 'scheduler-worker',
            heartbeat_status: 'fresh',
            reason: null,
          },
          crawl_workers: {
            headed: {
              available: false,
              status: 'missing',
              heartbeat_status: 'missing',
              reason: 'headed_worker_missing',
            },
          },
        },
      }),
    );

    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await screen.findByText('Task Control Board');
    await waitForSourceCatalogOptions();
    fireEvent.click(screen.getByRole('button', { name: /direct override/i }));
    await waitFor(() => {
      expect(screen.getByRole('combobox', { name: /crawl mode/i })).toHaveValue('headed');
    });

    expect(await screen.findByText(/headed crawl worker is offline/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /start job id crawl/i })).toBeDisabled();

    const crawlJobCalls = globalThis.fetch.mock.calls.filter(
      ([url, request]) => url === '/api/v1/crawl-jobs' && request?.method === 'POST',
    );
    expect(crawlJobCalls).toHaveLength(0);
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

    await waitForSourceCatalogOptions();
    changeSource('ctgoodjobs');
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

  it('defaults OfferToday direct override runs to the all-IT listing scope and submits an empty category payload', async () => {
    vi.stubGlobal(
      'fetch',
      createFetchMock({
        offertodayCategories: OFFERTODAY_CATEGORIES,
      }),
    );

    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await screen.findByText('Task Control Board');

    await waitForSourceCatalogOptions();
    changeSource('offertoday');

    await waitFor(() => {
      expectFetchCalledWithUrl('/api/categories?source_site=offertoday');
    });

    fireEvent.click(screen.getByRole('button', { name: /direct override/i }));

    expect(screen.getByRole('spinbutton')).toHaveValue(50);
    expect(screen.getByText('全 IT 分類（預設）')).toBeInTheDocument();
    expect(screen.getByText('50 pages across 全 IT 分類（預設）')).toBeInTheDocument();
    expect(
      screen.getByText('Leave sectors blank to use 全 IT 分類（預設）.')
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /start job id crawl/i }));

    await waitFor(() => {
      const crawlJobCall = globalThis.fetch.mock.calls.find(
        ([url, request]) => url === '/api/v1/crawl-jobs' && request?.method === 'POST',
      );

      expect(crawlJobCall).toBeTruthy();
      expect(JSON.parse(crawlJobCall[1].body)).toEqual({
        source_site: 'offertoday',
        crawl_phase: 'listing',
        crawl_mode: 'headless',
        category_ids: [],
        max_pages: 50,
        detail_limit: 100,
        skip_existing: true,
      });
    });
  });

  it('shows listing-mode readiness guidance before any sector is selected', async () => {
    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await screen.findByText('Task Control Board');
    await waitForSourceCatalogOptions();
    fireEvent.click(screen.getByRole('button', { name: /direct override/i }));

    expect(await screen.findByText(/listing mode/i)).toBeInTheDocument();
    expect(screen.getByText(/select at least one sector to launch this listing crawl/i)).toBeInTheDocument();
    expect(screen.getByText(/launch blocked/i)).toBeInTheDocument();
  });

  it('shows detail-mode readiness guidance and explains the backlog scope when switched to detail mode', async () => {
    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await screen.findByText('Task Control Board');
    fireEvent.click(screen.getByRole('button', { name: /direct override/i }));
    fireEvent.change(screen.getByRole('combobox', { name: /crawl phase/i }), {
      target: { value: 'detail' },
    });

    expect(await screen.findByText(/detail mode/i)).toBeInTheDocument();
    expect(screen.getByText(/recover eligible detail backlog/i)).toBeInTheDocument();
    expect(screen.getByText(/launch blocked/i)).toBeInTheDocument();
  });

  it('shows listing-specific numeric helper copy in listing mode and detail-specific helper copy in detail mode', async () => {
    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await screen.findByText('Task Control Board');
    fireEvent.click(screen.getByRole('button', { name: /direct override/i }));

    expect(screen.getByText(/set how many listing pages to scan per selected sector/i)).toBeInTheDocument();

    fireEvent.change(screen.getByRole('combobox', { name: /crawl phase/i }), {
      target: { value: 'detail' },
    });

    expect(
      await screen.findByText(/set the maximum number of eligible detail rows to recover/i)
    ).toBeInTheDocument();
  });

  it('shows a readable launch summary for detail mode when a listing batch is selected', async () => {
    vi.stubGlobal(
      'fetch',
      createFetchMock({
        listingBatches: [
          {
            crawl_job_id: 'listing-batch-123',
            source_site: 'jobsdb',
            category_name: 'Engineering',
            listings_staged: 48,
            detail_pending: 12,
          },
        ],
      }),
    );

    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await screen.findByText('Task Control Board');
    await waitForSourceCatalogOptions();
    fireEvent.click(screen.getByRole('button', { name: /direct override/i }));
    await waitFor(() => {
      expect(screen.getByRole('combobox', { name: /crawl mode/i })).toHaveValue('headed');
    });
    fireEvent.change(screen.getByRole('combobox', { name: /crawl phase/i }), {
      target: { value: 'detail' },
    });

    const batchSelect = await screen.findByRole('combobox', { name: /listing batch scope/i });
    fireEvent.change(batchSelect, { target: { value: 'listing-batch-123' } });

    expect(await screen.findByText(/listing batch scope: jobsdb batch listing-batch-123/i)).toBeInTheDocument();
    expect(screen.getByText(/detail crawl will use only the selected listing batch/i)).toBeInTheDocument();
  });

  it('reuses cached listing batches when reopening detail mode for the same source', async () => {
    vi.stubGlobal(
      'fetch',
      createFetchMock({
        listingBatches: [
          {
            crawl_job_id: 'listing-batch-123',
            source_site: 'jobsdb',
            category_name: 'Engineering',
            listings_staged: 48,
            detail_pending: 12,
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

    expect(await screen.findByRole('combobox', { name: /listing batch scope/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /^cancel$/i }));
    fireEvent.click(screen.getByRole('button', { name: /direct override/i }));

    expect(await screen.findByRole('combobox', { name: /listing batch scope/i })).toBeInTheDocument();

    const urls = globalThis.fetch.mock.calls.map(([url]) => url);
    expect(urls.filter((url) => url === '/api/v1/crawl-jobs/listing-batches?source_site=jobsdb&limit=20')).toHaveLength(1);
  });

  it('logs contextual monitoring details when listing batch loading fails', async () => {
    vi.stubGlobal(
      'fetch',
      createFetchMock({
        listingBatchesError: new Error('listing batches offline'),
      }),
    );

    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await screen.findByText('Task Control Board');
    fireEvent.click(screen.getByRole('button', { name: /direct override/i }));
    fireEvent.change(screen.getByRole('combobox', { name: /crawl phase/i }), {
      target: { value: 'detail' },
    });

    await waitFor(() => {
      expect(monitoringSpies.logError).toHaveBeenCalledWith(
        'schedule_manager.listing_batches_failed',
        expect.objectContaining({
          sourceSite: 'jobsdb',
          requestId: 'req-fixed',
          detail: 'listing batches offline',
        }),
      );
    });
  });

  it('invalidates cached listing batches after launching a new listing crawl', async () => {
    vi.stubGlobal(
      'fetch',
      createFetchMock({
        listingBatches: [
          {
            crawl_job_id: 'listing-batch-123',
            source_site: 'jobsdb',
            category_name: 'Engineering',
            listings_staged: 48,
            detail_pending: 12,
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
    expect(await screen.findByRole('combobox', { name: /listing batch scope/i })).toBeInTheDocument();

    fireEvent.change(screen.getByRole('combobox', { name: /crawl phase/i }), {
      target: { value: 'listing' },
    });
    fireEvent.click(screen.getByRole('checkbox', { name: /engineering/i }));
    fireEvent.click(screen.getByRole('button', { name: /start job id crawl/i }));
    await screen.findByText('Scrape Progress Stub');
    fireEvent.click(screen.getByRole('button', { name: /close progress stub/i }));
    await waitFor(() => {
      expect(screen.queryByText('Scrape Progress Stub')).not.toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: /direct override/i }));
    fireEvent.change(screen.getByRole('combobox', { name: /crawl phase/i }), {
      target: { value: 'detail' },
    });
    expect(await screen.findByRole('combobox', { name: /listing batch scope/i })).toBeInTheDocument();

    const urls = globalThis.fetch.mock.calls.map(([url]) => url);
    expect(urls.filter((url) => url === '/api/v1/crawl-jobs/listing-batches?source_site=jobsdb&limit=20')).toHaveLength(2);
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
      const resumeCalls = getFetchCallsForUrl('/api/v1/crawl-jobs/crawl-job-123/resume');
      const reuseResumeCall = resumeCalls.find(([, request]) => request?.body === JSON.stringify({ strategy: 'reuse_open_browser' }));
      const freshResumeCall = resumeCalls.find(([, request]) => request?.body === JSON.stringify({ strategy: 'fresh_profile' }));
      const cancelCall = getFetchCallsForUrl('/api/v1/crawl-jobs/crawl-job-123/cancel')[0];
      const openBrowserCall = getFetchCallsForUrl('http://127.0.0.1:47652/manual-actions/open-browser')[0];
      const reuseStatusCall = getFetchCallsForUrl('http://127.0.0.1:47652/manual-actions/reuse-status')[0];
      const closeWindowsCall = getFetchCallsForUrl('http://127.0.0.1:47652/manual-actions/close-profile-windows')[0];

      expect(reuseResumeCall?.[1]?.method).toBe('POST');
      expect(reuseResumeCall?.[1]?.body).toBe(JSON.stringify({ strategy: 'reuse_open_browser' }));
      expect(getHeaderValue(reuseResumeCall?.[1]?.headers, 'Content-Type')).toBe('application/json');
      expect(getHeaderValue(reuseResumeCall?.[1]?.headers, 'X-Request-ID')).toBe('req-fixed');

      expect(freshResumeCall?.[1]?.method).toBe('POST');
      expect(freshResumeCall?.[1]?.body).toBe(JSON.stringify({ strategy: 'fresh_profile' }));
      expect(getHeaderValue(freshResumeCall?.[1]?.headers, 'Content-Type')).toBe('application/json');
      expect(getHeaderValue(freshResumeCall?.[1]?.headers, 'X-Request-ID')).toBe('req-fixed');

      expect(cancelCall?.[1]?.method).toBe('POST');
      expect(getHeaderValue(cancelCall?.[1]?.headers, 'X-Request-ID')).toBe('req-fixed');

      expect(openBrowserCall?.[1]?.method).toBe('POST');
      expect(openBrowserCall?.[1]?.body).toBe(JSON.stringify({ crawl_job_id: 'crawl-job-123' }));
      expect(getHeaderValue(openBrowserCall?.[1]?.headers, 'Content-Type')).toBe('application/json');
      expect(getHeaderValue(openBrowserCall?.[1]?.headers, 'X-Request-ID')).toBe('req-fixed');

      expect(reuseStatusCall?.[1]?.method).toBe('POST');
      expect(reuseStatusCall?.[1]?.body).toBe(JSON.stringify({ crawl_job_id: 'crawl-job-123' }));
      expect(getHeaderValue(reuseStatusCall?.[1]?.headers, 'Content-Type')).toBe('application/json');
      expect(getHeaderValue(reuseStatusCall?.[1]?.headers, 'X-Request-ID')).toBe('req-fixed');

      expect(closeWindowsCall?.[1]?.method).toBe('POST');
      expect(closeWindowsCall?.[1]?.body).toBe(JSON.stringify({ crawl_job_id: 'crawl-job-123' }));
      expect(getHeaderValue(closeWindowsCall?.[1]?.headers, 'Content-Type')).toBe('application/json');
      expect(getHeaderValue(closeWindowsCall?.[1]?.headers, 'X-Request-ID')).toBe('req-fixed');
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
    expect(monitoringSpies.logError).toHaveBeenCalledWith(
      'schedule_manager.progress_bootstrap_failed',
      expect.objectContaining({
        requestId: 'req-fixed',
        detail: 'network down',
      }),
    );
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

  it('adds X-Request-ID headers to the remaining schedule control-plane fetches', async () => {
    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    const scheduleCard = (await screen.findByText('JobsDB Nightly')).closest('.schedule-card');
    expect(scheduleCard).not.toBeNull();

    await waitFor(() => {
      const bootstrapCall = getFetchCallsForUrl('/api/v1/schedules').find(
        ([, request]) => !request?.method,
      );
      expect(getHeaderValue(bootstrapCall?.[1]?.headers, 'X-Request-ID')).toBe('req-fixed');
    });

    fireEvent.click(screen.getByRole('button', { name: /new automation/i }));
    fireEvent.click(screen.getByRole('button', { name: /submit schedule stub/i }));

    await waitFor(() => {
      const createCall = getFetchCallsForUrl('/api/v1/schedules').find(
        ([, request]) => request?.method === 'POST',
      );
      expect(getHeaderValue(createCall?.[1]?.headers, 'X-Request-ID')).toBe('req-fixed');
    });

    fireEvent.click(within(scheduleCard).getByRole('checkbox'));

    await waitFor(() => {
      const toggleCall = getFetchCallsForUrl('/api/v1/schedules/jobsdb-nightly/toggle')[0];
      expect(getHeaderValue(toggleCall?.[1]?.headers, 'X-Request-ID')).toBe('req-fixed');
    });

    fireEvent.click(within(scheduleCard).getAllByRole('button', { name: /logs/i })[0]);

    await waitFor(() => {
      const historyCall = getFetchCallsForUrl('/api/v1/schedules/jobsdb-nightly/history')[0];
      expect(getHeaderValue(historyCall?.[1]?.headers, 'X-Request-ID')).toBe('req-fixed');
    });

    fireEvent.click(within(scheduleCard).getAllByRole('button', { name: /run now/i })[0]);

    await waitFor(() => {
      const runCall = getFetchCallsForUrl('/api/v1/schedules/jobsdb-nightly/run')[0];
      expect(getHeaderValue(runCall?.[1]?.headers, 'X-Request-ID')).toBe('req-fixed');
    });

    fireEvent.click(screen.getByRole('button', { name: /direct override/i }));
    fireEvent.click(screen.getByRole('checkbox', { name: /engineering/i }));
    fireEvent.click(screen.getByRole('button', { name: /start job id crawl/i }));

    await waitFor(() => {
      const directOverrideCall = getFetchCallsForUrl('/api/v1/crawl-jobs')[0];
      expect(getHeaderValue(directOverrideCall?.[1]?.headers, 'X-Request-ID')).toBe('req-fixed');
    });

    fireEvent.click(within(scheduleCard).getAllByRole('button')[2]);

    await waitFor(() => {
      const deleteCall = getFetchCallsForUrl('/api/v1/schedules/jobsdb-nightly')[0];
      expect(getHeaderValue(deleteCall?.[1]?.headers, 'X-Request-ID')).toBe('req-fixed');
    });
  });

  it.each([
    {
      name: 'schedule bootstrap',
      fetchMock: () => createFetchMock({ schedulesErrorDetail: 'Schedule bootstrap unavailable' }),
      trigger: async () => {
        render(<ScheduleManager onNavigateToAI={vi.fn()} />);
        expect(await screen.findByText('Schedule bootstrap unavailable')).toBeInTheDocument();
      },
      event: 'schedule_manager.schedules_bootstrap_failed',
      detail: 'Schedule bootstrap unavailable',
      fields: {},
    },
    {
      name: 'schedule creation',
      fetchMock: () => createFetchMock({ createScheduleErrorDetail: 'Schedule creation failed' }),
      trigger: async () => {
        render(<ScheduleManager onNavigateToAI={vi.fn()} />);
        await screen.findByText('JobsDB Nightly');
        fireEvent.click(screen.getByRole('button', { name: /new automation/i }));
        fireEvent.click(screen.getByRole('button', { name: /submit schedule stub/i }));
        expect(await screen.findByText('Schedule creation failed')).toBeInTheDocument();
      },
      event: 'schedule_manager.schedule_create_failed',
      detail: 'Schedule creation failed',
      fields: {
        sourceSite: 'jobsdb',
        scheduleName: 'jobsdb automation',
      },
    },
    {
      name: 'schedule toggle',
      fetchMock: () => createFetchMock({ toggleScheduleErrorDetail: 'Schedule toggle failed' }),
      trigger: async () => {
        render(<ScheduleManager onNavigateToAI={vi.fn()} />);
        const scheduleCard = (await screen.findByText('JobsDB Nightly')).closest('.schedule-card');
        fireEvent.click(within(scheduleCard).getByRole('checkbox'));
        expect(await screen.findByText('Schedule toggle failed')).toBeInTheDocument();
      },
      event: 'schedule_manager.schedule_toggle_failed',
      detail: 'Schedule toggle failed',
      fields: { scheduleId: 'jobsdb-nightly' },
    },
    {
      name: 'schedule deletion',
      fetchMock: () => createFetchMock({ deleteScheduleErrorDetail: 'Schedule delete failed' }),
      trigger: async () => {
        render(<ScheduleManager onNavigateToAI={vi.fn()} />);
        const scheduleCard = (await screen.findByText('JobsDB Nightly')).closest('.schedule-card');
        fireEvent.click(within(scheduleCard).getAllByRole('button')[2]);
        expect(await screen.findByText('Schedule delete failed')).toBeInTheDocument();
      },
      event: 'schedule_manager.schedule_delete_failed',
      detail: 'Schedule delete failed',
      fields: { scheduleId: 'jobsdb-nightly' },
    },
    {
      name: 'schedule manual run',
      fetchMock: () => createFetchMock({ runScheduleErrorDetail: 'Schedule run failed' }),
      trigger: async () => {
        render(<ScheduleManager onNavigateToAI={vi.fn()} />);
        await screen.findByText('JobsDB Nightly');
        fireEvent.click(screen.getAllByRole('button', { name: /run now/i })[0]);
        expect(await screen.findByText('Schedule run failed')).toBeInTheDocument();
      },
      event: 'schedule_manager.schedule_run_failed',
      detail: 'Schedule run failed',
      fields: { scheduleId: 'jobsdb-nightly' },
    },
    {
      name: 'schedule history bootstrap',
      fetchMock: () => createFetchMock({ scheduleHistoryErrorDetail: 'Schedule history failed' }),
      trigger: async () => {
        render(<ScheduleManager onNavigateToAI={vi.fn()} />);
        await screen.findByText('JobsDB Nightly');
        fireEvent.click(screen.getAllByRole('button', { name: /logs/i })[0]);
        expect(await screen.findByText('Schedule history failed')).toBeInTheDocument();
      },
      event: 'schedule_manager.schedule_history_failed',
      detail: 'Schedule history failed',
      fields: { scheduleId: 'jobsdb-nightly' },
    },
    {
      name: 'direct override crawl creation',
      fetchMock: () => createFetchMock({ directOverrideErrorDetail: 'Direct override failed' }),
      trigger: async () => {
        render(<ScheduleManager onNavigateToAI={vi.fn()} />);
        await screen.findByText('Task Control Board');
        fireEvent.click(screen.getByRole('button', { name: /direct override/i }));
        fireEvent.click(screen.getByRole('checkbox', { name: /engineering/i }));
        fireEvent.click(screen.getByRole('button', { name: /start job id crawl/i }));
        expect(await screen.findByText('Direct override failed')).toBeInTheDocument();
      },
      event: 'schedule_manager.direct_override_create_failed',
      detail: 'Direct override failed',
      fields: {
        sourceSite: 'jobsdb',
        crawlPhase: 'listing',
      },
    },
  ])('logs contextual monitoring details when the $name flow fails', async ({ fetchMock, trigger, event, detail, fields }) => {
    vi.stubGlobal('fetch', fetchMock());

    await trigger();

    expect(monitoringSpies.logError).toHaveBeenCalledWith(
      event,
      expect.objectContaining({
        requestId: 'req-fixed',
        detail,
        ...fields,
      }),
    );
  });

  it('includes source_site when creating schedules', async () => {
    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await waitForSourceCatalogOptions();
    changeSource('ctgoodjobs');
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

  it('creates schedules with a local list update instead of refetching all schedules', async () => {
    vi.stubGlobal(
      'fetch',
      createFetchMock({
        createdSchedule: {
          id: 'created-schedule',
          name: 'jobsdb automation',
          cron_expression: '0 2 * * *',
          category_ids: [1200],
          source_site: 'jobsdb',
          crawl_phase: 'listing',
          crawl_mode: 'headed',
          is_active: true,
          last_run_at: null,
          next_run_at: null,
        },
      }),
    );

    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await screen.findByText('JobsDB Nightly');
    fireEvent.click(screen.getByRole('button', { name: /new automation/i }));
    fireEvent.click(screen.getByRole('button', { name: /submit schedule stub/i }));

    expect(await screen.findByText('jobsdb automation')).toBeInTheDocument();

    const urls = globalThis.fetch.mock.calls.map(([url]) => url);
    expect(urls.filter((url) => url === '/api/v1/schedules')).toHaveLength(2);
    expect(
      urls.filter((url, index) => url === '/api/v1/schedules' && globalThis.fetch.mock.calls[index][1]?.method !== 'POST')
    ).toHaveLength(1);
  });

  it('applies schedule toggle locally without refetching all schedules', async () => {
    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    const scheduleCard = (await screen.findByText('JobsDB Nightly')).closest('.schedule-card');
    expect(scheduleCard).not.toBeNull();

    const toggle = within(scheduleCard).getByRole('checkbox');
    expect(toggle).toBeChecked();

    fireEvent.click(toggle);

    await waitFor(() => {
      expect(toggle).not.toBeChecked();
    });

    const urls = globalThis.fetch.mock.calls.map(([url]) => url);
    expect(urls.filter((url) => url === '/api/v1/schedules')).toHaveLength(1);
    expect(urls.filter((url) => /\/api\/v1\/schedules\/jobsdb-nightly\/toggle$/.test(url))).toHaveLength(1);
  });

  it('removes deleted schedules locally without refetching all schedules', async () => {
    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    const scheduleCard = (await screen.findByText('JobsDB Nightly')).closest('.schedule-card');
    expect(scheduleCard).not.toBeNull();

    const deleteButton = within(scheduleCard).getAllByRole('button')[2];
    fireEvent.click(deleteButton);

    await waitFor(() => {
      expect(screen.queryByText('JobsDB Nightly')).not.toBeInTheDocument();
    });

    const urls = globalThis.fetch.mock.calls.map(([url]) => url);
    expect(urls.filter((url) => url === '/api/v1/schedules')).toHaveLength(1);
    expect(urls.filter((url) => /\/api\/v1\/schedules\/jobsdb-nightly$/.test(url))).toHaveLength(1);
  });

  it('does not refetch all schedules after running a schedule immediately', async () => {
    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await screen.findByText('JobsDB Nightly');
    fireEvent.click(screen.getAllByRole('button', { name: /run now/i })[0]);

    await waitFor(() => {
      const runCall = getFetchCallsForUrl('/api/v1/schedules/jobsdb-nightly/run')[0];
      expect(runCall?.[1]?.method).toBe('POST');
      expect(getHeaderValue(runCall?.[1]?.headers, 'X-Request-ID')).toBe('req-fixed');
    });

    const urls = globalThis.fetch.mock.calls.map(([url]) => url);
    expect(urls.filter((url) => url === '/api/v1/schedules')).toHaveLength(1);
  });

  it('reuses cached schedule history when reopening the same logs drawer', async () => {
    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await screen.findByText('JobsDB Nightly');
    fireEvent.click(screen.getAllByRole('button', { name: /logs/i })[0]);

    expect(await screen.findByText('Schedule History Stub')).toBeInTheDocument();
    expect(screen.getByTestId('history-schedule-name')).toHaveTextContent('JobsDB Nightly');
    expect(screen.getByTestId('history-execution-count')).toHaveTextContent('1');

    fireEvent.click(screen.getByRole('button', { name: /close history stub/i }));
    await waitFor(() => {
      expect(screen.queryByText('Schedule History Stub')).not.toBeInTheDocument();
    });

    fireEvent.click(screen.getAllByRole('button', { name: /logs/i })[0]);
    expect(await screen.findByText('Schedule History Stub')).toBeInTheDocument();

    const urls = globalThis.fetch.mock.calls.map(([url]) => url);
    expect(urls.filter((url) => url === '/api/v1/schedules/jobsdb-nightly/history')).toHaveLength(1);
  });

  it('invalidates cached schedule history after running the same schedule', async () => {
    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await screen.findByText('JobsDB Nightly');
    fireEvent.click(screen.getAllByRole('button', { name: /logs/i })[0]);
    expect(await screen.findByText('Schedule History Stub')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /close history stub/i }));
    await waitFor(() => {
      expect(screen.queryByText('Schedule History Stub')).not.toBeInTheDocument();
    });

    fireEvent.click(screen.getAllByRole('button', { name: /run now/i })[0]);
    await waitFor(() => {
      const runCall = getFetchCallsForUrl('/api/v1/schedules/jobsdb-nightly/run')[0];
      expect(runCall?.[1]?.method).toBe('POST');
      expect(getHeaderValue(runCall?.[1]?.headers, 'X-Request-ID')).toBe('req-fixed');
    });

    fireEvent.click(screen.getAllByRole('button', { name: /logs/i })[0]);
    expect(await screen.findByText('Schedule History Stub')).toBeInTheDocument();

    const urls = globalThis.fetch.mock.calls.map(([url]) => url);
    expect(urls.filter((url) => url === '/api/v1/schedules/jobsdb-nightly/history')).toHaveLength(2);
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
      expectFetchCalledWithUrl('/api/v1/crawl-jobs/listing-batches?source_site=jobsdb&limit=20');
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
      screen.getByText(/listing batch scope: jobsdb batch 11111111-1111-4111-8111-111111111111/i)
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

  it('defaults OfferToday detail runs to the newest eligible listing batch and keeps global scope explicit', async () => {
    const listingBatchId = '4cee200d-9b1b-40ad-88da-8866bacd71a7';
    vi.stubGlobal(
      'fetch',
      createFetchMock({
        listingBatches: [
          {
            crawl_job_id: 'newer-running-listing-batch',
            source_site: 'offertoday',
            status: 'running',
            category_ids: [118000],
            queued_at: '2026-07-14T12:00:00Z',
            listings_staged: 10,
            detail_pending: 10,
            detail_running: 0,
            detail_completed: 0,
            detail_failed: 0,
            detail_manual_action_required: 0,
          },
          {
            crawl_job_id: 'older-completed-listing-batch',
            source_site: 'offertoday',
            status: 'completed',
            category_ids: [118000],
            queued_at: '2026-07-14T10:00:00Z',
            completed_at: '2026-07-14T10:30:00Z',
            listings_staged: 25,
            detail_pending: 25,
            detail_running: 0,
            detail_completed: 0,
            detail_failed: 0,
            detail_manual_action_required: 0,
          },
          {
            crawl_job_id: listingBatchId,
            source_site: 'offertoday',
            status: 'completed',
            category_ids: [118000],
            queued_at: '2026-07-14T11:28:59Z',
            completed_at: '2026-07-14T12:45:50Z',
            listings_staged: 6969,
            detail_pending: 5956,
            detail_running: 0,
            detail_completed: 1013,
            detail_failed: 0,
            detail_manual_action_required: 0,
          },
        ],
      }),
    );

    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await screen.findByText('Task Control Board');
    await waitForSourceCatalogOptions();
    changeSource('offertoday');
    fireEvent.click(screen.getByRole('button', { name: /direct override/i }));
    fireEvent.change(screen.getByRole('combobox', { name: /crawl phase/i }), {
      target: { value: 'detail' },
    });

    const batchScope = await screen.findByRole('combobox', { name: /listing batch scope/i });
    await waitFor(() => {
      expect(batchScope).toHaveValue(listingBatchId);
    });
    expect(
      screen.getByText(new RegExp(`listing batch scope: offertoday batch ${listingBatchId}`, 'i'))
    ).toBeInTheDocument();

    fireEvent.change(batchScope, { target: { value: '' } });
    await waitFor(() => {
      expect(batchScope).toHaveValue('');
    });
    expect(
      screen.getByRole('option', { name: /global category backlog \(advanced\)/i }).selected
    ).toBe(true);

    fireEvent.change(batchScope, { target: { value: listingBatchId } });
    fireEvent.click(screen.getByRole('button', { name: /start job detail crawl/i }));

    await waitFor(() => {
      const crawlJobCall = globalThis.fetch.mock.calls.find(
        ([url, request]) => url === '/api/v1/crawl-jobs' && request?.method === 'POST',
      );
      expect(crawlJobCall).toBeTruthy();
      expect(JSON.parse(crawlJobCall[1].body)).toMatchObject({
        source_site: 'offertoday',
        crawl_phase: 'detail',
        crawl_mode: 'headless',
        category_ids: [],
        source_listing_crawl_job_id: listingBatchId,
        detail_limit: 100,
        skip_existing: false,
      });
    });
  });

  it('does not overwrite an explicit global OfferToday scope when listing batches finish loading', async () => {
    const baseFetch = createFetchMock();
    let resolveListingBatches;
    const listingBatchResponse = new Promise((resolve) => {
      resolveListingBatches = resolve;
    });
    vi.stubGlobal('fetch', vi.fn((input, init) => {
      if (String(input).startsWith('/api/v1/crawl-jobs/listing-batches')) {
        return listingBatchResponse;
      }
      return baseFetch(input, init);
    }));

    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await screen.findByText('Task Control Board');
    await waitForSourceCatalogOptions();
    changeSource('offertoday');
    fireEvent.click(screen.getByRole('button', { name: /direct override/i }));
    fireEvent.change(screen.getByRole('combobox', { name: /crawl phase/i }), {
      target: { value: 'detail' },
    });

    const batchScope = await screen.findByRole('combobox', { name: /listing batch scope/i });
    fireEvent.change(batchScope, { target: { value: '' } });

    await act(async () => {
      resolveListingBatches(await mockJsonResponse({
        batches: [
          {
            crawl_job_id: 'completed-batch-after-request',
            source_site: 'offertoday',
            status: 'completed',
            queued_at: '2026-07-14T12:00:00Z',
            detail_pending: 10,
            detail_failed: 0,
            detail_manual_action_required: 0,
          },
        ],
      }));
    });

    await screen.findByRole('option', { name: /completed-batch-after-request/i });
    expect(batchScope).toHaveValue('');
    expect(
      screen.getByRole('option', { name: /global category backlog \(advanced\)/i }).selected
    ).toBe(true);
  });

  it('does not present cleared numeric override fields as zero-valued run summaries', async () => {
    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await screen.findByText('Task Control Board');
    fireEvent.click(screen.getByRole('button', { name: /direct override/i }));

    const numericInput = screen.getByRole('spinbutton');
    fireEvent.change(numericInput, { target: { value: '' } });

    expect(screen.queryByText(/0 pages per sector/i)).not.toBeInTheDocument();
    expect(screen.getByText(/page limit not set/i)).toBeInTheDocument();

    fireEvent.change(screen.getByRole('combobox', { name: /crawl phase/i }), {
      target: { value: 'detail' },
    });
    await waitFor(() => {
      expectFetchCalledWithUrl('/api/v1/crawl-jobs/listing-batches?source_site=jobsdb&limit=20');
    });
    fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '' } });

    expect(screen.queryByText(/up to 0 job details to crawl/i)).not.toBeInTheDocument();
    expect(screen.getByText(/detail limit not set/i)).toBeInTheDocument();
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
    expect(screen.getByText('details completed')).toBeInTheDocument();
    expect(screen.queryByText('details ingested')).not.toBeInTheDocument();
  });

  it('shows failed and manual-review detail counts when the selected listing batch includes them', async () => {
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
            detail_pending: 51,
            detail_running: 0,
            detail_completed: 22,
            detail_failed: 11,
            detail_manual_action_required: 6,
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

    expect(
      await screen.findByRole('option', { name: /jobsdb batch 11111111-1111-4111-8111-111111111111/i })
    ).toBeInTheDocument();

    fireEvent.change(screen.getByRole('combobox', { name: /listing batch/i }), {
      target: { value: '11111111-1111-4111-8111-111111111111' },
    });

    expect(
      await screen.findByText('11 failed')
    ).toBeInTheDocument();
    expect(screen.getByText('details failed')).toBeInTheDocument();
    expect(screen.getByText('6 manual review')).toBeInTheDocument();
    expect(screen.getByText('details blocked')).toBeInTheDocument();
  });

  it('shows running detail counts when the selected listing batch has in-flight detail work', async () => {
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
            detail_pending: 51,
            detail_running: 12,
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

    expect(
      await screen.findByRole('option', { name: /jobsdb batch 11111111-1111-4111-8111-111111111111/i })
    ).toBeInTheDocument();

    fireEvent.change(screen.getByRole('combobox', { name: /listing batch/i }), {
      target: { value: '11111111-1111-4111-8111-111111111111' },
    });

    expect(await screen.findByText('12 running')).toBeInTheDocument();
    expect(screen.getByText('details in flight')).toBeInTheDocument();
  });

  it('orders selected listing batch backlog metrics in the same stage-to-terminal sequence used elsewhere', async () => {
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
            detail_pending: 51,
            detail_running: 12,
            detail_completed: 22,
            detail_failed: 11,
            detail_manual_action_required: 6,
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

    expect(
      await screen.findByRole('option', { name: /jobsdb batch 11111111-1111-4111-8111-111111111111/i })
    ).toBeInTheDocument();

    fireEvent.change(screen.getByRole('combobox', { name: /listing batch/i }), {
      target: { value: '11111111-1111-4111-8111-111111111111' },
    });

    const metricGrid = screen.getByLabelText(/selected listing batch backlog/i);
    const metricLabels = Array.from(metricGrid.querySelectorAll('strong')).map((node) => node.textContent);

    expect(metricLabels).toEqual([
      '96 staged',
      '51 pending',
      '12 running',
      '22 completed',
      '11 failed',
      '6 manual review',
    ]);
  });

  it('renders source-specific empty copy when the current source has no schedules', async () => {
    vi.stubGlobal(
      'fetch',
      createFetchMock({
        schedules: [MIXED_SCHEDULES[0]],
      }),
    );

    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await waitForSourceCatalogOptions();
    changeSource('ctgoodjobs');

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

