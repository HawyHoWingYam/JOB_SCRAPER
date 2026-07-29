import { StrictMode } from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import taxonomyFixture from '../fixtures/current_taxonomy_responses.json';
import productFixture from '../fixtures/job_intelligence_product_surfaces.json';

const api = vi.hoisted(() => ({
  apiFetchJson: vi.fn(),
  fetchCapabilities: vi.fn(),
}));

vi.mock('../api/client', () => ({ apiFetchJson: api.apiFetchJson }));
vi.mock('../api/capabilities', () => ({
  fetchCapabilities: api.fetchCapabilities,
}));

import JobBrowser from './JobBrowser';
import { JOB_BROWSER_SESSION_KEY } from './jobBrowserSessionStorage';

function createDeferredSearchResponse() {
  let resolve;
  const promise = new Promise((resolvePromise) => {
    resolve = resolvePromise;
  });
  return {
    promise,
    resolve(payload) {
      resolve({
        ok: true,
        json: () => Promise.resolve(payload),
      });
    },
  };
}

function searchPayloadWithTitle(title) {
  return {
    ...productFixture.job_search,
    facets: searchFacets(),
    jobs: [{
      ...productFixture.job_search.jobs[0],
      id: title.toLowerCase().replaceAll(' ', '-'),
      title,
    }],
    total: 1,
    total_pages: 1,
  };
}

function searchFacets() {
  const sourceClassifications = productFixture.job_filters.source_classifications.map(
    (option, index) => ({
      ...option,
      parent_id: index === 0 ? null : 'jobsdb:6281',
      count: index === 0 ? 3 : 2,
    }),
  );
  return {
    sources: [
      { id: 'jobsdb', label: 'JobsDB', count: 3 },
      { id: 'ctgoodjobs', label: 'CTGoodJobs', count: 0 },
      { id: 'offertoday', label: 'OfferToday', count: 0 },
    ],
    employment_types: productFixture.job_filters.employment_types.map(
      (option) => ({ ...option, id: option.code, count: 2 }),
    ),
    source_classifications: sourceClassifications,
    company_industries: [
      {
        id: taxonomyFixture.company_tree.nodes[0].code,
        label: taxonomyFixture.company_tree.nodes[0].labels.en,
        parent_id: null,
        level: taxonomyFixture.company_tree.nodes[0].level,
        count: 2,
      },
    ],
  };
}

function jobSearchPayload(overrides = {}) {
  return {
    ...productFixture.job_search,
    facets: searchFacets(),
    ...overrides,
  };
}

function currentCompanyIndustryTree() {
  return {
    taxonomy: 'company_industry',
    nodes: taxonomyFixture.company_tree.nodes.map((node) => ({
      code: node.code,
      parent_code: null,
      level: node.level,
      labels: node.labels,
      order: node.order,
      is_assignable: true,
    })),
  };
}

describe('JobBrowser governed filters', () => {
  beforeEach(() => {
    window.location.hash = '#jobs';
    window.sessionStorage.clear();
    api.apiFetchJson.mockReset();
    api.fetchCapabilities.mockReset();
    api.fetchCapabilities.mockResolvedValue({
      search: {
        semantic: { available: true },
        hybrid: { available: true },
      },
    });
    api.apiFetchJson.mockImplementation((url) => {
      const path = String(url);
      if (path.includes('/jobs/filters')) {
        return Promise.resolve(productFixture.job_filters);
      }
      if (path.includes('/company-industries/tree')) {
        return Promise.resolve(currentCompanyIndustryTree());
      }
      return Promise.reject(new Error(`Unexpected API read: ${path}`));
    });
    globalThis.fetch = vi.fn((_url, options) => {
      if (!options?.body) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(productFixture.job_detail),
        });
      }
      const request = JSON.parse(options.body);
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(jobSearchPayload({
          applied_scope: request.scope,
        })),
      });
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('uses the atomic search facets for every governed selector', async () => {
    const user = userEvent.setup();
    render(<JobBrowser />);

    await user.click(await screen.findByRole('button', {
      name: 'Employment Type, 0 selected',
    }));
    expect(screen.getByRole('checkbox', {
      name: 'Full-time (2 jobs)',
    })).toBeInTheDocument();
    await user.click(screen.getByRole('button', {
      name: 'Company Industry, 0 selected',
    }));
    expect(screen.getByRole('checkbox', {
      name: 'J · Information and communications (2 jobs)',
    })).toBeInTheDocument();
    await user.click(screen.getByRole('button', {
      name: 'Source Classification Paths, 0 selected',
    }));
    expect(screen.getByRole('checkbox', {
      name: 'JobsDB · Information Technology (3 jobs)',
    })).toBeInTheDocument();
    expect(screen.queryByText('Legacy Software evidence')).not.toBeInTheDocument();
    expect(api.apiFetchJson).not.toHaveBeenCalled();
  });

  it('renders governed Employment Types without legacy fallback', async () => {
    render(<JobBrowser />);

    const assignedCard = await screen.findByRole('article', {
      name: 'Platform Engineer at Fixture Company',
    });
    expect(within(assignedCard).getByText('Full-time')).toBeInTheDocument();
    expect(within(assignedCard).getByText('Permanent')).toBeInTheDocument();
    expect(within(assignedCard).queryByText('Legacy Contract')).not.toBeInTheDocument();
    expect(
      within(assignedCard).queryByText('Legacy / AI / Category'),
    ).not.toBeInTheDocument();

    const unassignedCard = screen.getByRole('article', {
      name: 'Evidence Analyst at Review Company',
    });
    expect(
      within(unassignedCard).getByText('Employment Type: Unknown'),
    ).toBeInTheDocument();

    const unavailableCard = screen.getByRole('article', {
      name: 'Operations Coordinator at Legacy Company',
    });
    expect(
      within(unavailableCard).queryByText('Legacy Operations Taxonomy'),
    ).not.toBeInTheDocument();
  });

  it('opens job details only through the keyboard-operable View control', async () => {
    const user = userEvent.setup();
    render(<JobBrowser />);

    const card = await screen.findByRole('article', {
      name: 'Platform Engineer at Fixture Company',
    });
    await user.click(card);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    const viewButton = within(card).getByRole('button', {
      name: 'View Platform Engineer at Fixture Company',
    });
    viewButton.focus();
    await user.keyboard('{Enter}');
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('submits every governed multi-value filter through the Job Browser scope', async () => {
    const user = userEvent.setup();
    const industryNode = taxonomyFixture.company_tree.nodes[0];

    render(<JobBrowser />);

    const employmentTypes = await screen.findByRole('button', {
      name: 'Employment Type, 0 selected',
    });
    await waitFor(() => expect(employmentTypes).toBeEnabled());
    await user.click(employmentTypes);
    await user.click(screen.getByRole('checkbox', { name: 'Full-time (2 jobs)' }));
    await user.click(screen.getByRole('checkbox', { name: 'Permanent (2 jobs)' }));
    await user.click(screen.getByRole('button', {
      name: 'Source Classification Paths, 0 selected',
    }));
    await user.click(screen.getByRole('checkbox', {
      name: 'JobsDB · Information Technology (3 jobs)',
    }));
    await user.click(screen.getByRole('button', {
      name: 'Company Industry, 0 selected',
    }));
    await user.click(screen.getByRole('checkbox', {
      name: 'J · Information and communications (2 jobs)',
    }));
    await user.click(screen.getByRole('button', { name: 'Search all jobs' }));

    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(2));
    const submitted = JSON.parse(globalThis.fetch.mock.calls[1][1].body);
    expect(submitted.scope.layers).toHaveLength(1);
    expect(submitted.scope.layers[0].structured_filters).toEqual(
      expect.objectContaining({
        employment_type_codes: ['full_time', 'permanent'],
        source_classification_ids: ['jobsdb:6281'],
        company_industry_node_ids: [industryNode.code],
        employment_type: '',
        industry: '',
      }),
    );
  });

  it('hydrates exact Skill route filters and responds to in-place route changes', async () => {
    window.sessionStorage.setItem(JOB_BROWSER_SESSION_KEY, JSON.stringify({
      version: 1,
      scope: {
        layers: [{
          client_id: 'restored',
          text_expression: 'should not win',
          structured_filters: {},
        }],
      },
    }));
    globalThis.fetch = vi.fn((_url, options) => {
      const request = JSON.parse(options.body);
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
          ...productFixture.job_search,
          applied_scope: request.scope,
          layer_summaries: request.scope.layers.map((layer) => ({
            client_id: layer.client_id,
            label: 'Structured filters only',
          })),
        }),
      });
    });

    const { rerender } = render(
      <JobBrowser routeHash="#jobs?skill_ids=python" />,
    );

    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(1));
    let request = JSON.parse(globalThis.fetch.mock.calls[0][1].body);
    expect(request.scope.layers[0].structured_filters).toEqual(
      expect.objectContaining({
        skill_ids: ['python'],
      }),
    );
    expect(request.scope.layers[0].text_expression).toBe('');

    rerender(
      <JobBrowser routeHash="#jobs?skill_ids=docker" />,
    );

    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(2));
    request = JSON.parse(globalThis.fetch.mock.calls[1][1].body);
    expect(request.scope.layers[0].structured_filters).toEqual(
      expect.objectContaining({
        skill_ids: ['docker'],
      }),
    );
  });

  it('restores the applied layered scope from the current tab at page one', async () => {
    window.sessionStorage.setItem(JOB_BROWSER_SESSION_KEY, JSON.stringify({
      version: 1,
      scope: {
        layers: [
          {
            client_id: 'root',
            text_expression: 'platform',
            structured_filters: { skill_ids: ['python'] },
          },
          {
            client_id: 'refine-1',
            text_expression: '',
            structured_filters: { employment_type_codes: ['full_time'] },
          },
        ],
      },
    }));

    render(<JobBrowser routeHash="#jobs" />);

    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(1));
    const request = JSON.parse(globalThis.fetch.mock.calls[0][1].body);
    expect(request.page).toBe(1);
    expect(request.include_facets).toBe(true);
    expect(request.scope.layers).toHaveLength(2);
    expect(request.scope.layers[0]).toEqual(expect.objectContaining({
      client_id: 'root',
      text_expression: 'platform',
    }));
    expect(await screen.findByText('Layer 2')).toBeInTheDocument();
  });

  it('adds, edits, removes, and clears applied layers in place', async () => {
    const user = userEvent.setup();
    render(<JobBrowser />);
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(1));

    const searchInput = screen.getByPlaceholderText(
      'Query titles, companies, or deep scan descriptions...',
    );
    await user.type(searchInput, 'platform');
    await user.click(screen.getByRole('button', { name: 'Search all jobs' }));
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(2));
    expect(await screen.findByText('Text: platform')).toBeInTheDocument();

    await user.type(searchInput, 'remote');
    await user.click(screen.getByRole('button', { name: 'Refine current results' }));
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(3));
    expect(screen.getByText('Layer 2')).toBeInTheDocument();

    await user.click(screen.getAllByRole('button', { name: 'Edit layer' })[0]);
    expect(searchInput).toHaveValue('platform');
    await user.clear(searchInput);
    await user.type(searchInput, 'senior platform');
    await user.click(screen.getByRole('button', { name: 'Save layer' }));
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(4));
    let request = JSON.parse(globalThis.fetch.mock.calls[3][1].body);
    expect(request.scope.layers.map((layer) => layer.client_id)).toEqual([
      'root',
      'refine-1',
    ]);
    expect(request.scope.layers[0].text_expression).toBe('senior platform');

    await user.click(screen.getAllByRole('button', { name: 'Remove layer' })[1]);
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(5));
    request = JSON.parse(globalThis.fetch.mock.calls[4][1].body);
    expect(request.scope.layers.map((layer) => layer.client_id)).toEqual(['root']);

    await user.click(screen.getByRole('button', { name: 'Clear all layers' }));
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(6));
    request = JSON.parse(globalThis.fetch.mock.calls[5][1].body);
    expect(request.scope).toEqual({ layers: [] });
    expect(window.sessionStorage.getItem(JOB_BROWSER_SESSION_KEY)).toBeNull();
  });

  it('discards a pending refinement without requesting jobs', async () => {
    const user = userEvent.setup();
    render(<JobBrowser />);
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(1));

    const searchInput = screen.getByPlaceholderText(
      'Query titles, companies, or deep scan descriptions...',
    );
    await user.type(searchInput, 'unapplied');
    await user.click(screen.getByRole('button', { name: 'Discard changes' }));

    expect(searchInput).toHaveValue('');
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
  });

  it('omits facets when only changing pages', async () => {
    const user = userEvent.setup();
    globalThis.fetch = vi.fn((_url, options) => {
      const request = JSON.parse(options.body);
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(jobSearchPayload({
          applied_scope: request.scope,
          total: 30,
          total_pages: 2,
        })),
      });
    });
    render(<JobBrowser />);
    await user.click(await screen.findByRole('button', { name: 'Next' }));
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(2));
    const request = JSON.parse(globalThis.fetch.mock.calls[1][1].body);
    expect(request.page).toBe(2);
    expect(request.include_facets).toBe(false);
  });

  it('keeps the newest search response when an older request finishes later', async () => {
    const olderRequest = createDeferredSearchResponse();
    const latestRequest = createDeferredSearchResponse();
    globalThis.fetch = vi
      .fn()
      .mockImplementationOnce(() => olderRequest.promise)
      .mockImplementationOnce(() => latestRequest.promise);

    render(
      <StrictMode>
        <JobBrowser />
      </StrictMode>,
    );

    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(2));
    latestRequest.resolve(searchPayloadWithTitle('Latest Platform Role'));
    expect(await screen.findByRole('article', {
      name: 'Latest Platform Role at Fixture Company',
    })).toBeInTheDocument();

    olderRequest.resolve(searchPayloadWithTitle('Stale Platform Role'));
    await waitFor(() => {
      expect(screen.queryByRole('article', {
        name: 'Stale Platform Role at Fixture Company',
      })).not.toBeInTheDocument();
    });
    expect(screen.getByRole('article', {
      name: 'Latest Platform Role at Fixture Company',
    })).toBeInTheDocument();
  });

  it('announces when the job result list is loading', () => {
    const request = createDeferredSearchResponse();
    api.apiFetchJson.mockImplementation(() => new Promise(() => {}));
    api.fetchCapabilities.mockImplementation(() => new Promise(() => {}));
    globalThis.fetch = vi.fn(() => request.promise);

    render(<JobBrowser />);

    expect(screen.getByRole('status')).toHaveTextContent('Querying jobs…');
  });

  it('announces a job result request failure', async () => {
    globalThis.fetch = vi.fn(() => Promise.reject(new Error('Search service offline')));

    render(<JobBrowser />);

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'System Error: Search service offline',
    );
  });

  it('announces an empty job result list', async () => {
    globalThis.fetch = vi.fn(() => Promise.resolve({
      ok: true,
      json: () => Promise.resolve({
        ...productFixture.job_search,
        jobs: [],
        total: 0,
        total_pages: 0,
      }),
    }));

    render(<JobBrowser />);

    await screen.findByRole('heading', { name: 'No Jobs Found' });
    expect(screen.getByRole('status')).toHaveTextContent('No Jobs Found');
  });
});
