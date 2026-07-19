import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import productFixture from '../../fixtures/job_intelligence_product_surfaces.json';
import AddJobPage from './AddJobPage';

function jsonResponse(payload) {
  return Promise.resolve({
    ok: true,
    json: async () => payload,
  });
}

describe('AddJobPage governed manual entry', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('loads governed Employment Types and submits stable multi-value codes', async () => {
    const submittedJobs = [];
    globalThis.fetch = vi.fn((input, init = {}) => {
      const url = new URL(String(input), 'http://localhost');

      if (url.pathname === '/api/v1/jobs/filters') {
        return jsonResponse(productFixture.job_filters);
      }
      if (url.pathname === '/api/v1/companies') {
        return jsonResponse({
          items: [productFixture.companies[0]],
          total: 1,
          page: 1,
          page_size: 10,
          total_pages: 1,
        });
      }
      if (url.pathname === '/api/v1/jobs/manual' && init.method === 'POST') {
        submittedJobs.push(JSON.parse(init.body));
        return jsonResponse(productFixture.job_detail);
      }
      return Promise.reject(new Error(`Unhandled request: ${url.pathname}`));
    });

    const user = userEvent.setup();
    render(<AddJobPage />);

    const employmentTypes = await screen.findByLabelText('Employment Types');
    expect(employmentTypes).toHaveAttribute('multiple');
    expect(screen.getByRole('option', { name: 'Permanent' })).toHaveValue('permanent');
    await user.selectOptions(employmentTypes, ['full_time', 'permanent']);

    await user.type(screen.getByLabelText('Job Title *'), 'Platform Engineer');
    await user.type(screen.getByLabelText('Company *'), 'Fixture');
    await user.click(await screen.findByRole('option', { name: /Fixture Company/ }));
    expect(screen.queryByText('Legacy evidence only')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Create Job & Enrich' }));

    await waitFor(() => expect(submittedJobs).toHaveLength(1));
    expect(submittedJobs[0]).toEqual(expect.objectContaining({
      company_id: productFixture.companies[0].id,
      title: 'Platform Engineer',
      employment_type_codes: ['full_time', 'permanent'],
    }));
    expect(submittedJobs[0]).not.toHaveProperty('employment_type');
    expect(await screen.findByRole('status')).toHaveTextContent(
      'created successfully with AI enrichment',
    );
    expect(await screen.findByText('Canonical Job Taxonomy')).toBeInTheDocument();
    expect(screen.getByText(
      'Technology / Software Development / Backend Development',
    )).toBeInTheDocument();
    expect(screen.queryByText('Classification')).not.toBeInTheDocument();
  });

  it('labels new Company Industry text as review evidence instead of an assignment', async () => {
    const createdCompanies = [];
    globalThis.fetch = vi.fn((input, init = {}) => {
      const url = new URL(String(input), 'http://localhost');

      if (url.pathname === '/api/v1/jobs/filters') {
        return jsonResponse(productFixture.job_filters);
      }
      if (url.pathname === '/api/v1/companies' && init.method === 'POST') {
        createdCompanies.push(JSON.parse(init.body));
        return jsonResponse({
          ...productFixture.companies[1],
          name: 'New Evidence Company',
        });
      }
      if (url.pathname === '/api/v1/companies') {
        return jsonResponse({
          items: [],
          total: 0,
          page: 1,
          page_size: 10,
          total_pages: 0,
        });
      }
      return Promise.reject(new Error(`Unhandled request: ${url.pathname}`));
    });

    const user = userEvent.setup();
    render(<AddJobPage />);

    await user.type(screen.getByLabelText('Company *'), 'New Evidence Company');
    await user.click(await screen.findByRole('button', { name: /can't find/i }));

    expect(screen.getByText(/free text is recorded as evidence/i)).toBeInTheDocument();
    await user.type(screen.getByLabelText('Company Industry evidence'), 'Software Consulting');
    await user.type(
      screen.getByLabelText('Location', { selector: '#new-company-location' }),
      'Central',
    );
    await user.click(screen.getByRole('button', { name: 'Create Company' }));

    await waitFor(() => expect(createdCompanies).toHaveLength(1));
    expect(createdCompanies[0]).toEqual({
      name: 'New Evidence Company',
      industry: 'Software Consulting',
      location: 'Central',
    });
    expect(screen.getByText('Company Industry: Unassigned')).toBeInTheDocument();
    expect(screen.queryByText('Software Consulting')).not.toBeInTheDocument();
  });
});
