import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

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
            category_ids: categories.slice(0, 1).map((category) => category.id),
            max_pages: 4,
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
  default: () => <div>Scrape Progress Stub</div>,
}));

import ScheduleManager from './ScheduleManager';

function mockJsonResponse(payload) {
  return Promise.resolve({
    ok: true,
    json: async () => payload,
  });
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

describe('ScheduleManager', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn((input, init) => {
      const url = String(input);

      if (url === '/api/v1/schedules') {
        return mockJsonResponse({ schedules: MIXED_SCHEDULES });
      }

      if (url === '/api/categories') {
        return mockJsonResponse({ categories: JOBSDB_CATEGORIES });
      }

      if (url === '/api/categories?source_site=jobsdb') {
        return mockJsonResponse({ categories: JOBSDB_CATEGORIES });
      }

      if (url === '/api/categories?source_site=ctgoodjobs') {
        return mockJsonResponse({ categories: CTGOODJOBS_CATEGORIES });
      }

      if (url === '/api/v1/scrape/progress') {
        return mockJsonResponse({ active: {}, all: {}, has_active: false });
      }

      if (url === '/api/v1/schedules/run-now' && init?.method === 'POST') {
        return mockJsonResponse({ message: 'Scraping started' });
      }

      if (url === '/api/v1/schedules' && init?.method === 'POST') {
        return mockJsonResponse({ id: 'created-schedule' });
      }

      return Promise.reject(new Error(`Unhandled fetch: ${url}`));
    }));

    vi.spyOn(window, 'confirm').mockReturnValue(true);
  });

  afterEach(() => {
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

  it('posts jobsdb run-now payloads with integer category ids and source_site', async () => {
    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await screen.findByText('Task Control Board');
    fireEvent.click(screen.getByRole('button', { name: /direct override/i }));
    fireEvent.click(screen.getByRole('checkbox', { name: /engineering/i }));
    fireEvent.click(screen.getByRole('button', { name: /engage scanner/i }));

    await waitFor(() => {
      const runNowCall = globalThis.fetch.mock.calls.find(
        ([url, request]) => url === '/api/v1/schedules/run-now' && request?.method === 'POST',
      );

      expect(runNowCall).toBeTruthy();
      expect(JSON.parse(runNowCall[1].body)).toEqual({
        source_site: 'jobsdb',
        category_ids: [1200],
        max_pages: 3,
      });
    });
  });

  it('posts ctgoodjobs run-now payloads with string category ids and source_site', async () => {
    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    fireEvent.change(screen.getByRole('combobox', { name: /data source/i }), {
      target: { value: 'ctgoodjobs' },
    });
    fireEvent.click(screen.getByRole('button', { name: /direct override/i }));
    fireEvent.click(await screen.findByRole('checkbox', { name: /information technology/i }));
    fireEvent.click(screen.getByRole('button', { name: /engage scanner/i }));

    await waitFor(() => {
      const runNowCall = globalThis.fetch.mock.calls.find(
        ([url, request]) => url === '/api/v1/schedules/run-now' && request?.method === 'POST',
      );

      expect(runNowCall).toBeTruthy();
      expect(JSON.parse(runNowCall[1].body)).toEqual({
        source_site: 'ctgoodjobs',
        category_ids: ['ctgoodjobs:021'],
        max_pages: 3,
      });
    });
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
        category_ids: ['ctgoodjobs:021'],
        max_pages: 4,
      });
    });
  });

  it('renders source-specific empty copy when the current source has no schedules', async () => {
    vi.stubGlobal('fetch', vi.fn((input, init) => {
      const url = String(input);

      if (url === '/api/v1/schedules') {
        return mockJsonResponse({
          schedules: [MIXED_SCHEDULES[0]],
        });
      }

      if (url === '/api/categories?source_site=jobsdb') {
        return mockJsonResponse({ categories: JOBSDB_CATEGORIES });
      }

      if (url === '/api/categories?source_site=ctgoodjobs') {
        return mockJsonResponse({ categories: CTGOODJOBS_CATEGORIES });
      }

      if (url === '/api/v1/scrape/progress') {
        return mockJsonResponse({ active: {}, all: {}, has_active: false });
      }

      if (url === '/api/v1/schedules/run-now' && init?.method === 'POST') {
        return mockJsonResponse({ message: 'Scraping started' });
      }

      return Promise.reject(new Error(`Unhandled fetch: ${url}`));
    }));

    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    fireEvent.change(screen.getByRole('combobox', { name: /data source/i }), {
      target: { value: 'ctgoodjobs' },
    });

    expect(await screen.findByText('No CTgoodjobs automated tasks')).toBeInTheDocument();
  });

  it('shows a source badge on each rendered schedule card', async () => {
    vi.stubGlobal('fetch', vi.fn((input, init) => {
      const url = String(input);

      if (url === '/api/v1/schedules') {
        return mockJsonResponse({
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
        });
      }

      if (url === '/api/categories?source_site=jobsdb') {
        return mockJsonResponse({ categories: JOBSDB_CATEGORIES });
      }

      if (url === '/api/v1/scrape/progress') {
        return mockJsonResponse({ active: {}, all: {}, has_active: false });
      }

      if (url === '/api/v1/schedules/run-now' && init?.method === 'POST') {
        return mockJsonResponse({ message: 'Scraping started' });
      }

      return Promise.reject(new Error(`Unhandled fetch: ${url}`));
    }));

    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    const scheduleTitle = await screen.findByText('Nightly Import');
    const scheduleCard = scheduleTitle.closest('.schedule-card');

    expect(scheduleCard).not.toBeNull();
    expect(within(scheduleCard).getByText('JobsDB')).toBeInTheDocument();
  });
});
