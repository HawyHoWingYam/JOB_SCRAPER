import { useState } from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import productFixture from '../fixtures/job_intelligence_product_surfaces.json';
import JobDetailModal from './JobDetailModal';

function mockJsonResponse(payload) {
  return Promise.resolve({
    ok: true,
    json: async () => payload,
  });
}

function createJobPayload(overrides = {}) {
  return {
    // Keep every mocked detail response anchored to the backend-validated contract.
    ...productFixture.job_detail,
    job_id: 'platform-engineer-123',
    title: 'Senior Platform Engineer',
    company_name: 'Acme Health',
    company_ai_description: 'AI generated company blurb.',
    location: 'Hong Kong',
    salary_range: 'HK$40k - HK$60k',
    employment_type: 'Full-time',
    skills: ['Python', 'FastAPI'],
    ai_summary: 'Builds internal platform services and backend APIs.',
    ai_enriched_at: '2026-04-15T12:34:56Z',
    source_classification_name: 'Information & Communication Technology',
    source_subclassification_name: 'Platform Engineering',
    source_classification_paths: [
      {
        id: '10000000-0000-0000-0000-000000000001',
        source_site: 'jobsdb',
        source_order: 0,
        nodes: [
          {
            source_position: 0,
            native_depth: 0,
            source_classification_id: 'jobsdb:6281',
            native_id: '6281',
            label: 'Information & Communication Technology',
          },
        ],
        is_primary: false,
        primary_basis: null,
        provenance: { method: 'jobsdb-listing-payload' },
      },
    ],
    employment_types: [
      { code: 'full_time', label: 'Full-time', sort_order: 1 },
    ],
    source_employment_labels: [
      {
        id: '20000000-0000-0000-0000-000000000001',
        source_site: 'jobsdb',
        source_order: 0,
        raw_code: null,
        raw_label: 'Full-time',
        normalized_lookup_key: 'full-time',
        mapped_type_code: 'full_time',
        mapping_id: 'jobsdb-label-v1:full-time',
        provenance: { method: 'jobsdb-listing-payload' },
      },
    ],
    experience_level: 'mid_level',
    experience_min_years: 3,
    experience_max_years: 5,
    experience_summary: 'Typically seeks 3-5 years of backend platform experience.',
    experience_evidence: ['3-5 years of relevant experience preferred.'],
    description: '<p>Build APIs</p>',
    posted_date: '2026-04-14T00:00:00Z',
    expiry_date: '2026-05-01T00:00:00Z',
    is_expired: false,
    ...overrides,
  };
}

function createSkillState(overrides = {}) {
  return {
    ...productFixture.job_detail.skill_state,
    skills: [],
    ...overrides,
  };
}

function renderModalWithPayload(payload) {
  globalThis.fetch = vi.fn(() => mockJsonResponse(payload));

  render(
    <JobDetailModal
      jobId="job-1"
      apiUrl="http://localhost:8000"
      onClose={vi.fn()}
    />,
  );
}

function renderModalWithDetailAndRecommendations(payload, recommendations) {
  globalThis.fetch = vi.fn((input) => {
    const url = new URL(String(input), 'http://localhost');

    if (url.pathname === '/api/jobs/job-1') {
      return mockJsonResponse(payload);
    }

    if (url.pathname === '/api/jobs/job-1/similar') {
      return mockJsonResponse({
        source_job_id: payload.id,
        recommendations,
      });
    }

    return Promise.reject(new Error(`Unhandled fetch: ${url.pathname}`));
  });

  render(
    <JobDetailModal
      jobId="job-1"
      apiUrl="http://localhost:8000"
      onClose={vi.fn()}
    />,
  );
}

describe('JobDetailModal', () => {
  beforeEach(() => {
    vi.spyOn(Date, 'now').mockReturnValue(new Date('2026-04-16T00:00:00Z').getTime());
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('opens as a named modal dialog and moves focus inside it', async () => {
    renderModalWithPayload(createJobPayload());

    const dialog = await screen.findByRole('dialog', {
      name: /senior platform engineer/i,
    });
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(screen.getByRole('button', { name: 'Close job details' })).toHaveFocus();
  });

  it('traps keyboard focus, closes with Escape, and restores the opener focus', async () => {
    const user = userEvent.setup();
    globalThis.fetch = vi.fn(() => mockJsonResponse(createJobPayload({
      original_job_url: 'https://example.com/jobs/platform-engineer-123',
    })));

    function JobDetailHarness() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>Open job details</button>
          {open && (
            <JobDetailModal
              jobId="job-1"
              apiUrl="http://localhost:8000"
              onClose={() => setOpen(false)}
            />
          )}
        </>
      );
    }

    render(<JobDetailHarness />);
    const opener = screen.getByRole('button', { name: 'Open job details' });
    await user.click(opener);

    const closeButton = screen.getByRole('button', { name: 'Close job details' });
    const lastAction = await screen.findByRole('link', { name: /original job post/i });
    lastAction.focus();
    await user.tab();
    expect(closeButton).toHaveFocus();

    await user.tab({ shift: true });
    expect(lastAction).toHaveFocus();

    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });

  it('announces the job detail loading state', () => {
    globalThis.fetch = vi.fn(() => new Promise(() => {}));

    render(
      <JobDetailModal
        jobId="job-1"
        apiUrl="http://localhost:8000"
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByRole('status')).toHaveTextContent('Loading job details…');
  });

  it('announces a job detail request failure', async () => {
    globalThis.fetch = vi.fn(() => Promise.resolve({ ok: false }));

    render(
      <JobDetailModal
        jobId="missing-job"
        apiUrl="http://localhost:8000"
        onClose={vi.fn()}
      />,
    );

    expect(await screen.findByRole('alert')).toHaveTextContent('Job not found');
  });

  it('edits operator-authored fields only for a Manual Job', async () => {
    const payload = createJobPayload({
      origin: 'manual_entry',
      manual_editable: true,
      enrichment_eligibility: 'needs_job_description',
      job_intelligence_freshness: 'not_enriched',
      description: null,
    });
    const patches = [];
    globalThis.fetch = vi.fn((input, init = {}) => {
      const url = new URL(String(input), 'http://localhost');
      if (url.pathname === '/api/jobs/job-1') return mockJsonResponse(payload);
      if (url.pathname === '/api/jobs/job-1/similar') {
        return mockJsonResponse({ recommendations: [] });
      }
      if (url.pathname === '/api/jobs/filters') {
        return mockJsonResponse(productFixture.job_filters);
      }
      if (url.pathname === `/api/jobs/manual/${payload.id}` && init.method === 'PATCH') {
        patches.push({ body: JSON.parse(init.body), headers: init.headers });
        return mockJsonResponse({
          ...payload,
          description: 'Operator supplied description',
          enrichment_eligibility: 'pending',
        });
      }
      return Promise.reject(new Error(`Unhandled fetch: ${url.pathname}`));
    });
    const user = userEvent.setup();
    render(
      <JobDetailModal jobId="job-1" apiUrl="http://localhost:8000" onClose={vi.fn()} />,
    );

    expect(await screen.findByText('Origin: Manual Entry')).toBeInTheDocument();
    expect(screen.getByText(/Needs job description before AI enrichment/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Edit Manual Job' }));
    await user.type(screen.getByLabelText('Description'), 'Operator supplied description');
    await user.click(screen.getByRole('button', { name: 'Save Job' }));

    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0].body.company).toEqual({
      mode: 'existing',
      company_id: payload.company_id,
    });
    expect(patches[0].headers['Idempotency-Key']).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Save Job' })).not.toBeInTheDocument();
  });

  it('renders company name, salary range, relational skills, and ai summary from the detail API', async () => {
    renderModalWithPayload(createJobPayload());

    expect(await screen.findByRole('heading', { name: /senior platform engineer/i })).toBeInTheDocument();
    expect(screen.getByText('Acme Health')).toBeInTheDocument();
    expect(screen.getByText('HK$40k - HK$60k')).toBeInTheDocument();
    expect(screen.getByText('Python')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /ai summary/i })).toBeInTheDocument();
    expect(screen.getByText(/builds internal platform services/i)).toBeInTheDocument();
  });

  it('renders backend-owned governed Job Intelligence states without legacy fallback', async () => {
    renderModalWithPayload(productFixture.job_detail);

    const roleEvidence = await screen.findByRole('region', { name: 'Role Evidence' });
    expect(roleEvidence).toHaveTextContent('Full-time');
    expect(roleEvidence).toHaveTextContent('Permanent');
    expect(roleEvidence).toHaveTextContent(
      'Information Technology / Developers and Programmers',
    );
    expect(roleEvidence).toHaveTextContent('Not declared Primary');

    expect(screen.queryByText('Legacy evidence only')).not.toBeInTheDocument();
    expect(screen.queryByText('Legacy / AI / Category')).not.toBeInTheDocument();
    expect(screen.queryByText('Rust')).not.toBeInTheDocument();
  });

  it('shows explicit unenriched ai states when enrichment has not run yet', async () => {
    renderModalWithPayload(
      createJobPayload({
        ai_enriched_at: null,
        skills: [],
        skill_state: createSkillState(),
        ai_summary: null,
        experience_level: null,
        experience_summary: null,
      }),
    );

    expect(await screen.findByRole('heading', { name: /senior platform engineer/i })).toBeInTheDocument();
    expect(screen.getByText('AI enrichment not run yet')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /^skills$/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /^experience$/i })).toBeInTheDocument();
  });

  it('shows explicit empty-state copy when ai enrichment ran but extracted no values', async () => {
    renderModalWithPayload(
      createJobPayload({
        skills: [],
        skill_state: createSkillState(),
        ai_summary: null,
        experience_level: 'not_specified',
        experience_summary: null,
      }),
    );

    expect(await screen.findByRole('heading', { name: /senior platform engineer/i })).toBeInTheDocument();
    expect(screen.getByText('No technical skills extracted from this posting')).toBeInTheDocument();
    expect(screen.getByText('No AI summary extracted from this posting')).toBeInTheDocument();
    expect(screen.getByText('Not specified')).toBeInTheDocument();
    expect(screen.getByText('The posting does not specify experience')).toBeInTheDocument();
  });

  it('prefers a normalized numeric experience label over free-text summary text', async () => {
    renderModalWithPayload(createJobPayload());

    expect(await screen.findByRole('heading', { name: /senior platform engineer/i })).toBeInTheDocument();
    expect(screen.getByText('3+')).toBeInTheDocument();
    expect(screen.getByText('3–5 years')).toBeInTheDocument();
    expect(
      screen.queryByText('Typically seeks 3-5 years of backend platform experience.'),
    ).not.toBeInTheDocument();
  });

  it('renders governed role evidence without promoting legacy scalar context', async () => {
    renderModalWithPayload(
      createJobPayload({
        job_id: '7f3a-platform-engineer',
        original_job_url: 'https://hk.jobsdb.com/job/7f3a-platform-engineer',
      }),
    );

    expect(await screen.findByRole('heading', { name: /senior platform engineer/i })).toBeInTheDocument();
    expect(screen.getByText('Source Classification Paths')).toBeInTheDocument();
    expect(screen.getByText('Information & Communication Technology')).toBeInTheDocument();
    expect(screen.queryByText('Platform Engineering')).not.toBeInTheDocument();
    expect(screen.getByText('Company AI description')).toBeInTheDocument();
    expect(screen.getByText('AI generated company blurb.')).toBeInTheDocument();
    expect(screen.getByText('Posted 2 days ago')).toBeInTheDocument();
    expect(screen.getByText('Application closes 1 May 2026')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /original job post/i })).toHaveAttribute(
      'href',
      'https://hk.jobsdb.com/job/7f3a-platform-engineer',
    );
  });

  it('uses the API-provided ctgoodjobs original job url', async () => {
    renderModalWithPayload(
      createJobPayload({
        job_id: 'ctgoodjobs:10090657',
        source_site: 'ctgoodjobs',
        original_job_url: 'https://jobs.ctgoodjobs.hk/job/10090657',
      }),
    );

    expect(await screen.findByRole('heading', { name: /senior platform engineer/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /original job post/i })).toHaveAttribute(
      'href',
      'https://jobs.ctgoodjobs.hk/job/10090657',
    );
  });

  it('renders related job recommendations when the similar-jobs endpoint returns matches', async () => {
    renderModalWithDetailAndRecommendations(
      createJobPayload(),
      [
        {
          ...productFixture.job_recommendations.recommendations[0],
          employment_type: 'Legacy Contract',
        },
      ],
    );

    expect(await screen.findByRole('heading', { name: /senior platform engineer/i })).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: /related jobs/i })).toBeInTheDocument();
    expect(screen.getByText('Related Platform Engineer')).toBeInTheDocument();
    expect(screen.getByText('Related Fixture Company')).toBeInTheDocument();
    const relatedJobCard = screen.getByRole('article');
    expect(relatedJobCard).toHaveTextContent('Full-time');
    expect(relatedJobCard).toHaveTextContent('Permanent');
    expect(relatedJobCard).not.toHaveTextContent('Legacy Contract');
    expect(relatedJobCard).not.toHaveTextContent('Legacy / AI / Category');
  });

  it('does not invent a 0 percent related-job score when the recommendation score is missing', async () => {
    renderModalWithDetailAndRecommendations(
      createJobPayload(),
      [
        {
          id: 'job-2',
          job_id: 'platform-engineer-456',
          title: 'Platform Backend Engineer',
          company_name: 'Atlas Systems',
          location: 'Hong Kong',
          employment_type: 'Full-time',
          posted_date: '2026-04-15T00:00:00Z',
        },
      ],
    );

    expect(await screen.findByRole('heading', { name: /related jobs/i })).toBeInTheDocument();
    expect(screen.getByText('Platform Backend Engineer')).toBeInTheDocument();
    expect(screen.getByText(/score unavailable/i)).toBeInTheDocument();
    expect(screen.queryByText('0%')).not.toBeInTheDocument();
  });

  it('skips related jobs requests when similar jobs are unavailable in the runtime profile', async () => {
    globalThis.fetch = vi.fn((input) => {
      const url = new URL(String(input), 'http://localhost');

      if (url.pathname === '/api/jobs/job-1') {
        return mockJsonResponse(createJobPayload());
      }

      if (url.pathname === '/api/jobs/job-1/similar') {
        return mockJsonResponse({ source_job_id: 'job-1', recommendations: [] });
      }

      return Promise.reject(new Error(`Unhandled fetch: ${url.pathname}`));
    });

    render(
      <JobDetailModal
        jobId="job-1"
        apiUrl="http://localhost:8000"
        capabilities={{ recommendations: { similar_jobs: { available: false } } }}
        onClose={vi.fn()}
      />,
    );

    expect(await screen.findByRole('heading', { name: /senior platform engineer/i })).toBeInTheDocument();
    expect(
      screen.getByText('Related jobs are unavailable in the current runtime profile.'),
    ).toBeInTheDocument();
    expect(
      globalThis.fetch.mock.calls.some(([input]) => String(input).includes('/api/jobs/job-1/similar')),
    ).toBe(false);
  });

  it('waits for runtime capabilities before deciding whether to request related jobs', async () => {
    globalThis.fetch = vi.fn((input) => {
      const url = new URL(String(input), 'http://localhost');

      if (url.pathname === '/api/jobs/job-1') {
        return mockJsonResponse(createJobPayload());
      }

      if (url.pathname === '/api/jobs/job-1/similar') {
        return mockJsonResponse({ source_job_id: 'job-1', recommendations: [] });
      }

      return Promise.reject(new Error(`Unhandled fetch: ${url.pathname}`));
    });

    const modalProps = {
      jobId: 'job-1',
      apiUrl: 'http://localhost:8000',
      onClose: vi.fn(),
    };
    const { rerender } = render(
      <JobDetailModal
        {...modalProps}
        capabilities={null}
        capabilitiesLoading
      />,
    );

    expect(await screen.findByRole('heading', { name: /senior platform engineer/i })).toBeInTheDocument();

    rerender(
      <JobDetailModal
        {...modalProps}
        capabilities={{ recommendations: { similar_jobs: { available: false } } }}
        capabilitiesLoading={false}
      />,
    );

    expect(
      await screen.findByText('Related jobs are unavailable in the current runtime profile.'),
    ).toBeInTheDocument();
    expect(
      globalThis.fetch.mock.calls.some(([input]) => String(input).includes('/api/jobs/job-1/similar')),
    ).toBe(false);
  });
});
