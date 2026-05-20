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
        <button type="button" onClick={() => props.onResumeCrawlJob?.('crawl-job-123')}>
          Resume Progress Stub
        </button>
        <button type="button" onClick={() => props.onCancelCrawlJob?.('crawl-job-123')}>
          Cancel Progress Stub
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

    if (url === '/api/v1/crawl-jobs' && init?.method === 'POST') {
      return mockJsonResponse({ id: crawlJobId, status: 'queued' });
    }

    if (url === '/api/v1/crawl-jobs/crawl-job-123/resume' && init?.method === 'POST') {
      return mockJsonResponse({ id: 'crawl-job-123', status: 'dispatching' });
    }

    if (url === '/api/v1/crawl-jobs/crawl-job-123/cancel' && init?.method === 'POST') {
      return mockJsonResponse({ id: 'crawl-job-123', status: 'cancelled' });
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

  it('posts jobsdb crawl-job payloads with integer category ids and source_site', async () => {
    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await screen.findByText('Task Control Board');
    fireEvent.click(screen.getByRole('button', { name: /direct override/i }));
    fireEvent.click(screen.getByRole('checkbox', { name: /engineering/i }));
    fireEvent.click(screen.getByRole('button', { name: /engage scanner/i }));

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
      });
    });
  });

  it('stores a direct override session marker and opens progress with recovery props after launch', async () => {
    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await screen.findByText('Task Control Board');
    fireEvent.click(screen.getByRole('button', { name: /direct override/i }));
    fireEvent.click(screen.getByRole('checkbox', { name: /engineering/i }));
    fireEvent.click(screen.getByRole('button', { name: /engage scanner/i }));

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
    fireEvent.click(screen.getByRole('button', { name: /engage scanner/i }));

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

  it('passes both resume and cancel handlers into the scrape progress panel', async () => {
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
  });

  it('posts resume and cancel requests when the progress panel invokes its action handlers', async () => {
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

    fireEvent.click(screen.getByRole('button', { name: /resume progress stub/i }));
    fireEvent.click(screen.getByRole('button', { name: /cancel progress stub/i }));

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith('/api/v1/crawl-jobs/crawl-job-123/resume', {
        method: 'POST',
      });
      expect(globalThis.fetch).toHaveBeenCalledWith('/api/v1/crawl-jobs/crawl-job-123/cancel', {
        method: 'POST',
      });
    });
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
    fireEvent.click(screen.getByRole('button', { name: /engage scanner/i }));

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
    fireEvent.click(screen.getByRole('button', { name: /engage scanner/i }));

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

  it('posts detail crawl payloads with detail_limit and optional source listing batch id', async () => {
    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await screen.findByText('Task Control Board');
    fireEvent.click(screen.getByRole('button', { name: /direct override/i }));
    fireEvent.change(screen.getByRole('combobox', { name: /crawl phase/i }), {
      target: { value: 'detail' },
    });
    fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '250' } });
    fireEvent.change(screen.getByRole('textbox', { name: /source listing crawl job id/i }), {
      target: { value: 'listing-crawl-123' },
    });
    fireEvent.click(screen.getByRole('button', { name: /engage scanner/i }));

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
        source_listing_crawl_job_id: 'listing-crawl-123',
      });
    });
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
