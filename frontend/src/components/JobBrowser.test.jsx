import { StrictMode } from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import canonicalFixture from '../fixtures/canonical_job_taxonomy_responses.json';
import companyFixture from '../fixtures/company_industry_responses.json';
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
    jobs: [{
      ...productFixture.job_search.jobs[0],
      id: title.toLowerCase().replaceAll(' ', '-'),
      title,
    }],
    total: 1,
    total_pages: 1,
  };
}

describe('JobBrowser governed filters', () => {
  beforeEach(() => {
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
      if (path.includes('/canonical-job-taxonomy/tree')) {
        return Promise.resolve(canonicalFixture.tree);
      }
      if (path.includes('/company-industries/tree')) {
        return Promise.resolve(companyFixture.tree);
      }
      return Promise.reject(new Error(`Unexpected API read: ${path}`));
    });
    globalThis.fetch = vi.fn(() => Promise.resolve({
      ok: true,
      json: () => Promise.resolve(productFixture.job_search),
    }));
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('combines backend-owned Source, canonical, and Company Industry options', async () => {
    render(<JobBrowser />);

    expect(
      await screen.findByRole('option', { name: 'Full-time' }),
    ).toHaveValue('full_time');
    expect(
      screen.getByRole('option', { name: 'Job Domain · Accounting' }),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole('checkbox', {
        name: 'J · Information and communications',
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('option', {
        name: 'JobsDB · Information Technology / Developers and Programmers',
      }),
    ).toHaveValue('jobsdb:6287');
    expect(screen.queryByText('Legacy Software evidence')).not.toBeInTheDocument();

    await waitFor(() => {
      expect(api.apiFetchJson).toHaveBeenCalledWith(
        expect.stringContaining('/canonical-job-taxonomy/tree'),
        expect.any(Object),
      );
      expect(api.apiFetchJson).toHaveBeenCalledWith(
        expect.stringContaining('/company-industries/tree'),
        expect.any(Object),
      );
    });
  });

  it('renders governed Employment Types and Canonical Job Taxonomy without legacy fallback', async () => {
    render(<JobBrowser />);

    const assignedCard = await screen.findByRole('article', {
      name: 'Platform Engineer at Fixture Company',
    });
    expect(within(assignedCard).getByText('Full-time')).toBeInTheDocument();
    expect(within(assignedCard).getByText('Permanent')).toBeInTheDocument();
    expect(
      within(assignedCard).getByText(
        'Canonical Job Taxonomy: Technology / Software Development / Backend Development',
      ),
    ).toBeInTheDocument();
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
    expect(
      within(unassignedCard).getByText('Canonical Job Taxonomy: Unassigned'),
    ).toBeInTheDocument();

    const unavailableCard = screen.getByRole('article', {
      name: 'Operations Coordinator at Legacy Company',
    });
    expect(
      within(unavailableCard).getByText('Canonical Job Taxonomy: Unavailable'),
    ).toBeInTheDocument();
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
    const domain = canonicalFixture.tree.domains[0];
    const category = domain.categories[0];
    const subcategory = category.subcategories[0];
    const industryNode = companyFixture.tree.nodes[0];

    render(<JobBrowser />);

    await user.selectOptions(
      await screen.findByLabelText('Employment Type'),
      ['full_time', 'permanent'],
    );
    await user.selectOptions(
      screen.getByLabelText('Source Classification Paths'),
      ['jobsdb:6281', 'jobsdb:6287'],
    );
    await user.selectOptions(
      screen.getByLabelText('Canonical Job Taxonomy'),
      [domain.id, category.id, subcategory.id],
    );
    await user.click(screen.getByRole('checkbox', {
      name: 'J · Information and communications',
    }));
    await user.click(screen.getByRole('button', { name: 'Search all jobs' }));

    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(2));
    const submitted = JSON.parse(globalThis.fetch.mock.calls[1][1].body);
    expect(submitted.scope.layers).toHaveLength(1);
    expect(submitted.scope.layers[0].structured_filters).toEqual(
      expect.objectContaining({
        employment_type_codes: ['full_time', 'permanent'],
        source_classification_ids: ['jobsdb:6281', 'jobsdb:6287'],
        canonical_domain_ids: [domain.id],
        canonical_category_ids: [category.id],
        canonical_subcategory_ids: [subcategory.id],
        company_industry_node_ids: [industryNode.id],
        employment_type: '',
        industry: '',
        subcategory_ids: [],
      }),
    );
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
