import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { monitoringSpies } = vi.hoisted(() => ({
  monitoringSpies: {
    createMonitoringId: vi.fn(() => 'req-fixed'),
    logError: vi.fn(),
    logInfo: vi.fn(),
    logWarn: vi.fn(),
  },
}));

vi.mock('../../monitoring', () => monitoringSpies);

import CrawlTasksPage from './CrawlTasksPage';

function createJsonResponse(payload) {
  return Promise.resolve({
    ok: true,
    status: 200,
    json: async () => payload,
  });
}

const PAGE_ONE_PAYLOAD = {
  items: [
    {
      crawl_job_id: 'crawl-job-1',
      persisted_status: 'failed',
      status: 'failed',
      source_site: 'ctgoodjobs',
      crawl_mode: 'headed',
      request_payload: {
        crawl_phase: 'detail',
      },
      queued_at: '2026-07-09T01:48:00+00:00',
      started_at: '2026-07-09T01:52:00+00:00',
      updated_at: '2026-07-09T02:00:00+00:00',
      detail_target_rows: 48,
      jobs_saved: 24,
      error: 'Unable to launch headed browser',
    },
  ],
  total: 11,
  page: 1,
  page_size: 10,
  time_range: 'all',
  refreshed_at: '2026-07-09T02:00:00+00:00',
};

const PAGE_TWO_PAYLOAD = {
  items: [
    {
      crawl_job_id: 'crawl-job-11',
      persisted_status: 'completed',
      status: 'completed',
      source_site: 'jobsdb',
      crawl_mode: 'headless',
      request_payload: {
        crawl_phase: 'listing',
      },
      queued_at: '2026-07-08T18:48:00+00:00',
      started_at: '2026-07-08T18:49:00+00:00',
      updated_at: '2026-07-08T19:00:00+00:00',
      job_ids_collected: 120,
      detail_target_rows: 86,
      jobs_saved: 86,
    },
  ],
  total: 11,
  page: 2,
  page_size: 10,
  time_range: 'all',
  refreshed_at: '2026-07-09T02:10:00+00:00',
};

const MANUAL_ACTION_PAYLOAD = {
  items: [
    {
      crawl_job_id: 'crawl-job-manual',
      persisted_status: 'manual_action_required',
      status: 'manual_action_required',
      source_site: 'jobsdb',
      crawl_mode: 'headed',
      issue_class: 'manual_action_required',
      issue_code: 'captcha_interstitial',
      issue_stage: 'detail',
      latest_issue_text: 'Complete the captcha challenge, then resume the run.',
      request_payload: {
        crawl_phase: 'detail',
      },
      manual_action: {
        reason: 'captcha_interstitial',
        blocked_url: 'https://example.test/manual-action',
        resume_supported: true,
        reuse_open_browser_supported: true,
      },
      queued_at: '2026-07-09T03:00:00+00:00',
      started_at: '2026-07-09T03:02:00+00:00',
      updated_at: '2026-07-09T03:05:00+00:00',
      error: 'Manual verification required',
    },
  ],
  total: 1,
  page: 1,
  page_size: 10,
  time_range: 'all',
  refreshed_at: '2026-07-09T03:05:00+00:00',
};

const OFFERTODAY_IP_BLOCK_PAYLOAD = {
  ...MANUAL_ACTION_PAYLOAD,
  items: [
    {
      ...MANUAL_ACTION_PAYLOAD.items[0],
      crawl_job_id: '21436eff-7d0f-4df2-9460-e4ab9d8805e2',
      source_site: 'offertoday',
      crawl_mode: 'headless',
      issue_class: 'ip_blocked',
      issue_code: '-1000035',
      latest_issue_text: 'OfferToday detail phase requires manual action: ip_blocked',
      manual_action: {
        action_type: 'session_recovery',
        classification: 'ip_blocked',
        resume_supported: true,
        reuse_open_browser_supported: true,
      },
    },
  ],
};

const IDENTITY_AUDIT_PAYLOAD = {
  ...MANUAL_ACTION_PAYLOAD,
  items: [
    {
      ...MANUAL_ACTION_PAYLOAD.items[0],
      crawl_job_id: 'crawl-job-identity-audit',
      source_site: 'offertoday',
      issue_class: 'manual_action_required',
      latest_issue_text: 'OfferToday identity evidence requires operator review.',
      manual_action: {
        action_type: 'identity_audit',
        classification: 'identity_conflict',
        resume_supported: false,
        reuse_open_browser_supported: false,
      },
    },
  ],
};

const OFFERTODAY_LISTING_RUNNING_PAYLOAD = {
  items: [
    {
      crawl_job_id: 'crawl-job-offertoday-running',
      persisted_status: 'running',
      status: 'running',
      source_site: 'offertoday',
      crawl_mode: 'headless',
      request_payload: {
        crawl_phase: 'listing',
      },
      queued_at: '2026-07-09T13:15:41+00:00',
      started_at: '2026-07-09T13:15:42+00:00',
      updated_at: '2026-07-09T13:29:41+00:00',
      current_page: 1122,
      total_pages: 7600,
      job_ids_collected: 5000,
      detail_target_rows: 1304,
    },
  ],
  total: 1,
  page: 1,
  page_size: 10,
  time_range: 'all',
  refreshed_at: '2026-07-09T13:29:41+00:00',
};

const OFFERTODAY_LISTING_COMPLETED_PAYLOAD = {
  items: [
    {
      crawl_job_id: 'crawl-job-offertoday-complete',
      persisted_status: 'completed',
      status: 'completed',
      source_site: 'offertoday',
      crawl_mode: 'headless',
      request_payload: {
        crawl_phase: 'listing',
      },
      queued_at: '2026-07-09T13:15:41+00:00',
      started_at: '2026-07-09T13:15:42+00:00',
      updated_at: '2026-07-09T13:29:41+00:00',
      current_page: 1122,
      total_pages: 7600,
      job_ids_collected: 5000,
      detail_target_rows: 1304,
      detail_pending: 0,
      listing_completed: true,
    },
  ],
  total: 1,
  page: 1,
  page_size: 10,
  time_range: 'all',
  refreshed_at: '2026-07-09T13:29:41+00:00',
};

const OFFERTODAY_LISTING_PARTIAL_PAYLOAD = {
  items: [
    {
      crawl_job_id: '4cee200d-9b1b-40ad-88da-8866bacd71a7',
      persisted_status: 'completed',
      status: 'completed',
      source_site: 'offertoday',
      crawl_mode: 'headless',
      request_payload: {
        crawl_phase: 'listing',
      },
      queued_at: '2026-07-14T11:28:59+00:00',
      started_at: '2026-07-14T11:29:00+00:00',
      updated_at: '2026-07-14T12:45:50+00:00',
      current_page: 2615,
      total_pages: 3040,
      job_ids_collected: 9707,
      listings_staged: 6969,
      detail_target_rows: 0,
      listing_completed: true,
      listing_partial: true,
      listing_condition_count: 152,
      listing_natural_condition_count: 45,
      listing_capped_condition_count: 107,
    },
  ],
  total: 1,
  page: 1,
  page_size: 10,
  time_range: 'all',
  refreshed_at: '2026-07-14T12:45:50+00:00',
};

describe('CrawlTasksPage', () => {
  beforeEach(() => {
    monitoringSpies.createMonitoringId.mockClear();
    monitoringSpies.logError.mockClear();
    monitoringSpies.logInfo.mockClear();
    monitoringSpies.logWarn.mockClear();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('renders the page shell and filter bar', async () => {
    vi.stubGlobal('fetch', vi.fn(() => createJsonResponse({
      items: [],
      total: 0,
      page: 1,
      page_size: 10,
      time_range: 'all',
      refreshed_at: '2026-07-09T02:00:00+00:00',
    })));

    render(<CrawlTasksPage />);

    expect(await screen.findByRole('heading', { level: 1, name: /crawl tasks/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /refresh/i })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: /status/i })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: /source site/i })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: /crawl mode/i })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: /time range/i })).toBeInTheDocument();
  });

  it('renders stable live-smoke hooks for filters, issue metadata, and task actions', async () => {
    vi.stubGlobal('fetch', vi.fn(() => createJsonResponse(MANUAL_ACTION_PAYLOAD)));

    render(<CrawlTasksPage />);

    expect(await screen.findByTestId('crawl-tasks-filter-status')).toBeInTheDocument();
    expect(screen.getByTestId('crawl-tasks-filter-source')).toBeInTheDocument();
    expect(screen.getByTestId('crawl-tasks-filter-mode')).toBeInTheDocument();
    expect(screen.getByTestId('crawl-tasks-filter-time-range')).toBeInTheDocument();
    expect(screen.getByTestId('crawl-task-issue-class')).toHaveTextContent(/manual_action_required/i);
    expect(screen.getByTestId('crawl-task-issue-code')).toHaveTextContent(/captcha_interstitial/i);
    expect(screen.getByTestId('crawl-task-issue-stage')).toHaveTextContent(/detail/i);
    expect(screen.getByTestId('crawl-task-latest-issue-text')).toHaveTextContent(/captcha/i);
    expect(screen.getByTestId('crawl-task-open-browser')).toBeInTheDocument();
    expect(screen.getByTestId('crawl-task-resume-open-browser')).toBeInTheDocument();
    expect(screen.getByTestId('crawl-task-resume-fresh')).toBeInTheDocument();
  });

  it('loads crawl tasks, renders pagination metadata, and moves to the next page', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input) => {
        const url = new URL(String(input), 'http://localhost');

        if (url.pathname !== '/api/v1/crawl-jobs/tasks') {
          return Promise.reject(new Error(`Unhandled fetch: ${url.pathname}`));
        }

        const page = url.searchParams.get('page') || '1';
        return createJsonResponse(page === '2' ? PAGE_TWO_PAYLOAD : PAGE_ONE_PAYLOAD);
      }),
    );

    render(<CrawlTasksPage />);

    expect((await screen.findAllByText(/crawl-job-1/i)).length).toBeGreaterThan(0);
    expect(screen.getByText(/11 tasks/i)).toBeInTheDocument();
    expect(screen.getByText(/page 1 of 2/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /next page/i }));

    expect((await screen.findAllByText(/crawl-job-11/i)).length).toBeGreaterThan(0);
    expect(screen.getByText(/page 2 of 2/i)).toBeInTheDocument();
  });

  it('reloads when filters change and exposes detail action scaffolding for manual-action tasks', async () => {
    const fetchSpy = vi.fn((input) => {
      const url = new URL(String(input), 'http://localhost');

      if (url.pathname !== '/api/v1/crawl-jobs/tasks') {
        return Promise.reject(new Error(`Unhandled fetch: ${url.pathname}`));
      }

      const status = url.searchParams.get('status');
      return createJsonResponse(status === 'manual_action_required' ? MANUAL_ACTION_PAYLOAD : PAGE_ONE_PAYLOAD);
    });

    vi.stubGlobal('fetch', fetchSpy);

    render(<CrawlTasksPage />);

    expect((await screen.findAllByText(/crawl-job-1/i)).length).toBeGreaterThan(0);

    fireEvent.change(screen.getByRole('combobox', { name: /status/i }), {
      target: { value: 'manual_action_required' },
    });

    expect((await screen.findAllByText(/crawl-job-manual/i)).length).toBeGreaterThan(0);
    expect(
      fetchSpy.mock.calls.some(([input]) =>
        String(input).includes('/api/v1/crawl-jobs/tasks?page=1&page_size=10&time_range=all&status=manual_action_required')
      )
    ).toBe(true);

    expect(screen.getByRole('heading', { level: 2, name: /task details/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /resume using open browser/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^resume fresh$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /cancel crawl job/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^open browser$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /check reuse status/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /close profile windows/i })).toBeInTheDocument();
  });

  it('tells the operator to change IP before resuming an OfferToday IP block', async () => {
    vi.stubGlobal('fetch', vi.fn(() => createJsonResponse(OFFERTODAY_IP_BLOCK_PAYLOAD)));

    render(<CrawlTasksPage />);

    expect(await screen.findByTestId('crawl-task-ip-block-guidance')).toHaveTextContent(
      /change your ip or network first/i,
    );
    expect(screen.getByTestId('crawl-task-latest-issue-text')).toHaveTextContent(
      /completed progress is preserved/i,
    );
    expect(screen.getByRole('button', { name: /resume using open browser/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^resume fresh$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^open browser$/i })).toBeInTheDocument();
  });

  it('does not expose resume or browser actions for identity audits', async () => {
    vi.stubGlobal('fetch', vi.fn(() => createJsonResponse(IDENTITY_AUDIT_PAYLOAD)));

    render(<CrawlTasksPage />);

    expect(await screen.findByTestId('crawl-task-resume-unsupported')).toHaveTextContent(
      /cannot be resumed automatically/i,
    );
    expect(screen.queryByRole('button', { name: /resume using open browser/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^resume fresh$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^open browser$/i })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /cancel crawl job/i })).toBeInTheDocument();
  });

  it('auto-refreshes while the page is visible', async () => {
    vi.useFakeTimers();
    const fetchSpy = vi.fn(() =>
      createJsonResponse({
        items: [],
        total: 0,
        page: 1,
        page_size: 10,
        time_range: 'all',
        refreshed_at: '2026-07-09T02:00:00+00:00',
      })
    );

    vi.stubGlobal('fetch', fetchSpy);

    render(<CrawlTasksPage />);

    expect(screen.getByRole('heading', { name: /crawl tasks/i })).toBeInTheDocument();
    expect(fetchSpy).toHaveBeenCalledTimes(1);

    await act(async () => {
      vi.advanceTimersByTime(10000);
    });

    expect(fetchSpy).toHaveBeenCalledTimes(2);
  });

  it('shows OfferToday listing runs with query-task progress instead of generic pages', async () => {
    vi.stubGlobal('fetch', vi.fn(() => createJsonResponse(OFFERTODAY_LISTING_RUNNING_PAYLOAD)));

    render(<CrawlTasksPage />);

    expect((await screen.findAllByText(/crawl-job-offertoday-running/i)).length).toBeGreaterThan(0);
    expect(screen.getByText('Query requests 1,122 / max 7,600')).toBeInTheDocument();
    expect(screen.getByText('Queue 1,304')).toBeInTheDocument();
  });

  it('shows completed listing-only OfferToday runs as ready for future detail work', async () => {
    vi.stubGlobal('fetch', vi.fn(() => createJsonResponse(OFFERTODAY_LISTING_COMPLETED_PAYLOAD)));

    render(<CrawlTasksPage />);

    expect((await screen.findAllByText(/crawl-job-offertoday-complete/i)).length).toBeGreaterThan(0);
    expect(screen.getAllByText('Listing Complete').length).toBeGreaterThan(0);
    expect(screen.getByText('Ready for detail 1,304')).toBeInTheDocument();
    expect(screen.getByText('Query requests 1,122 / max 7,600')).toBeInTheDocument();
  });

  it('distinguishes partial OfferToday completion and keeps discovered and staged counts separate', async () => {
    vi.stubGlobal('fetch', vi.fn(() => createJsonResponse(OFFERTODAY_LISTING_PARTIAL_PAYLOAD)));

    render(<CrawlTasksPage />);

    expect((await screen.findAllByText(/4cee200d-9b1b-40ad-88da-8866bacd71a7/i)).length).toBeGreaterThan(0);
    expect(screen.getAllByText('Listing Complete (Partial)').length).toBeGreaterThan(0);
    expect(screen.getByText('IDs 9,707')).toBeInTheDocument();
    expect(screen.getByText('Staged 6,969')).toBeInTheDocument();
    expect(screen.getByText('Query requests 2,615 / max 3,040')).toBeInTheDocument();
    expect(
      screen.getAllByText(/107 of 152 query conditions reached the configured page cap/i).length,
    ).toBeGreaterThan(0);
    expect(screen.queryByText(/blocked/i)).not.toBeInTheDocument();
  });
});
