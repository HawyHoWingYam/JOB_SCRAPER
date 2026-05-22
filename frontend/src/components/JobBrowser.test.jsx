import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import JobBrowser from './JobBrowser';

const ALL_JOBS = [
  {
    id: 'job-1',
    title: 'Healthcare ERP Lead',
    company_name: 'Acme Health',
    company_industry: 'Healthcare',
    location: 'Hong Kong',
    employment_type: 'Full-time',
    job_taxonomy: { path: 'Information & Communication Technology / Software Development / Backend Development' },
    posted_date: '2026-04-15T00:00:00Z',
  },
  {
    id: 'job-2',
    title: 'Tech ERP Lead',
    company_name: 'Platform Labs',
    company_industry: 'Technology',
    location: 'Hong Kong',
    employment_type: 'Full-time',
    job_taxonomy: { path: 'Information & Communication Technology / Software Development / Backend Development' },
    posted_date: '2026-04-14T00:00:00Z',
  },
  {
    id: 'job-3',
    title: 'Data Analyst',
    company_name: 'General Analytics',
    company_industry: 'Healthcare',
    location: 'Hong Kong',
    employment_type: 'Contract',
    job_taxonomy: { path: 'Information & Communication Technology / Data & Analytics / Data Analysis' },
    posted_date: '2026-04-13T00:00:00Z',
  },
];

function getSearchCalls(fetchMock) {
  return fetchMock.mock.calls.filter(([input, init]) => {
    const url = new URL(String(input), 'http://localhost');
    return url.pathname === '/api/v1/jobs/search' && (init?.method || 'GET') === 'POST';
  });
}

function getLatestSearchBody(fetchMock) {
  const calls = getSearchCalls(fetchMock);
  return JSON.parse(calls.at(-1)[1].body);
}

function getExportCalls(fetchMock) {
  return fetchMock.mock.calls.filter(([input, init]) => {
    const url = new URL(String(input), 'http://localhost');
    return url.pathname === '/api/v1/jobs/search/export' && (init?.method || 'GET') === 'POST';
  });
}

function getLatestExportBody(fetchMock) {
  const calls = getExportCalls(fetchMock);
  return JSON.parse(calls.at(-1)[1].body);
}

function summarizeLayer(layer) {
  const parts = [];
  const text = layer.text_expression?.trim();

  if (text) {
    if (text.startsWith('=')) {
      parts.push(`Exact: ${text}`);
    } else if (text.startsWith('"')) {
      parts.push(`Phrase: ${text}`);
    } else {
      parts.push(`Broad: ${text}`);
    }
  }

  if (layer.structured_filters?.industry) {
    parts.push(`Industry: ${layer.structured_filters.industry}`);
  }

  return {
    client_id: layer.client_id,
    label: parts.join(' | ') || 'Structured filters only',
  };
}

function filterJobsForScope(scope) {
  let jobs = [...ALL_JOBS];

  for (const layer of scope.layers || []) {
    const text = layer.text_expression?.trim();

    if (text) {
      if (text === '=NoMatch') {
        jobs = [];
      } else if (text === '=ERP') {
        jobs = jobs.filter((job) => job.title.includes('ERP'));
      } else if (text === '"ERP system"') {
        jobs = jobs.filter((job) => job.title.includes('ERP'));
      } else if (text.toLowerCase().includes('erp')) {
        jobs = jobs.filter((job) => job.title.includes('ERP'));
      }
    }

    if (layer.structured_filters?.industry) {
      jobs = jobs.filter((job) => job.company_industry === layer.structured_filters.industry);
    }
  }

  return jobs;
}

function mockSearchResponse(body) {
  const layers = body.scope?.layers || [];
  const invalidLayer = layers.find((layer) => layer.text_expression === '"ERP system');
  if (invalidLayer) {
    return Promise.resolve({
      ok: false,
      status: 422,
      json: async () => ({
        detail: {
          code: 'invalid_search_expression',
          message: 'Unclosed quote in search expression',
          token: '"ERP system',
        },
      }),
    });
  }

  const page = body.page || 1;
  const pageSize = body.page_size || 24;
  const filteredJobs = filterJobsForScope(body.scope || { layers: [] });
  const startIndex = (page - 1) * pageSize;

  return Promise.resolve({
    ok: true,
    json: async () => ({
      jobs: filteredJobs.slice(startIndex, startIndex + pageSize),
      total: filteredJobs.length,
      page,
      page_size: pageSize,
      total_pages: Math.max(1, Math.ceil(filteredJobs.length / pageSize)),
      applied_scope: body.scope || { layers: [] },
      layer_summaries: layers.map(summarizeLayer),
    }),
  });
}

describe('JobBrowser', () => {
  let exportShouldFail = false;
  let forcedSearchErrorDetail = null;
  let capabilitiesPayload = null;

  beforeEach(() => {
    exportShouldFail = false;
    forcedSearchErrorDetail = null;
    capabilitiesPayload = {
      search: {
        lexical: { available: true },
        semantic: { available: true },
        hybrid: { available: true },
      },
      recommendations: { similar_jobs: { available: true } },
    };
    globalThis.URL.createObjectURL = vi.fn(() => 'blob:job-export');
    globalThis.URL.revokeObjectURL = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    globalThis.fetch = vi.fn((input, init = {}) => {
      const url = new URL(String(input), 'http://localhost');

      if (url.pathname === '/api/v1/capabilities') {
        return Promise.resolve({
          ok: true,
          json: async () => capabilitiesPayload,
        });
      }

      if (url.pathname === '/api/v1/jobs/filters') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            locations: [],
            regions: [],
            location_hierarchy: [],
            employment_types: ['Full-time', 'Contract'],
            industries: ['Technology', 'Healthcare'],
          }),
        });
      }

      if (url.pathname === '/api/v1/filters/job-subcategories') {
        return Promise.resolve({
          ok: true,
          json: async () => ([
            { id: 'subcat-backend', name: 'Backend Development' },
            { id: 'subcat-data', name: 'Data Analysis' },
          ]),
        });
      }

      if (url.pathname === '/api/v1/jobs/search' && (init.method || 'GET') === 'POST') {
        if (forcedSearchErrorDetail) {
          return Promise.resolve({
            ok: false,
            status: 422,
            json: async () => ({
              detail: forcedSearchErrorDetail,
            }),
          });
        }

        return mockSearchResponse(JSON.parse(init.body || '{}'));
      }

      if (url.pathname === '/api/v1/jobs/search/export' && (init.method || 'GET') === 'POST') {
        if (exportShouldFail) {
          return Promise.resolve({
            ok: false,
            status: 500,
            json: async () => ({
              detail: {
                message: 'Export failed for the current scope',
              },
            }),
          });
        }

        return Promise.resolve({
          ok: true,
          blob: async () => new Blob(['job_id,title\njob-1,Healthcare ERP Lead\n'], { type: 'text/csv' }),
        });
      }

      return Promise.reject(new Error(`Unhandled fetch: ${url.pathname}`));
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('loads the browser through POST search with an empty scope', async () => {
    render(<JobBrowser />);

    expect(await screen.findByText('Healthcare ERP Lead')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /search all jobs/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /search within results/i })).not.toBeInTheDocument();

    expect(getSearchCalls(globalThis.fetch)).toHaveLength(1);
    expect(getLatestSearchBody(globalThis.fetch)).toEqual({
      scope: { layers: [] },
      retrieval_mode: 'lexical',
      page: 1,
      page_size: 24,
    });
  });

  it('submits the selected retrieval mode with search requests', async () => {
    render(<JobBrowser />);

    await screen.findByText('Healthcare ERP Lead');

    fireEvent.change(screen.getByLabelText(/retrieval mode/i), {
      target: { value: 'semantic' },
    });
    fireEvent.change(screen.getByPlaceholderText(/query titles, companies/i), {
      target: { value: 'erp' },
    });
    fireEvent.click(screen.getByRole('button', { name: /search all jobs/i }));

    await waitFor(() => {
      expect(getLatestSearchBody(globalThis.fetch).retrieval_mode).toBe('semantic');
    });
  });

  it('disables semantic and hybrid retrieval modes when capabilities report retrieval unavailable', async () => {
    capabilitiesPayload = {
      search: {
        lexical: { available: true },
        semantic: { available: false, reason: 'retrieval_api_url_not_configured' },
        hybrid: { available: false, reason: 'retrieval_api_url_not_configured' },
      },
      recommendations: { similar_jobs: { available: false } },
    };

    render(<JobBrowser />);

    const select = await screen.findByLabelText(/retrieval mode/i);
    expect(within(select).getByRole('option', { name: /semantic/i })).toBeDisabled();
    expect(within(select).getByRole('option', { name: /hybrid/i })).toBeDisabled();
  });

  it('replaces the active scope when search all jobs is pressed', async () => {
    render(<JobBrowser />);

    await screen.findByText('Healthcare ERP Lead');

    fireEvent.change(screen.getByPlaceholderText(/query titles, companies/i), {
      target: { value: 'erp' },
    });
    fireEvent.change(screen.getByLabelText(/industry/i), {
      target: { value: 'Healthcare' },
    });
    fireEvent.click(screen.getByRole('button', { name: /search all jobs/i }));

    await waitFor(() => {
      const latestBody = getLatestSearchBody(globalThis.fetch);

      expect(latestBody.scope.layers).toEqual([
        {
          client_id: 'root',
          text_expression: 'erp',
          structured_filters: {
            employment_type: '',
            subcategory_ids: [],
            industry: 'Healthcare',
            posted_date_from: '',
            posted_date_to: '',
            experience_years_from: '',
            experience_years_to: '',
          },
        },
      ]);
      expect(latestBody.retrieval_mode).toBe('lexical');
    });

    expect(screen.getByRole('button', { name: /search within results/i })).toBeInTheDocument();
    expect(screen.getByText(/broad: erp/i)).toBeInTheDocument();
    expect(screen.getByText(/industry: healthcare/i)).toBeInTheDocument();
    expect(screen.queryByText('Tech ERP Lead')).not.toBeInTheDocument();
  });

  it('appends a refine layer when search within results is pressed', async () => {
    render(<JobBrowser />);

    await screen.findByText('Healthcare ERP Lead');

    fireEvent.change(screen.getByPlaceholderText(/query titles, companies/i), {
      target: { value: 'erp' },
    });
    fireEvent.click(screen.getByRole('button', { name: /search all jobs/i }));

    await screen.findByRole('button', { name: /search within results/i });

    fireEvent.change(screen.getByLabelText(/industry/i), {
      target: { value: 'Healthcare' },
    });
    fireEvent.click(screen.getByRole('button', { name: /search within results/i }));

    await waitFor(() => {
      const latestBody = getLatestSearchBody(globalThis.fetch);

      expect(latestBody.scope.layers).toEqual([
        {
          client_id: 'root',
          text_expression: 'erp',
          structured_filters: {
            employment_type: '',
            subcategory_ids: [],
            industry: '',
            posted_date_from: '',
            posted_date_to: '',
            experience_years_from: '',
            experience_years_to: '',
          },
        },
        {
          client_id: 'refine-1',
          text_expression: '',
          structured_filters: {
            employment_type: '',
            subcategory_ids: [],
            industry: 'Healthcare',
            posted_date_from: '',
            posted_date_to: '',
            experience_years_from: '',
            experience_years_to: '',
          },
        },
      ]);
    });

    expect(screen.getByText('Healthcare ERP Lead')).toBeInTheDocument();
    expect(screen.queryByText('Tech ERP Lead')).not.toBeInTheDocument();
  });

  it('removes one applied layer and restores the broader result set', async () => {
    render(<JobBrowser />);

    await screen.findByText('Healthcare ERP Lead');

    fireEvent.change(screen.getByPlaceholderText(/query titles, companies/i), {
      target: { value: 'erp' },
    });
    fireEvent.click(screen.getByRole('button', { name: /search all jobs/i }));
    await screen.findByRole('button', { name: /search within results/i });

    fireEvent.change(screen.getByLabelText(/industry/i), {
      target: { value: 'Healthcare' },
    });
    fireEvent.click(screen.getByRole('button', { name: /search within results/i }));

    await screen.findByText(/industry: healthcare/i);

    const scopeTrail = screen.getByLabelText(/active scope trail/i);
    const refineSummary = within(scopeTrail).getByText(/industry: healthcare/i).closest('.scope-trail-item');
    fireEvent.click(within(refineSummary).getByRole('button', { name: /remove layer/i }));

    await waitFor(() => {
      const latestBody = getLatestSearchBody(globalThis.fetch);
      expect(latestBody.scope.layers).toHaveLength(1);
    });

    expect(screen.getByText('Healthcare ERP Lead')).toBeInTheDocument();
    expect(screen.getByText('Tech ERP Lead')).toBeInTheDocument();
  });

  it('keeps the current results when the server rejects the draft syntax', async () => {
    render(<JobBrowser />);

    await screen.findByText('Healthcare ERP Lead');

    fireEvent.change(screen.getByPlaceholderText(/query titles, companies/i), {
      target: { value: 'erp' },
    });
    fireEvent.click(screen.getByRole('button', { name: /search all jobs/i }));

    await screen.findByRole('button', { name: /search within results/i });
    fireEvent.change(screen.getByPlaceholderText(/query titles, companies/i), {
      target: { value: '"ERP system' },
    });
    fireEvent.click(screen.getByRole('button', { name: /search within results/i }));

    expect(await screen.findByText(/unclosed quote/i)).toBeInTheDocument();
    expect(screen.getByText('Healthcare ERP Lead')).toBeInTheDocument();
    expect(screen.getByText('Tech ERP Lead')).toBeInTheDocument();
    expect(screen.getByText(/broad: erp/i)).toBeInTheDocument();
  });

  it('preserves the scope trail and recovery actions when a refine returns no results', async () => {
    render(<JobBrowser />);

    await screen.findByText('Healthcare ERP Lead');

    fireEvent.change(screen.getByPlaceholderText(/query titles, companies/i), {
      target: { value: 'erp' },
    });
    fireEvent.click(screen.getByRole('button', { name: /search all jobs/i }));

    await screen.findByRole('button', { name: /search within results/i });
    fireEvent.change(screen.getByPlaceholderText(/query titles, companies/i), {
      target: { value: '=NoMatch' },
    });
    fireEvent.click(screen.getByRole('button', { name: /search within results/i }));

    expect(await screen.findByText(/no profiles found/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/active scope trail/i)).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: /remove layer/i }).length).toBeGreaterThan(0);
  });

  it('exports the active scope instead of pending draft edits', async () => {
    render(<JobBrowser />);

    await screen.findByText('Healthcare ERP Lead');

    fireEvent.change(screen.getByPlaceholderText(/query titles, companies/i), {
      target: { value: 'erp' },
    });
    fireEvent.click(screen.getByRole('button', { name: /search all jobs/i }));

    await screen.findByRole('button', { name: /search within results/i });
    fireEvent.change(screen.getByPlaceholderText(/query titles, companies/i), {
      target: { value: '=NoMatch' },
    });
    fireEvent.click(screen.getByRole('button', { name: /export 2 results/i }));

    await waitFor(() => {
      expect(getExportCalls(globalThis.fetch)).toHaveLength(1);
    });

    expect(getLatestExportBody(globalThis.fetch)).toEqual({
      scope: {
        layers: [
          {
            client_id: 'root',
            text_expression: 'erp',
            structured_filters: {
              employment_type: '',
              subcategory_ids: [],
              industry: '',
              posted_date_from: '',
              posted_date_to: '',
              experience_years_from: '',
              experience_years_to: '',
            },
          },
        ],
      },
      retrieval_mode: 'lexical',
    });
    expect(screen.getByText(/export uses current results, not pending edits/i)).toBeInTheDocument();
    expect(globalThis.URL.createObjectURL).toHaveBeenCalled();
  });

  it('disables export when the active scope has zero results', async () => {
    render(<JobBrowser />);

    await screen.findByText('Healthcare ERP Lead');

    fireEvent.change(screen.getByPlaceholderText(/query titles, companies/i), {
      target: { value: '=NoMatch' },
    });
    fireEvent.click(screen.getByRole('button', { name: /search all jobs/i }));

    expect(await screen.findByRole('button', { name: /export 0 results/i })).toBeDisabled();
  });

  it('shows a scoped error when export fails without clearing the list', async () => {
    render(<JobBrowser />);

    await screen.findByText('Healthcare ERP Lead');

    fireEvent.change(screen.getByPlaceholderText(/query titles, companies/i), {
      target: { value: 'erp' },
    });
    fireEvent.click(screen.getByRole('button', { name: /search all jobs/i }));

    await screen.findByRole('button', { name: /export 2 results/i });
    exportShouldFail = true;
    fireEvent.click(screen.getByRole('button', { name: /export 2 results/i }));

    expect(await screen.findByText(/export failed for the current scope/i)).toBeInTheDocument();
    expect(screen.getByText('Healthcare ERP Lead')).toBeInTheDocument();
    expect(screen.getByText('Tech ERP Lead')).toBeInTheDocument();
  });

  it('formats validation detail arrays into a readable system error', async () => {
    render(<JobBrowser />);

    await screen.findByText('Healthcare ERP Lead');

    forcedSearchErrorDetail = [
      {
        loc: ['body', 'scope', 'layers', 0, 'structured_filters', 'posted_date_from'],
        msg: 'Input should be a valid date or datetime, input is too short',
      },
      {
        loc: ['body', 'scope', 'layers', 0, 'structured_filters', 'experience_years_from'],
        msg: 'Input should be a valid integer, unable to parse string as an integer',
      },
    ];

    fireEvent.change(screen.getByPlaceholderText(/query titles, companies/i), {
      target: { value: 'erp' },
    });
    fireEvent.click(screen.getByRole('button', { name: /search all jobs/i }));

    expect(
      await screen.findByText(
        /scope\.layers\.0\.structured_filters\.posted_date_from: input should be a valid date or datetime, input is too short/i,
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(/scope\.layers\.0\.structured_filters\.experience_years_from: input should be a valid integer/i)).toBeInTheDocument();
  });
});
