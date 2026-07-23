import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import CompaniesPage from './CompaniesPage';

function mockJsonResponse(payload) {
  return Promise.resolve({
    ok: true,
    json: async () => payload,
  });
}

function mockDelayedJsonResponse(payload, delayMs) {
  return Promise.resolve({
    ok: true,
    json: () =>
      new Promise((resolve) => {
        setTimeout(() => resolve(payload), delayMs);
      }),
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
  let runItemsById;
  let createdRunResponse;
  let companyRequests;
  let createdRunCalls;
  let createdRunBodies;
  let webSearchCapability;

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
    runItemsById = {};
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
    createdRunBodies = [];
    webSearchCapability = {
      available: true,
      reason: null,
      last_test_status: 'passed',
    };

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

      if (url.pathname === '/api/v1/capabilities' && (!init.method || init.method === 'GET')) {
        return mockJsonResponse({
          ai: {
            companies: {
              web_search: webSearchCapability,
            },
          },
        });
      }

      if (url.pathname === '/api/v1/companies/enrichment-runs' && init.method === 'POST') {
        createdRunCalls += 1;
        createdRunBodies.push(JSON.parse(init.body));
        return mockJsonResponse(createdRunResponse);
      }

      if (url.pathname.startsWith('/api/v1/companies/enrichment-runs/') && (!init.method || init.method === 'GET')) {
        if (url.pathname.endsWith('/items')) {
          const runId = url.pathname.split('/')[5];
          return mockJsonResponse({
            items: runItemsById[runId] || [],
          });
        }
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
    expect(screen.getByRole('option', { name: /needs ai/i })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /ai ready/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /generate missing descriptions/i })).toBeInTheDocument();
    expect(screen.getByText('Acme Health')).toBeInTheDocument();
    expect(screen.getByText('Cyan Retail')).toBeInTheDocument();
    expect(screen.getByText(/page 1 of 2/i)).toBeInTheDocument();
    expect(screen.getByText(/descriptions ready on page/i)).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: /use web search for this run/i })).not.toBeChecked();
  });

  it('sends Web Search only when explicitly enabled for the Company run', async () => {
    const user = userEvent.setup();
    createdRunResponse.web_search_enabled = true;
    runResponsesById['run-1'] = [
      {
        ...createdRunResponse,
        status: 'running',
        pending_items: 2,
        started_at: '2026-04-19T10:00:00Z',
      },
    ];
    render(<CompaniesPage />);

    const searchOption = await screen.findByRole('checkbox', {
      name: /use web search for this run/i,
    });
    await waitFor(() => expect(searchOption).toBeEnabled());
    await user.click(searchOption);
    await user.click(screen.getByRole('button', { name: /generate missing descriptions/i }));

    expect(createdRunBodies).toEqual([{ web_search_enabled: true }]);
    expect(await screen.findByText(/^web search enabled$/i)).toBeInTheDocument();
  });

  it('displays the persisted mode of an already-active Company run', async () => {
    currentRunResponses = [
      {
        ...createdRunResponse,
        id: 'existing-run',
        status: 'pending',
        web_search_enabled: true,
      },
    ];
    runItemsById['existing-run'] = [];

    render(<CompaniesPage />);

    expect(await screen.findByText(/^web search enabled$/i)).toBeInTheDocument();
    expect(createdRunCalls).toBe(0);
  });

  it('disables Company Web Search with the upstream probe reason', async () => {
    webSearchCapability = {
      available: false,
      reason: 'The Krill Web Search probe was rejected.',
      last_test_status: 'failed',
    };
    render(<CompaniesPage />);

    const searchOption = await screen.findByRole('checkbox', {
      name: /use web search for this run/i,
    });
    expect(searchOption).toBeDisabled();
    expect(screen.getByText(/krill web search probe was rejected/i)).toBeInTheDocument();
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
    await user.click(screen.getByRole('button', { name: /^next$/i }));

    await waitFor(() => {
      expect(companyRequests.at(-1)).toBe('status=pending&q=&page=2&page_size=25');
    });
    expect(await screen.findByText('Zulu Health')).toBeInTheDocument();
    expect(screen.getByText(/page 2 of 2/i)).toBeInTheDocument();
  });

  it('jumps directly to a requested companies page', async () => {
    const user = userEvent.setup();
    render(<CompaniesPage />);

    await screen.findByText('Acme Health');

    await user.clear(screen.getByLabelText(/jump to page/i));
    await user.type(screen.getByLabelText(/jump to page/i), '2');
    await user.click(screen.getByRole('button', { name: /go/i }));

    await waitFor(() => {
      expect(companyRequests.at(-1)).toBe('status=pending&q=&page=2&page_size=25');
    });
  });

  it('returns to the latest available page when a refreshed result set makes the current page invalid', async () => {
    const user = userEvent.setup();
    render(<CompaniesPage />);

    await screen.findByText('Acme Health');
    await user.click(screen.getByRole('button', { name: /^next$/i }));
    expect(await screen.findByText('Zulu Health')).toBeInTheDocument();

    createdRunResponse = {
      id: 'run-1',
      status: 'running',
      total_items: 2,
      pending_items: 1,
      completed_items: 1,
      failed_items: 0,
      current_company_name: 'Zulu Health',
      error_message: null,
      started_at: '2026-04-19T10:00:00Z',
      completed_at: null,
      created_at: '2026-04-19T10:00:00Z',
    };
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
    companyPages['status=pending&q=&page=2&page_size=25'] = buildCompaniesPayload([], 2, 1);
    companyPages['status=pending&q=&page=1&page_size=25'] = companyPages['status=pending&q=&page=1&page_size=25#after-run'];

    await user.click(screen.getByRole('button', { name: /generate missing descriptions/i }));

    await waitFor(() => {
      expect(companyRequests).toContain('status=pending&q=&page=2&page_size=25');
      expect(companyRequests.at(-1)).toBe('status=pending&q=&page=1&page_size=25');
    });
    expect(await screen.findByText('Acme Health')).toBeInTheDocument();
    expect(screen.queryByLabelText(/jump to page/i)).not.toBeInTheDocument();
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

    await user.click(screen.getByRole('button', { name: /generate missing descriptions/i }));

    expect(createdRunCalls).toBe(1);
    expect(createdRunBodies).toEqual([{ web_search_enabled: false }]);

    await waitFor(() => {
      expect(companyRequests.at(-1)).toBe('status=pending&q=&page=1&page_size=25');
    });
    expect(await screen.findByText(/finished generating descriptions for 2 companies\. 2 succeeded, 0 failed\./i)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /open details for acme health/i }));
    expect(await within(screen.getByRole('dialog')).findByText('Acme Health AI summary')).toBeInTheDocument();
  });

  it('clears a stale list error after a run starts successfully', async () => {
    const user = userEvent.setup();
    let companiesRequestCount = 0;

    globalThis.fetch = vi.fn((input, init = {}) => {
      const url = new URL(String(input), 'http://localhost');

      if (url.pathname === '/api/v1/companies' && (!init.method || init.method === 'GET')) {
        companiesRequestCount += 1;
        if (companiesRequestCount === 1) {
          return Promise.resolve({
            ok: false,
            json: async () => ({}),
          });
        }

        return mockJsonResponse(companyPages['status=pending&q=&page=1&page_size=25']);
      }

      if (url.pathname === '/api/v1/companies/enrichment-runs/current' && (!init.method || init.method === 'GET')) {
        return mockJsonResponse(null);
      }

      if (url.pathname === '/api/v1/companies/enrichment-runs' && init.method === 'POST') {
        createdRunCalls += 1;
        return mockJsonResponse(createdRunResponse);
      }

      if (url.pathname === '/api/v1/companies/enrichment-runs/run-1' && (!init.method || init.method === 'GET')) {
        return mockJsonResponse({
          id: 'run-1',
          status: 'running',
          total_items: 2,
          pending_items: 2,
          completed_items: 0,
          failed_items: 0,
          current_company_name: null,
          error_message: null,
          started_at: '2026-04-19T10:00:00Z',
          completed_at: null,
          created_at: '2026-04-19T10:00:00Z',
        });
      }

      return Promise.reject(new Error(`Unhandled fetch: ${url.pathname}`));
    });

    render(<CompaniesPage />);

    expect(await screen.findByText('Failed to load companies')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /generate missing descriptions/i }));

    await waitFor(() => {
      expect(createdRunCalls).toBe(1);
    });
    expect(screen.queryByText('Failed to load companies')).not.toBeInTheDocument();
    expect(screen.getByText(/global backlog run started\./i)).toBeInTheDocument();
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

  it('shows at least one percent once a large run has started making progress', async () => {
    currentRunResponses = [
      {
        id: 'run-current',
        status: 'running',
        total_items: 2748,
        pending_items: 2744,
        completed_items: 1,
        failed_items: 3,
        current_company_name: 'CL Technical Services Limited',
        error_message: null,
        started_at: '2026-06-02T07:51:06Z',
        completed_at: null,
        created_at: '2026-06-02T07:51:05Z',
      },
    ];

    render(<CompaniesPage />);

    expect(await screen.findByText(/generating descriptions: 4 \/ 2748/i)).toBeInTheDocument();
    expect(screen.getByText(/^1%$/i)).toBeInTheDocument();
    expect(screen.getByText(/current company: cl technical services limited/i)).toBeInTheDocument();
  });

  it('clears stale active item state after a run reaches a terminal status', async () => {
    let runPollCalls = 0;
    let runItemsCalls = 0;
    vi.spyOn(document, 'hidden', 'get').mockImplementation(() => false);
    currentRunResponses = [
      {
        id: 'run-current',
        status: 'running',
        total_items: 2,
        pending_items: 1,
        completed_items: 0,
        failed_items: 0,
        current_company_id: 'company-1',
        current_company_name: 'Acme Health',
        error_message: null,
        started_at: '2026-04-19T10:00:00Z',
        completed_at: null,
        created_at: '2026-04-19T10:00:00Z',
      },
    ];
    runResponsesById['run-current'] = [
      {
        id: 'run-current',
        status: 'completed_with_failures',
        total_items: 2,
        pending_items: 0,
        completed_items: 1,
        failed_items: 1,
        current_company_id: null,
        current_company_name: null,
        error_message: '1 item(s) failed. First error: provider timeout',
        started_at: '2026-04-19T10:00:00Z',
        completed_at: '2026-04-19T10:01:00Z',
        created_at: '2026-04-19T10:00:00Z',
      },
    ];
    const initialCompaniesPayload = buildCompaniesPayload(
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
          id: 'company-2',
          company_id: 'company-2',
          name: 'Beta Logistics',
          industry: 'Logistics',
          location: 'Tsuen Wan',
          ai_description: null,
        },
      ],
      1,
      2,
    );
    const refreshedCompaniesPayload = buildCompaniesPayload(
      [
        {
          id: 'company-1',
          company_id: 'company-1',
          name: 'Acme Health',
          industry: 'Healthcare',
          location: 'Hong Kong',
          ai_description: 'Acme Health AI summary',
        },
        {
          id: 'company-2',
          company_id: 'company-2',
          name: 'Beta Logistics',
          industry: 'Logistics',
          location: 'Tsuen Wan',
          ai_description: null,
        },
      ],
      1,
      2,
    );
    companyPages['status=pending&q=&page=1&page_size=25'] = initialCompaniesPayload;

    const baseFetch = globalThis.fetch;
    globalThis.fetch = vi.fn((input, init = {}) => {
      const url = new URL(String(input), 'http://localhost');

      if (url.pathname === '/api/v1/companies/enrichment-runs/run-current' && (!init.method || init.method === 'GET')) {
        runPollCalls += 1;
      }

      if (url.pathname === '/api/v1/companies/enrichment-runs/run-current/items' && (!init.method || init.method === 'GET')) {
        runItemsCalls += 1;
        return mockJsonResponse(
          runItemsCalls === 1
            ? {
                items: [
                  {
                    id: 'item-1',
                    run_id: 'run-current',
                    company_id: 'company-1',
                    status: 'running',
                    error_message: null,
                  },
                  {
                    id: 'item-2',
                    run_id: 'run-current',
                    company_id: 'company-2',
                    status: 'pending',
                    error_message: null,
                  },
                ],
              }
            : {
                items: [
                  {
                    id: 'item-1',
                    run_id: 'run-current',
                    company_id: 'company-1',
                    status: 'running',
                    error_message: null,
                  },
                  {
                    id: 'item-2',
                    run_id: 'run-current',
                    company_id: 'company-2',
                    status: 'pending',
                    error_message: null,
                  },
                ],
              },
        );
      }

      return baseFetch(input, init);
    });

    vi.useFakeTimers();
    render(<CompaniesPage />);

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    companyPages['status=pending&q=&page=1&page_size=25'] = refreshedCompaniesPayload;

    expect(screen.getByText(/current company: acme health/i)).toBeInTheDocument();
    expect(within(screen.getByRole('button', { name: /open details for acme health/i })).getByText('Generating')).toBeInTheDocument();
    expect(within(screen.getByRole('button', { name: /open details for beta logistics/i })).getByText('Queued')).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(2100);
      await Promise.resolve();
      await Promise.resolve();
    });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(runPollCalls).toBe(1);
    expect(companyRequests).toHaveLength(2);
    vi.useRealTimers();
    await waitFor(() => {
      expect(screen.queryByText(/current company: acme health/i)).not.toBeInTheDocument();
    });
    await waitFor(() => {
      expect(runItemsCalls).toBeGreaterThanOrEqual(2);
    });
    expect(screen.getByText(/finished generating descriptions for 2 companies\. 1 succeeded, 1 failed\./i)).toBeInTheDocument();
    expect(screen.queryByText(/generating descriptions:/i)).not.toBeInTheDocument();
    expect(within(screen.getByRole('button', { name: /open details for acme health/i })).getByText('AI Ready')).toBeInTheDocument();
    expect(within(screen.getByRole('button', { name: /open details for beta logistics/i })).queryByText('Queued')).not.toBeInTheDocument();
  });

  it('describes pending company runs as queued before the first company starts', async () => {
    currentRunResponses = [
      {
        id: 'run-current',
        status: 'pending',
        total_items: 3,
        pending_items: 3,
        completed_items: 0,
        failed_items: 0,
        current_company_name: null,
        error_message: null,
        started_at: null,
        completed_at: null,
        created_at: '2026-04-19T10:00:00Z',
      },
    ];

    render(<CompaniesPage />);

    expect(await screen.findByText(/queued for execution/i)).toBeInTheDocument();
    expect(screen.getByText(/waiting for worker pickup/i)).toBeInTheDocument();
    expect(screen.getByText(/remaining: 3/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /generation queued/i })).toBeDisabled();
  });

  it('marks targeted companies as queued when the current run has pending run items', async () => {
    currentRunResponses = [
      {
        id: 'run-current',
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
      },
    ];
    runItemsById['run-current'] = [
      {
        id: 'item-queued-1',
        run_id: 'run-current',
        company_id: 'company-1',
        status: 'pending',
        error_message: null,
      },
      {
        id: 'item-queued-2',
        run_id: 'run-current',
        company_id: 'company-3',
        status: 'pending',
        error_message: null,
      },
    ];

    render(<CompaniesPage />);

    const acmeCard = await screen.findByRole('button', { name: /open details for acme health/i });
    const cyanCard = screen.getByRole('button', { name: /open details for cyan retail/i });

    expect(await within(acmeCard).findByText('Queued')).toBeInTheDocument();
    expect(await within(cyanCard).findByText('Queued')).toBeInTheDocument();
  });

  it('renders the latest terminal run as a completed summary instead of an active generation panel', async () => {
    currentRunResponses = [
      {
        id: 'run-terminal',
        status: 'completed_with_failures',
        total_items: 3,
        pending_items: 0,
        completed_items: 2,
        failed_items: 1,
        current_company_name: null,
        error_message: '1 item(s) failed. First error: provider timeout',
        started_at: '2026-04-19T10:00:00Z',
        completed_at: '2026-04-19T10:02:00Z',
        created_at: '2026-04-19T10:00:00Z',
      },
    ];

    render(<CompaniesPage />);

    expect(await screen.findByText(/latest run/i)).toBeInTheDocument();
    expect(screen.getByText(/completed with failures/i)).toBeInTheDocument();
    expect(screen.getByText(/finished generating descriptions for 3 companies\. 2 succeeded, 1 failed\./i)).toBeInTheDocument();
    expect(screen.getByText(/provider timeout/i)).toBeInTheDocument();
    expect(screen.queryByText(/generating descriptions:/i)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /generate missing descriptions/i })).not.toBeDisabled();
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

    await user.click(screen.getByRole('button', { name: /generate missing descriptions/i }));

    expect(await screen.findByText(/finished generating descriptions for 2 companies\. 0 succeeded, 2 failed\./i)).toBeInTheDocument();
    expect(screen.getByText(/anthropic client does not support web_search requests/i)).toBeInTheDocument();
  });

  it('marks companies with failed run items as failed when the latest terminal run includes item failures', async () => {
    currentRunResponses = [
      {
        id: 'run-terminal',
        status: 'completed_with_failures',
        total_items: 2,
        pending_items: 0,
        completed_items: 1,
        failed_items: 1,
        current_company_name: null,
        error_message: '1 item(s) failed. First error: provider timeout',
        started_at: '2026-04-19T10:00:00Z',
        completed_at: '2026-04-19T10:02:00Z',
        created_at: '2026-04-19T10:00:00Z',
      },
    ];
    runItemsById['run-terminal'] = [
      {
        id: 'item-failed',
        run_id: 'run-terminal',
        company_id: 'company-1',
        status: 'failed',
        error_message: 'provider timeout',
      },
      {
        id: 'item-completed',
        run_id: 'run-terminal',
        company_id: 'company-3',
        status: 'completed',
        error_message: null,
      },
    ];

    render(<CompaniesPage />);

    const acmeCard = await screen.findByRole('button', { name: /open details for acme health/i });
    const cyanCard = screen.getByRole('button', { name: /open details for cyan retail/i });

    expect(await within(acmeCard).findByText('Failed')).toBeInTheDocument();
    expect(within(cyanCard).getByText('Awaiting AI')).toBeInTheDocument();
  });

  it('keeps polling after a refresh failure and recovers on a later poll', async () => {
    let runPollCalls = 0;
    const realSetTimeout = window.setTimeout.bind(window);
    let pollTimeoutCalls = 0;
    vi.spyOn(window, 'setTimeout').mockImplementation((callback, delay, ...args) => {
      if (delay === 2000) {
        pollTimeoutCalls += 1;
        return realSetTimeout(callback, pollTimeoutCalls === 1 ? 0 : 25, ...args);
      }

      return realSetTimeout(callback, delay, ...args);
    });

    companyPages['status=pending&q=&page=1&page_size=25'] = companyPages['status=pending&q=&page=1&page_size=25#after-run'];

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
        return mockJsonResponse(companyPages[key]);
      }

      if (url.pathname === '/api/v1/companies/enrichment-runs/current' && (!init.method || init.method === 'GET')) {
        return mockJsonResponse(null);
      }

      if (url.pathname === '/api/v1/companies/enrichment-runs' && init.method === 'POST') {
        createdRunCalls += 1;
        return mockJsonResponse(createdRunResponse);
      }

      if (url.pathname === '/api/v1/companies/enrichment-runs/run-1' && (!init.method || init.method === 'GET')) {
        runPollCalls += 1;

        if (runPollCalls === 1) {
          return mockJsonResponse({
            id: 'run-1',
            status: 'running',
            total_items: 2,
            pending_items: 1,
            completed_items: 1,
            failed_items: 0,
            current_company_name: 'Acme Health',
            error_message: null,
            started_at: '2026-04-19T10:00:00Z',
            completed_at: null,
            created_at: '2026-04-19T10:00:00Z',
          });
        }

        if (runPollCalls === 2) {
          return Promise.reject(new Error('network down'));
        }

        return mockJsonResponse({
          id: 'run-1',
          status: 'completed',
          total_items: 2,
          pending_items: 0,
          completed_items: 2,
          failed_items: 0,
          current_company_name: null,
          error_message: null,
          started_at: '2026-04-19T10:00:00Z',
          completed_at: '2026-04-19T10:02:00Z',
          created_at: '2026-04-19T10:00:00Z',
        });
      }

      return Promise.reject(new Error(`Unhandled fetch: ${url.pathname}`));
    });

    render(<CompaniesPage />);

    await screen.findByText('Acme Health');
    fireEvent.click(screen.getByRole('button', { name: /generate missing descriptions/i }));

    expect(await screen.findByText(/current company: acme health/i)).toBeInTheDocument();
    expect(await screen.findByText(/refresh failed: network down/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /generation in progress/i })).toBeDisabled();

    await waitFor(() => {
      expect(screen.queryByText(/refresh failed: network down/i)).not.toBeInTheDocument();
    });
    expect(await screen.findByText(/finished generating descriptions for 2 companies\. 2 succeeded, 0 failed\./i)).toBeInTheDocument();
    expect(screen.getByText('Acme Health')).toBeInTheDocument();
  });

  it('pauses company run polling while the page is hidden and refreshes immediately when visible again', async () => {
    let runPollCalls = 0;
    let isHidden = false;
    vi.spyOn(document, 'hidden', 'get').mockImplementation(() => isHidden);

    currentRunResponses = [
      {
        id: 'run-current',
        status: 'running',
        total_items: 3,
        pending_items: 2,
        completed_items: 1,
        failed_items: 0,
        current_company_name: 'Acme Health',
        error_message: null,
        started_at: '2026-04-19T10:00:00Z',
        completed_at: null,
        created_at: '2026-04-19T10:00:00Z',
      },
    ];

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
        return mockJsonResponse(companyPages[key]);
      }

      if (url.pathname === '/api/v1/companies/enrichment-runs/current' && (!init.method || init.method === 'GET')) {
        return mockJsonResponse(currentRunResponses[0]);
      }

      if (url.pathname === '/api/v1/companies/enrichment-runs/run-current' && (!init.method || init.method === 'GET')) {
        runPollCalls += 1;
        const title = runPollCalls === 1 ? 'Beta Logistics' : 'Cyan Retail';
        return mockJsonResponse({
          id: 'run-current',
          status: 'running',
          total_items: 3,
          pending_items: Math.max(0, 3 - (runPollCalls + 1)),
          completed_items: runPollCalls + 1,
          failed_items: 0,
          current_company_name: title,
          error_message: null,
          started_at: '2026-04-19T10:00:00Z',
          completed_at: null,
          created_at: '2026-04-19T10:00:00Z',
        });
      }

      return Promise.reject(new Error(`Unhandled fetch: ${url.pathname}`));
    });

    vi.useFakeTimers();
    render(<CompaniesPage />);

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByText(/current company: acme health/i)).toBeInTheDocument();
    const baselineCalls = runPollCalls;
    expect(baselineCalls).toBeGreaterThanOrEqual(0);

    isHidden = true;
    await act(async () => {
      document.dispatchEvent(new Event('visibilitychange'));
      await Promise.resolve();
      await Promise.resolve();
    });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    await act(async () => {
      vi.advanceTimersByTime(5000);
    });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(runPollCalls).toBe(baselineCalls);
    expect(screen.getByText(/current company: acme health/i)).toBeInTheDocument();

    isHidden = false;
    await act(async () => {
      document.dispatchEvent(new Event('visibilitychange'));
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(runPollCalls).toBe(baselineCalls + 1);
    expect(screen.getByText(/current company: beta logistics/i)).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(2100);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(runPollCalls).toBe(baselineCalls + 2);
    expect(screen.getByText(/current company: cyan retail/i)).toBeInTheDocument();
  }, 10000);

  it('does not start a second company run refresh while the visibility-resume refresh is still in flight', async () => {
    let runPollCalls = 0;
    let isHidden = false;
    vi.spyOn(document, 'hidden', 'get').mockImplementation(() => isHidden);

    currentRunResponses = [
      {
        id: 'run-current',
        status: 'running',
        total_items: 3,
        pending_items: 2,
        completed_items: 1,
        failed_items: 0,
        current_company_name: 'Acme Health',
        error_message: null,
        started_at: '2026-04-19T10:00:00Z',
        completed_at: null,
        created_at: '2026-04-19T10:00:00Z',
      },
    ];

    globalThis.fetch = vi.fn((input, init = {}) => {
      const url = new URL(String(input), 'http://localhost');

      if (url.pathname === '/api/v1/companies' && (!init.method || init.method === 'GET')) {
        const key = [
          `status=${url.searchParams.get('status') || ''}`,
          `q=${url.searchParams.get('q') || ''}`,
          `page=${url.searchParams.get('page') || ''}`,
          `page_size=${url.searchParams.get('page_size') || ''}`,
        ].join('&');
        return mockJsonResponse(companyPages[key]);
      }

      if (url.pathname === '/api/v1/companies/enrichment-runs/current' && (!init.method || init.method === 'GET')) {
        return mockJsonResponse(currentRunResponses[0]);
      }

      if (url.pathname === '/api/v1/companies/enrichment-runs/run-current' && (!init.method || init.method === 'GET')) {
        runPollCalls += 1;
        return mockDelayedJsonResponse({
          id: 'run-current',
          status: 'running',
          total_items: 3,
          pending_items: 1,
          completed_items: 2,
          failed_items: 0,
          current_company_name: 'Beta Logistics',
          error_message: null,
          started_at: '2026-04-19T10:00:00Z',
          completed_at: null,
          created_at: '2026-04-19T10:00:00Z',
        }, 3000);
      }

      return Promise.reject(new Error(`Unhandled fetch: ${url.pathname}`));
    });

    vi.useFakeTimers();
    render(<CompaniesPage />);

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    isHidden = true;
    await act(async () => {
      document.dispatchEvent(new Event('visibilitychange'));
      await Promise.resolve();
      await Promise.resolve();
    });

    isHidden = false;
    await act(async () => {
      document.dispatchEvent(new Event('visibilitychange'));
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(runPollCalls).toBe(1);

    await act(async () => {
      vi.advanceTimersByTime(2100);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(runPollCalls).toBe(1);
  }, 10000);

  it('marks only the current_company_id match as generating when duplicate company names exist', async () => {
    companyPages['status=pending&q=&page=1&page_size=25'] = buildCompaniesPayload(
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
          id: 'company-2',
          company_id: 'company-2',
          name: 'Acme Health',
          industry: 'Healthcare',
          location: 'Kowloon',
          ai_description: null,
        },
      ],
      1,
      2,
    );
    currentRunResponses = [
      {
        id: 'run-current',
        status: 'running',
        total_items: 2,
        pending_items: 1,
        completed_items: 1,
        failed_items: 0,
        current_company_id: 'company-2',
        current_company_name: 'Acme Health',
        error_message: null,
        started_at: '2026-04-19T10:00:00Z',
        completed_at: null,
        created_at: '2026-04-19T10:00:00Z',
      },
    ];

    render(<CompaniesPage />);

    const companyCards = await screen.findAllByRole('button', { name: /open details for acme health/i });
    expect(companyCards).toHaveLength(2);
    expect(within(companyCards[0]).queryByText('Generating')).not.toBeInTheDocument();
    expect(within(companyCards[0]).getByText('Awaiting AI')).toBeInTheDocument();
    expect(within(companyCards[1]).getByText('Generating')).toBeInTheDocument();
  });
});
