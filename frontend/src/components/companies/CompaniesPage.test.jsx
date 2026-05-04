import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import CompaniesPage from './CompaniesPage';

function mockJsonResponse(payload) {
  return Promise.resolve({
    ok: true,
    json: async () => payload,
  });
}

function buildCompaniesPayload(items, page = 1, total = items.length, pageSize = 25) {
  const totalPages = total === 0 ? 0 : Math.ceil(total / pageSize);
  return {
    items,
    total,
    page,
    page_size: pageSize,
    total_pages: totalPages,
  };
}

describe('CompaniesPage', () => {
  let companyPages;
  let currentRunResponses;
  let runResponsesById;
  let createdRunResponse;
  let companyRequests;
  let createdRunCalls;

  beforeEach(() => {
    companyPages = {
      'status=pending&q=&page=1&page_size=25': buildCompaniesPayload(
        [
          {
            id: 'company-1',
            company_id: 'company-1',
            name: 'Acme Health',
            industry: 'Healthcare',
            location: 'Hong Kong',
            ai_description: null,
          },
          {
            id: 'company-3',
            company_id: 'company-3',
            name: 'Cyan Retail',
            industry: 'Retail',
            location: 'Kowloon',
            ai_description: null,
          },
        ],
        1,
        30,
      ),
      'status=all&q=beta&page=1&page_size=25': buildCompaniesPayload(
        [
          {
            id: 'company-2',
            company_id: 'company-2',
            name: 'Beta Logistics',
            industry: 'Logistics',
            location: 'Tsuen Wan',
            ai_description: 'Regional logistics operator focused on supply chain roles.',
          },
        ],
        1,
        1,
      ),
      'status=pending&q=&page=2&page_size=25': buildCompaniesPayload(
        [
          {
            id: 'company-26',
            company_id: 'company-26',
            name: 'Zulu Health',
            industry: 'Healthcare',
            location: 'Sha Tin',
            ai_description: null,
          },
        ],
        2,
        30,
      ),
      'status=pending&q=&page=1&page_size=25#after-run': buildCompaniesPayload(
        [
          {
            id: 'company-1',
            company_id: 'company-1',
            name: 'Acme Health',
            industry: 'Healthcare',
            location: 'Hong Kong',
            ai_description: 'Acme Health AI summary',
          },
        ],
        1,
        1,
      ),
    };
    currentRunResponses = [null];
    runResponsesById = {};
    createdRunResponse = {
      id: 'run-1',
      status: 'pending',
      total_items: 2,
      pending_items: 2,
      completed_items: 0,
      failed_items: 0,
      current_company_name: null,
      error_message: null,
      started_at: null,
      completed_at: null,
      created_at: '2026-04-19T10:00:00Z',
    };
    companyRequests = [];
    createdRunCalls = 0;

    globalThis.fetch = vi.fn((input, init = {}) => {
      const url = new URL(String(input), 'http://localhost');

      if (url.pathname === '/api/v1/companies' && (!init.method || init.method === 'GET')) {
        const key = [
          `status=${url.searchParams.get('status') || ''}`,
          `q=${url.searchParams.get('q') || ''}`,
          `page=${url.searchParams.get('page') || ''}`,
          `page_size=${url.searchParams.get('page_size') || ''}`,
        ].join('&');
        companyRequests.push(key);
        const payload = companyPages[key];
        if (!payload) {
          return Promise.reject(new Error(`Unhandled companies query: ${key}`));
        }
        return mockJsonResponse(payload);
      }

      if (url.pathname === '/api/v1/companies/enrichment-runs/current' && (!init.method || init.method === 'GET')) {
        const payload = currentRunResponses.length > 1
          ? currentRunResponses.shift()
          : currentRunResponses[0];
        return mockJsonResponse(payload);
      }

      if (url.pathname === '/api/v1/companies/enrichment-runs' && init.method === 'POST') {
        createdRunCalls += 1;
        return mockJsonResponse(createdRunResponse);
      }

      if (url.pathname.startsWith('/api/v1/companies/enrichment-runs/') && (!init.method || init.method === 'GET')) {
        const runId = url.pathname.split('/')[5];
        const responses = runResponsesById[runId];
        if (!responses || responses.length === 0) {
          return Promise.reject(new Error(`Unhandled run poll for ${runId}`));
        }
        const payload = responses.length > 1 ? responses.shift() : responses[0];
        return mockJsonResponse(payload);
      }

      return Promise.reject(new Error(`Unhandled fetch: ${url.pathname}`));
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('defaults to pending companies with server-side pagination', async () => {
    render(<CompaniesPage />);

    expect(await screen.findByRole('heading', { name: /companies/i })).toBeInTheDocument();
    expect(companyRequests[0]).toBe('status=pending&q=&page=1&page_size=25');
    expect(screen.getByText('Acme Health')).toBeInTheDocument();
    expect(screen.getByText('Cyan Retail')).toBeInTheDocument();
    expect(screen.getByText(/page 1 of 2/i)).toBeInTheDocument();
  });

  it('resets to page 1 when search or status filters change', async () => {
    const user = userEvent.setup();
    render(<CompaniesPage />);

    await screen.findByText('Acme Health');

    await user.selectOptions(screen.getByLabelText(/status/i), 'all');
    await user.clear(screen.getByLabelText(/search companies/i));
    await user.type(screen.getByLabelText(/search companies/i), 'beta');
    await user.click(screen.getByRole('button', { name: /search/i }));

    await waitFor(() => {
      expect(companyRequests.at(-1)).toBe('status=all&q=beta&page=1&page_size=25');
    });
    expect(await screen.findByText('Beta Logistics')).toBeInTheDocument();
  });

  it('keeps the active filters while paginating', async () => {
    const user = userEvent.setup();
    render(<CompaniesPage />);

    await screen.findByText('Acme Health');
    await user.click(screen.getByRole('button', { name: /next page/i }));

    await waitFor(() => {
      expect(companyRequests.at(-1)).toBe('status=pending&q=&page=2&page_size=25');
    });
    expect(await screen.findByText('Zulu Health')).toBeInTheDocument();
    expect(screen.getByText(/page 2 of 2/i)).toBeInTheDocument();
  });

  it('creates a persisted global run and refreshes the current page after completion', async () => {
    const user = userEvent.setup();
    render(<CompaniesPage />);

    await screen.findByText('Acme Health');

    runResponsesById['run-1'] = [
      {
        id: 'run-1',
        status: 'completed',
        total_items: 2,
        pending_items: 0,
        completed_items: 2,
        failed_items: 0,
        current_company_name: null,
        error_message: null,
        started_at: '2026-04-19T10:00:00Z',
        completed_at: '2026-04-19T10:01:00Z',
        created_at: '2026-04-19T10:00:00Z',
      },
    ];
    companyPages['status=pending&q=&page=1&page_size=25'] = companyPages['status=pending&q=&page=1&page_size=25#after-run'];

    await user.click(screen.getByRole('button', { name: /generate all pending descriptions/i }));

    expect(createdRunCalls).toBe(1);
    expect(screen.getByText(/global backlog run/i)).toBeInTheDocument();
    expect(screen.getByText(/generating descriptions: 2 \/ 2/i)).toBeInTheDocument();

    await waitFor(() => {
      expect(companyRequests.at(-1)).toBe('status=pending&q=&page=1&page_size=25');
    });
    expect(await screen.findByText(/finished generating descriptions for 2 companies\. 2 succeeded, 0 failed\./i)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /open details for acme health/i }));
    expect(await within(screen.getByRole('dialog')).findByText('Acme Health AI summary')).toBeInTheDocument();
  });

  it('adopts an existing active run and disables duplicate creation', async () => {
    currentRunResponses = [
      {
        id: 'run-current',
        status: 'running',
        total_items: 3,
        pending_items: 2,
        completed_items: 1,
        failed_items: 0,
        current_company_name: 'Beta Logistics',
        error_message: null,
        started_at: '2026-04-19T10:00:00Z',
        completed_at: null,
        created_at: '2026-04-19T10:00:00Z',
      },
    ];

    render(<CompaniesPage />);

    expect(await screen.findByText(/generating descriptions: 1 \/ 3/i)).toBeInTheDocument();
    expect(screen.getByText(/current company: beta logistics/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /generation in progress/i })).toBeDisabled();
    expect(createdRunCalls).toBe(0);
  });

  it('opens the detail modal and shows the current AI description text', async () => {
    const user = userEvent.setup();
    render(<CompaniesPage />);

    await user.click(await screen.findByRole('button', { name: /open details for acme health/i }));

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByRole('heading', { name: 'Acme Health' })).toBeInTheDocument();
    expect(within(dialog).getByText(/No AI description yet\. Generate one for this company\./i)).toBeInTheDocument();
  });

  it('shows the run failure reason when a terminal run completes with failures', async () => {
    const user = userEvent.setup();
    render(<CompaniesPage />);

    await screen.findByText('Acme Health');

    runResponsesById['run-1'] = [
      {
        id: 'run-1',
        status: 'failed',
        total_items: 2,
        pending_items: 0,
        completed_items: 0,
        failed_items: 2,
        current_company_name: null,
        error_message: 'anthropic client does not support web_search requests',
        started_at: '2026-04-19T10:00:00Z',
        completed_at: '2026-04-19T10:01:00Z',
        created_at: '2026-04-19T10:00:00Z',
      },
    ];

    await user.click(screen.getByRole('button', { name: /generate all pending descriptions/i }));

    expect(await screen.findByText(/finished generating descriptions for 2 companies\. 0 succeeded, 2 failed\./i)).toBeInTheDocument();
    expect(screen.getByText(/anthropic client does not support web_search requests/i)).toBeInTheDocument();
  });
});
