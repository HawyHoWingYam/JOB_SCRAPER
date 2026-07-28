import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import productFixture from '../../fixtures/job_intelligence_product_surfaces.json';
import AddJobPage from './AddJobPage';

function jsonResponse(payload, { ok = true, status = 200 } = {}) {
  return Promise.resolve({ ok, status, json: async () => payload });
}

function installBaseFetch(onManualSubmit) {
  globalThis.fetch = vi.fn((input, init = {}) => {
    const url = new URL(String(input), 'http://localhost');
    if (url.pathname === '/api/jobs/filters') {
      return jsonResponse(productFixture.job_filters);
    }
    if (url.pathname === '/api/companies') {
      return jsonResponse({
        items: [productFixture.companies[0]],
        total: 1,
        page: 1,
        page_size: 10,
        total_pages: 1,
      });
    }
    if (url.pathname === '/api/jobs/manual' && init.method === 'POST') {
      return onManualSubmit(init);
    }
    return Promise.reject(new Error(`Unhandled request: ${url.pathname}`));
  });
}

describe('AddJobPage manual persistence', () => {
  afterEach(() => vi.restoreAllMocks());

  it('submits an existing Company with governed fields and an idempotency key', async () => {
    const submissions = [];
    installBaseFetch((init) => {
      submissions.push(init);
      return jsonResponse({ ...productFixture.job_detail, title: 'Platform Engineer' });
    });
    const user = userEvent.setup();
    render(<AddJobPage />);

    expect(screen.getByText('Optional for saving · Required for AI enrichment')).toBeInTheDocument();
    expect(screen.getByText('Optional job details').closest('details')).not.toHaveAttribute('open');
    await user.type(screen.getByLabelText('Job Title *'), 'Platform Engineer');
    await user.type(screen.getByLabelText('Search Company'), 'Fixture');
    await user.click(await screen.findByRole('button', { name: /Fixture Company/ }));
    await user.click(screen.getByText('Optional job details'));
    const employmentTypes = await screen.findByLabelText('Employment Types');
    await user.selectOptions(employmentTypes, ['full_time', 'permanent']);
    await user.type(screen.getByLabelText('Salary Min'), '30000');
    await user.click(screen.getByRole('button', { name: 'Add Job' }));

    await waitFor(() => expect(submissions).toHaveLength(1));
    const payload = JSON.parse(submissions[0].body);
    expect(payload).toEqual(expect.objectContaining({
      company: { mode: 'existing', company_id: productFixture.companies[0].id },
      title: 'Platform Engineer',
      salary_min: 30000,
      employment_type_codes: ['full_time', 'permanent'],
    }));
    expect(payload).not.toHaveProperty('salary_range');
    expect(payload).not.toHaveProperty('employment_type');
    expect(submissions[0].headers['Idempotency-Key']).toBeTruthy();
    expect(await screen.findByRole('status')).toHaveTextContent('was added successfully');
    expect(screen.queryByText(/AI Summary|Canonical Job Taxonomy/)).not.toBeInTheDocument();
  });

  it('keeps a New Company draft local and submits it atomically with the Job', async () => {
    const submissions = [];
    installBaseFetch((init) => {
      submissions.push(JSON.parse(init.body));
      return jsonResponse({ ...productFixture.job_detail, title: 'Designer' });
    });
    const user = userEvent.setup();
    render(<AddJobPage />);

    await user.click(screen.getByLabelText('New Company'));
    await user.type(screen.getByLabelText('Company Name *'), 'New Evidence Company');
    await user.type(screen.getByLabelText('Website'), 'example.com');
    await user.type(screen.getByLabelText('Company Industry evidence'), 'Software Consulting');
    await user.type(screen.getByLabelText('Company Location'), 'Central');
    await user.type(screen.getByLabelText('Job Title *'), 'Designer');

    expect(globalThis.fetch).not.toHaveBeenCalledWith(
      expect.stringContaining('/companies'),
      expect.objectContaining({ method: 'POST' }),
    );
    await user.click(screen.getByRole('button', { name: 'Add Job' }));

    await waitFor(() => expect(submissions).toHaveLength(1));
    expect(submissions[0].company).toEqual({
      mode: 'new',
      name: 'New Evidence Company',
      website: 'example.com',
      industry: 'Software Consulting',
      location: 'Central',
    });
  });

  it('keeps one idempotency key through duplicate review and explicit confirmation', async () => {
    const keys = [];
    const bodies = [];
    installBaseFetch((init) => {
      keys.push(init.headers['Idempotency-Key']);
      bodies.push(JSON.parse(init.body));
      if (keys.length === 1) {
        return jsonResponse({
          detail: {
            code: 'duplicate_candidates',
            message: 'Possible duplicate',
            confirmation: 'a'.repeat(64),
            company_candidates: [],
            job_candidates: [{ id: 'job-1', title: 'Engineer' }],
          },
        }, { ok: false, status: 409 });
      }
      return jsonResponse({ ...productFixture.job_detail, title: 'Engineer' });
    });
    const user = userEvent.setup();
    render(<AddJobPage />);

    await user.type(screen.getByLabelText('Job Title *'), 'Engineer');
    await user.type(screen.getByLabelText('Search Company'), 'Fixture');
    await user.click(await screen.findByRole('button', { name: /Fixture Company/ }));
    await user.click(screen.getByRole('button', { name: 'Add Job' }));
    await user.click(await screen.findByRole('button', { name: 'Add anyway' }));

    await waitFor(() => expect(keys).toHaveLength(2));
    expect(keys[1]).toBe(keys[0]);
    expect(bodies[1].duplicate_confirmation).toBe('a'.repeat(64));
  });
});
