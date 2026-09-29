import { StrictMode } from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
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
  };
}

function fetchCallsFor(pathname) {
  return globalThis.fetch.mock.calls.filter(([input]) => (
    new URL(String(input), 'http://localhost').pathname === pathname
  ));
}

function jobSearchCalls() {
  return fetchCallsFor('/api/jobs/search');
}

function facetSearchCalls() {
  return fetchCallsFor('/api/jobs/search/facets');
}

function jobSearchPayload(overrides = {}) {
  return {
    ...productFixture.job_search,
    facets: searchFacets(),
    ...overrides,
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
      return Promise.reject(new Error(`Unexpected API read: ${path}`));
    });
    globalThis.fetch = vi.fn((input, options) => {
      const url = new URL(String(input), 'http://localhost');
      if (!options?.body) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(productFixture.job_detail),
        });
      }
      if (url.pathname === '/api/jobs/search/facets') {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(searchFacets()),
        });
      }
      const request = JSON.parse(options.body);
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(jobSearchPayload({
          applied_scope: request.scope,
          facets: null,
        })),
      });
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('uses progressively loaded search facets for governed selectors', async () => {
    const user = userEvent.setup();
    render(<JobBrowser />);

    const employmentTypes = await screen.findByRole('button', {
      name: 'Employment Type, 0 selected',
    });
    await waitFor(() => expect(employmentTypes).toBeEnabled());
    await user.click(employmentTypes);
    expect(screen.getByRole('checkbox', {
      name: 'Full-time (2 jobs)',
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

  it('renders the compact experience label from the original search-card bounds', async () => {
    globalThis.fetch = vi.fn((input, options) => {
      const url = new URL(String(input), 'http://localhost');
      if (url.pathname === '/api/jobs/search/facets') {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(searchFacets()) });
      }
      const request = JSON.parse(options.body);
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(jobSearchPayload({
          applied_scope: request.scope,
          jobs: [{
            ...productFixture.job_search.jobs[0],
            experience_level: 'mid_level',
            experience_min_years: 1,
            experience_max_years: 5,
          }],
          total: 1,
          total_pages: 1,
        })),
      });
    });

    render(<JobBrowser />);

    const card = await screen.findByRole('article', {
      name: 'Platform Engineer at Fixture Company',
    });
    expect(within(card).getByText('Experience: 1+')).toBeInTheDocument();
    expect(within(card).queryByText(/1–5/)).not.toBeInTheDocument();
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

  it('submits governed multi-value filters through the Job Browser scope', async () => {
    const user = userEvent.setup();

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
    await user.click(screen.getByRole('button', { name: 'Search all jobs' }));

    await waitFor(() => expect(jobSearchCalls()).toHaveLength(2));
    const submitted = JSON.parse(jobSearchCalls()[1][1].body);
    expect(submitted.scope.layers).toHaveLength(1);
    expect(submitted.scope.layers[0].structured_filters).toEqual(
      expect.objectContaining({
        employment_type_codes: ['full_time', 'permanent'],
        source_classification_ids: ['jobsdb:6281'],
        employment_type: '',
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
    globalThis.fetch = vi.fn((input, options) => {
      const url = new URL(String(input), 'http://localhost');
      if (url.pathname === '/api/jobs/search/facets') {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(searchFacets()),
        });
      }
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

    await waitFor(() => expect(jobSearchCalls()).toHaveLength(1));
    let request = JSON.parse(jobSearchCalls()[0][1].body);
    expect(request.scope.layers[0].structured_filters).toEqual(
      expect.objectContaining({
        skill_ids: ['python'],
      }),
    );
    expect(request.scope.layers[0].text_expression).toBe('');

    rerender(
      <JobBrowser routeHash="#jobs?skill_ids=docker" />,
    );

    await waitFor(() => expect(jobSearchCalls()).toHaveLength(2));
    request = JSON.parse(jobSearchCalls()[1][1].body);
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

    await waitFor(() => expect(jobSearchCalls()).toHaveLength(1));
    const request = JSON.parse(jobSearchCalls()[0][1].body);
    expect(request.page).toBe(1);
    expect(request.include_facets).toBe(false);
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
    await waitFor(() => expect(jobSearchCalls()).toHaveLength(1));

    const searchInput = screen.getByPlaceholderText(
      'Search Job Description...',
    );
    await user.type(searchInput, 'platform');
    await user.click(screen.getByRole('button', { name: 'Search all jobs' }));
    await waitFor(() => expect(jobSearchCalls()).toHaveLength(2));
    expect(await screen.findByText('Text: platform')).toBeInTheDocument();
    const appliedLayers = screen.getByRole('region', { name: 'Applied layers' });
    expect(within(appliedLayers).getByRole('heading', { name: 'Applied layers' }))
      .toBeInTheDocument();
    const firstLayer = within(appliedLayers).getByRole('group', { name: 'Layer 1' });
    expect(within(firstLayer).getByRole('button', { name: 'Edit layer' }))
      .toBeInTheDocument();
    expect(within(firstLayer).getByRole('button', { name: 'Remove layer' }))
      .toBeInTheDocument();
    expect(within(appliedLayers).getByRole('button', { name: 'Clear all layers' }))
      .toBeInTheDocument();

    await user.type(searchInput, 'remote');
    await user.click(screen.getByRole('button', { name: 'Refine current results' }));
    await waitFor(() => expect(jobSearchCalls()).toHaveLength(3));
    expect(screen.getByText('Layer 2')).toBeInTheDocument();

    await user.click(screen.getAllByRole('button', { name: 'Edit layer' })[0]);
    expect(searchInput).toHaveValue('platform');
    await user.clear(searchInput);
    await user.type(searchInput, 'senior platform');
    await user.click(screen.getByRole('button', { name: 'Save layer' }));
    await waitFor(() => expect(jobSearchCalls()).toHaveLength(4));
    let request = JSON.parse(jobSearchCalls()[3][1].body);
    expect(request.scope.layers.map((layer) => layer.client_id)).toEqual([
      'root',
      'refine-1',
    ]);
    expect(request.scope.layers[0].text_expression).toBe('senior platform');

    await user.click(screen.getAllByRole('button', { name: 'Remove layer' })[1]);
    await waitFor(() => expect(jobSearchCalls()).toHaveLength(5));
    request = JSON.parse(jobSearchCalls()[4][1].body);
    expect(request.scope.layers.map((layer) => layer.client_id)).toEqual(['root']);

    await user.click(screen.getByRole('button', { name: 'Clear all layers' }));
    await waitFor(() => expect(jobSearchCalls()).toHaveLength(6));
    request = JSON.parse(jobSearchCalls()[5][1].body);
    expect(request.scope).toEqual({ layers: [] });
    expect(window.sessionStorage.getItem(JOB_BROWSER_SESSION_KEY)).toBeNull();
  });

  it('makes Enter follow the visible replace action while edit Enter saves in place', async () => {
    const user = userEvent.setup();
    render(<JobBrowser />);
    await waitFor(() => expect(jobSearchCalls()).toHaveLength(1));

    const searchInput = screen.getByPlaceholderText('Search Job Description...');
    await user.type(searchInput, 'first description{Enter}');
    await waitFor(() => expect(jobSearchCalls()).toHaveLength(2));
    let request = JSON.parse(jobSearchCalls()[1][1].body);
    expect(request.scope.layers).toEqual([
      expect.objectContaining({ client_id: 'root', text_expression: 'first description' }),
    ]);

    await user.type(searchInput, 'replacement description{Enter}');
    await waitFor(() => expect(jobSearchCalls()).toHaveLength(3));
    request = JSON.parse(jobSearchCalls()[2][1].body);
    expect(request.scope.layers).toEqual([
      expect.objectContaining({ client_id: 'root', text_expression: 'replacement description' }),
    ]);
    expect(screen.getByText(/Use Refine current results to add another AND layer/))
      .toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Edit layer' }));
    await user.clear(searchInput);
    await user.type(searchInput, 'edited description{Enter}');
    await waitFor(() => expect(jobSearchCalls()).toHaveLength(4));
    request = JSON.parse(jobSearchCalls()[3][1].body);
    expect(request.scope.layers).toEqual([
      expect.objectContaining({ client_id: 'root', text_expression: 'edited description' }),
    ]);
  });

  it('discards a pending refinement without requesting jobs', async () => {
    const user = userEvent.setup();
    render(<JobBrowser />);
    await waitFor(() => expect(jobSearchCalls()).toHaveLength(1));

    const searchInput = screen.getByPlaceholderText(
      'Search Job Description...',
    );
    await user.type(searchInput, 'unapplied');
    await user.click(screen.getByRole('button', { name: 'Discard changes' }));

    expect(searchInput).toHaveValue('');
    expect(jobSearchCalls()).toHaveLength(1);
  });

  it('omits facets when only changing pages', async () => {
    const user = userEvent.setup();
    globalThis.fetch = vi.fn((input, options) => {
      const url = new URL(String(input), 'http://localhost');
      if (url.pathname === '/api/jobs/search/facets') {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(searchFacets()),
        });
      }
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
    await waitFor(() => expect(facetSearchCalls()).toHaveLength(1));
    await user.click(await screen.findByRole('button', { name: 'Next' }));
    await waitFor(() => expect(jobSearchCalls()).toHaveLength(2));
    const request = JSON.parse(jobSearchCalls()[1][1].body);
    expect(request.page).toBe(2);
    expect(request.include_facets).toBe(false);
    expect(facetSearchCalls()).toHaveLength(1);
  });

  it('keeps paging on the applied retrieval mode until a new search succeeds', async () => {
    const user = userEvent.setup();
    globalThis.fetch = vi.fn((input, options) => {
      const url = new URL(String(input), 'http://localhost');
      if (url.pathname === '/api/jobs/search/facets') {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(searchFacets()) });
      }
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
    await waitFor(() => expect(jobSearchCalls()).toHaveLength(1));

    await user.selectOptions(screen.getByLabelText('Retrieval mode'), 'semantic');
    expect(screen.getByText('Lexical retrieval')).toBeInTheDocument();
    expect(screen.getByText(/Apply the search to use this mode/)).toBeInTheDocument();
    expect(jobSearchCalls()).toHaveLength(1);

    await user.click(screen.getByRole('button', { name: 'Next' }));
    await waitFor(() => expect(jobSearchCalls()).toHaveLength(2));
    expect(JSON.parse(jobSearchCalls()[1][1].body).retrieval_mode).toBe('lexical');

    await user.click(screen.getByRole('button', { name: 'Search all jobs' }));
    await waitFor(() => expect(jobSearchCalls()).toHaveLength(3));
    expect(JSON.parse(jobSearchCalls()[2][1].body).retrieval_mode).toBe('semantic');
    expect(await screen.findByText('Semantic retrieval')).toBeInTheDocument();
  });

  it('disables unverified semantic modes when capabilities cannot load', async () => {
    api.fetchCapabilities.mockRejectedValueOnce(new Error('capabilities offline'));
    render(<JobBrowser />);

    const mode = await screen.findByLabelText('Retrieval mode');
    await waitFor(() => {
      expect(within(mode).getByRole('option', { name: 'Semantic' })).toBeDisabled();
      expect(within(mode).getByRole('option', { name: 'Hybrid' })).toBeDisabled();
    });
    expect(mode).toHaveValue('lexical');
  });

  it('labels bounded semantic and hybrid totals as ranked results', async () => {
    globalThis.fetch = vi.fn((input, options) => {
      const url = new URL(String(input), 'http://localhost');
      if (url.pathname === '/api/jobs/search/facets') {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(searchFacets()) });
      }
      const request = JSON.parse(options.body);
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(jobSearchPayload({
          applied_scope: request.scope,
          result_kind: 'ranked',
          result_limit: 1000,
          facets: null,
        })),
      });
    });

    render(<JobBrowser />);

    expect(await screen.findByText('Ranked results')).toBeInTheDocument();
    expect(screen.queryByText('Matched jobs')).not.toBeInTheDocument();
  });

  it('keeps an in-flight facet refresh active while changing pages', async () => {
    const user = userEvent.setup();
    const deferredFacets = createDeferredSearchResponse();
    globalThis.fetch = vi.fn((input, options) => {
      const url = new URL(String(input), 'http://localhost');
      if (url.pathname === '/api/jobs/search/facets') {
        return deferredFacets.promise;
      }
      const request = JSON.parse(options.body);
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(jobSearchPayload({
          applied_scope: request.scope,
          total: 30,
          total_pages: 2,
          facets: null,
        })),
      });
    });

    render(<JobBrowser />);

    await waitFor(() => expect(facetSearchCalls()).toHaveLength(1));
    expect(screen.getByRole('status', { name: 'Refreshing filter counts' }))
      .toBeInTheDocument();
    await user.click(await screen.findByRole('button', { name: 'Next' }));

    await waitFor(() => expect(jobSearchCalls()).toHaveLength(2));
    expect(facetSearchCalls()).toHaveLength(1);
    expect(screen.getByRole('status', { name: 'Refreshing filter counts' }))
      .toBeInTheDocument();
    expect(screen.getByRole('button', {
      name: 'Employment Type, 0 selected',
    })).toBeDisabled();

    deferredFacets.resolve(searchFacets());

    await waitFor(() => expect(screen.getByRole('button', {
      name: 'Employment Type, 0 selected',
    })).toBeEnabled());
  });

  it('shows fresh Jobs before contextual facets finish refreshing', async () => {
    const deferredFacets = createDeferredSearchResponse();
    globalThis.fetch = vi.fn((input, options) => {
      const url = new URL(String(input), 'http://localhost');
      if (url.pathname === '/api/jobs/search/facets') {
        return deferredFacets.promise;
      }
      const request = JSON.parse(options.body);
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
          ...searchPayloadWithTitle('Fresh Platform Result'),
          applied_scope: request.scope,
          facets: null,
        }),
      });
    });

    render(<JobBrowser />);

    expect(await screen.findByRole('article', {
      name: 'Fresh Platform Result at Fixture Company',
    })).toBeInTheDocument();
    const resultRequest = JSON.parse(jobSearchCalls()[0][1].body);
    expect(resultRequest.include_facets).toBe(false);
    expect(facetSearchCalls()).toHaveLength(1);
    expect(screen.getByRole('status', { name: 'Refreshing filter counts' }))
      .toBeInTheDocument();
    expect(screen.getByRole('button', {
      name: 'Employment Type, 0 selected',
    })).toBeDisabled();

    deferredFacets.resolve(searchFacets());

    await waitFor(() => expect(screen.getByRole('button', {
      name: 'Employment Type, 0 selected',
    })).toBeEnabled());
    expect(screen.queryByRole('status', { name: 'Refreshing filter counts' }))
      .not.toBeInTheDocument();
  });

  it('keeps successful Jobs visible when facets fail and retries only the counts', async () => {
    const user = userEvent.setup();
    let facetAttempt = 0;
    globalThis.fetch = vi.fn((input, options) => {
      const url = new URL(String(input), 'http://localhost');
      if (url.pathname === '/api/jobs/search/facets') {
        facetAttempt += 1;
        if (facetAttempt === 1) {
          return Promise.resolve({
            ok: false,
            json: () => Promise.resolve({ detail: 'Facet service offline' }),
          });
        }
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(searchFacets()),
        });
      }
      const request = JSON.parse(options.body);
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
          ...searchPayloadWithTitle('Durable Platform Result'),
          applied_scope: request.scope,
          facets: null,
        }),
      });
    });

    render(<JobBrowser />);

    expect(await screen.findByRole('article', {
      name: 'Durable Platform Result at Fixture Company',
    })).toBeInTheDocument();
    expect(await screen.findByRole('alert')).toHaveTextContent('Facet service offline');
    expect(screen.getByRole('button', {
      name: 'Employment Type, 0 selected',
    })).toBeDisabled();

    await user.selectOptions(screen.getByLabelText('Retrieval mode'), 'semantic');
    const jobsCallsBeforeRetry = jobSearchCalls().length;

    await user.click(screen.getByRole('button', { name: 'Retry filter counts' }));

    await waitFor(() => expect(facetSearchCalls()).toHaveLength(2));
    expect(jobSearchCalls()).toHaveLength(jobsCallsBeforeRetry);
    expect(JSON.parse(facetSearchCalls()[1][1].body)).toEqual(expect.objectContaining({
      retrieval_mode: 'lexical',
    }));
    expect(screen.getByRole('article', {
      name: 'Durable Platform Result at Fixture Company',
    })).toBeInTheDocument();
    expect(screen.getByRole('button', {
      name: 'Employment Type, 0 selected',
    })).toBeEnabled();
    expect(screen.queryByText('Facet service offline')).not.toBeInTheDocument();
  });

  it('ignores an older facet response after a newer scope has fresh counts', async () => {
    const user = userEvent.setup();
    const olderFacets = createDeferredSearchResponse();
    let facetAttempt = 0;
    let resultAttempt = 0;
    globalThis.fetch = vi.fn((input, options) => {
      const url = new URL(String(input), 'http://localhost');
      if (url.pathname === '/api/jobs/search/facets') {
        facetAttempt += 1;
        if (facetAttempt === 1) return olderFacets.promise;
        const freshFacets = searchFacets();
        freshFacets.employment_types[0].count = 9;
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(freshFacets),
        });
      }
      resultAttempt += 1;
      const request = JSON.parse(options.body);
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
          ...searchPayloadWithTitle(`Result Scope ${resultAttempt}`),
          applied_scope: request.scope,
          facets: null,
        }),
      });
    });

    render(<JobBrowser />);
    await screen.findByRole('article', {
      name: 'Result Scope 1 at Fixture Company',
    });

    const searchInput = screen.getByPlaceholderText(
      'Search Job Description...',
    );
    await user.type(searchInput, 'new scope');
    await user.click(screen.getByRole('button', { name: 'Search all jobs' }));

    await screen.findByRole('article', {
      name: 'Result Scope 2 at Fixture Company',
    });
    const employmentTypes = screen.getByRole('button', {
      name: 'Employment Type, 0 selected',
    });
    await waitFor(() => expect(employmentTypes).toBeEnabled());
    await user.click(employmentTypes);
    expect(screen.getByRole('checkbox', { name: 'Full-time (9 jobs)' }))
      .toBeInTheDocument();

    const staleFacets = searchFacets();
    staleFacets.employment_types[0].count = 99;
    olderFacets.resolve(staleFacets);

    await waitFor(() => {
      expect(screen.queryByRole('checkbox', { name: 'Full-time (99 jobs)' }))
        .not.toBeInTheDocument();
    });
    expect(screen.getByRole('checkbox', { name: 'Full-time (9 jobs)' }))
      .toBeInTheDocument();
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

    await waitFor(() => expect(jobSearchCalls()).toHaveLength(2));
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
      'Could not update results: Search service offline',
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
