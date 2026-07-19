import { useState } from 'react';
import { render, screen, within } from '@testing-library/react';
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
    company_industry: 'Healthcare Technology',
    company_ai_description: 'AI generated company blurb.',
    location: 'Hong Kong',
    salary_range: 'HK$40k - HK$60k',
    employment_type: 'Full-time',
    skills: ['Python', 'FastAPI'],
    provisional_skills: [],
    unreviewed_skill_mentions: [],
    ai_summary: 'Builds internal platform services and backend APIs.',
    job_taxonomy: {
      path: 'Information & Communication Technology / Software Development / Backend Development',
    },
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
        catalog_revision: null,
        provenance_limited: true,
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
    unreviewed_skill_mentions: [],
    ...overrides,
  };
}

function createUnassignedCanonicalState(overrides = {}) {
  return {
    job_id: productFixture.job_detail.id,
    state: 'unassigned',
    assignment: null,
    reasons: [],
    review_item_refs: [],
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

    if (url.pathname === '/api/v1/jobs/job-1') {
      return mockJsonResponse(payload);
    }

    if (url.pathname === '/api/v1/jobs/job-1/similar') {
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
    globalThis.fetch = vi.fn(() => mockJsonResponse(createJobPayload()));

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
    const lastLink = await screen.findByRole('link', { name: 'Open Skill Candidates' });
    lastLink.focus();
    await user.tab();
    expect(closeButton).toHaveFocus();

    await user.tab({ shift: true });
    expect(lastLink).toHaveFocus();

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

    const canonical = screen.getByRole('region', {
      name: 'Canonical Job Taxonomy',
    });
    expect(canonical).toHaveTextContent(
      'Technology / Software Development / Backend Development',
    );
    expect(canonical).toHaveTextContent('Assignment method: Constrained AI');
    expect(within(canonical).getByRole('link', { name: 'Open Job Taxonomy Review' }))
      .toHaveAttribute('href', '#job-intelligence/job-taxonomy');

    const industries = screen.getByRole('region', { name: 'Company Industries' });
    expect(industries).toHaveTextContent('J · Information and communications');
    expect(industries).toHaveTextContent('Primary Company Industry');
    expect(within(industries).getByRole('link', { name: 'Open Company Industries' }))
      .toHaveAttribute('href', '#job-intelligence/company-industries');

    expect(screen.queryByText('Legacy evidence only')).not.toBeInTheDocument();
    expect(screen.queryByText('Legacy / AI / Category')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Review Rust' })).toHaveAttribute(
      'href',
      '#job-intelligence/skill-candidates?item=80000000-0000-0000-0000-000000000010',
    );
  });

  it('summarizes an explicit Primary Company Industry as Primary + N', async () => {
    renderModalWithPayload({
      ...productFixture.job_detail,
      company_industries: productFixture.companies[0].company_industries,
    });

    const industries = await screen.findByRole('region', { name: 'Company Industries' });
    expect(industries).toHaveTextContent('Primary Company Industry +1');
    expect(industries).toHaveTextContent('J · Information and communications');
    expect(industries).toHaveTextContent('K · Financial and insurance activities');
  });

  it('does not infer a Primary Company Industry from assignment order', async () => {
    renderModalWithPayload({
      ...productFixture.job_detail,
      company_industries: {
        ...productFixture.companies[0].company_industries,
        assignments: productFixture.companies[0].company_industries.assignments.map(
          (assignment) => ({ ...assignment, is_primary: false, primary_basis: null }),
        ),
      },
    });

    const industries = await screen.findByRole('region', { name: 'Company Industries' });
    expect(industries).not.toHaveTextContent('Primary Company Industry');
    expect(within(industries).getAllByText('Additional Company Industry')).toHaveLength(2);
  });

  it('renders Unassigned and review states as read-only governance links', async () => {
    renderModalWithPayload({
      ...productFixture.job_detail,
      canonical_taxonomy: {
        job_id: productFixture.job_detail.id,
        state: 'unassigned',
        assignment: null,
        reasons: ['classifier_provenance_missing'],
        review_item_refs: [
          {
            id: '91000000-0000-0000-0000-000000000099',
            status: 'active',
            version: 3,
            decision_audit_id: null,
            deep_link: '/api/v1/job-intelligence/governance/job-taxonomy/review-items/91000000-0000-0000-0000-000000000099',
          },
        ],
      },
      company_industries: {
        company_id: productFixture.job_detail.company_id,
        assignments: [],
        review_item_refs: [
          {
            id: '93000000-0000-0000-0000-000000000099',
            status: 'active',
            reason: 'unmapped_source_label',
            version: 2,
            decision_audit_id: null,
            deep_link: '/api/v1/job-intelligence/governance/company-industries/review-items/93000000-0000-0000-0000-000000000099',
          },
        ],
      },
    });

    const canonical = await screen.findByRole('region', {
      name: 'Canonical Job Taxonomy',
    });
    expect(canonical).toHaveTextContent('Unassigned Canonical Taxonomy');
    expect(canonical).toHaveTextContent('Classifier Provenance Missing');
    expect(within(canonical).getByRole('link', { name: 'Open review item' }))
      .toHaveAttribute(
        'href',
        '#job-intelligence/job-taxonomy?item=91000000-0000-0000-0000-000000000099',
      );

    const industries = screen.getByRole('region', { name: 'Company Industries' });
    expect(industries).toHaveTextContent('No governed Company Industry assignment');
    expect(within(industries).getByRole('link', { name: 'Open Industry review item' }))
      .toHaveAttribute(
        'href',
        '#job-intelligence/company-industries?item=93000000-0000-0000-0000-000000000099',
      );
    expect(screen.queryByRole('button', { name: /assign|reject|approve/i }))
      .not.toBeInTheDocument();
  });

  it('shows governed domains as unavailable without consulting legacy values', async () => {
    renderModalWithPayload({
      ...productFixture.job_detail,
      canonical_taxonomy: null,
      company_industries: null,
      job_intelligence_availability: {
        ...productFixture.job_detail.job_intelligence_availability,
        canonical_taxonomy: {
          available: false,
          unavailable_code: 'CANONICAL_TAXONOMY_NOT_ACTIVE',
        },
        company_industries: {
          available: false,
          unavailable_code: 'COMPANY_INDUSTRY_TAXONOMY_NOT_ACTIVE',
        },
      },
    });

    const canonical = await screen.findByRole('region', {
      name: 'Canonical Job Taxonomy',
    });
    expect(canonical).toHaveTextContent(
      'Unavailable (CANONICAL_TAXONOMY_NOT_ACTIVE)',
    );
    const industries = screen.getByRole('region', { name: 'Company Industries' });
    expect(industries).toHaveTextContent(
      'Unavailable (COMPANY_INDUSTRY_TAXONOMY_NOT_ACTIVE)',
    );
    expect(screen.queryByText('Legacy evidence only')).not.toBeInTheDocument();
  });

  it('shows explicit unenriched ai states when enrichment has not run yet', async () => {
    renderModalWithPayload(
      createJobPayload({
        ai_enriched_at: null,
        skills: [],
        unreviewed_skill_mentions: [],
        skill_state: createSkillState(),
        ai_summary: null,
        job_taxonomy: null,
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
        provisional_skills: [],
        skill_state: createSkillState(),
        ai_summary: null,
        job_taxonomy: null,
        canonical_taxonomy: createUnassignedCanonicalState(),
        experience_level: 'not_specified',
        experience_summary: null,
      }),
    );

    expect(await screen.findByRole('heading', { name: /senior platform engineer/i })).toBeInTheDocument();
    expect(screen.getByText('No technical skills extracted from this posting')).toBeInTheDocument();
    expect(screen.getByText('No AI summary extracted from this posting')).toBeInTheDocument();
    expect(screen.getByText('Unassigned Canonical Taxonomy')).toBeInTheDocument();
    expect(screen.getByText('No explicit experience requirement found in the posting')).toBeInTheDocument();
  });

  it('renders unreviewed skill mentions as secondary evidence and ignores legacy generic/rejected labels', async () => {
    renderModalWithPayload(
      createJobPayload({
        skills: [],
        provisional_skills: ['Generic Tag', 'Rejected Evidence'],
        unreviewed_skill_mentions: [],
        skill_state: createSkillState({
          unreviewed_skill_mentions: [
            {
              id: '60000000-0000-0000-0000-000000000001',
              label: 'Unreviewed Skill Mention',
              raw_name: 'Rust',
              normalized_key: 'rust',
              candidate_id: '70000000-0000-0000-0000-000000000001',
              candidate_version: 1,
              source: 'ai-extraction',
              confidence: 0.82,
              provenance: { run_id: 'fixture-run' },
              deep_link: '/api/v1/job-intelligence/governance/skills/candidates/70000000-0000-0000-0000-000000000001',
              created_at: '2026-07-19T08:00:00Z',
              updated_at: '2026-07-19T08:00:00Z',
            },
          ],
        }),
      }),
    );

    expect(await screen.findByRole('heading', { name: /senior platform engineer/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /unreviewed skill mentions/i })).toBeInTheDocument();
    expect(screen.getByText('Rust')).toBeInTheDocument();
    expect(screen.getByText(/secondary evidence awaiting human taxonomy review/i)).toBeInTheDocument();
    expect(screen.queryByText('Generic Tag')).not.toBeInTheDocument();
    expect(screen.queryByText('Rejected Evidence')).not.toBeInTheDocument();
    expect(screen.getByText('No governed skills matched yet')).toBeInTheDocument();
  });

  it('keeps the legacy provisional skills fallback for older detail responses', async () => {
    renderModalWithPayload(
      createJobPayload({
        skills: [],
        provisional_skills: ['Google Suite'],
        unreviewed_skill_mentions: undefined,
        skill_state: null,
      }),
    );

    expect(await screen.findByRole('heading', { name: /senior platform engineer/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /unreviewed skill mentions/i })).toBeInTheDocument();
    expect(screen.getByText('Google Suite')).toBeInTheDocument();
  });

  it('prefers a normalized numeric experience label over free-text summary text', async () => {
    renderModalWithPayload(createJobPayload());

    expect(await screen.findByRole('heading', { name: /senior platform engineer/i })).toBeInTheDocument();
    expect(screen.getByText('3-5 years')).toBeInTheDocument();
    expect(
      screen.queryByText('Typically seeks 3-5 years of backend platform experience.'),
    ).not.toBeInTheDocument();
  });

  it('renders governed role evidence without promoting legacy scalar context', async () => {
    renderModalWithPayload(
      createJobPayload({
        job_id: '7f3a-platform-engineer',
        original_job_url: 'https://hk.jobsdb.com/job/7f3a-platform-engineer',
        company_industries: {
          company_id: productFixture.job_detail.company_id,
          assignments: [],
          review_item_refs: [],
        },
      }),
    );

    expect(await screen.findByRole('heading', { name: /senior platform engineer/i })).toBeInTheDocument();
    expect(screen.getByText('Source Classification Paths')).toBeInTheDocument();
    expect(screen.getByText('Information & Communication Technology')).toBeInTheDocument();
    expect(screen.queryByText('Platform Engineering')).not.toBeInTheDocument();
    expect(screen.getByText('Company Industries')).toBeInTheDocument();
    expect(screen.getByText('No governed Company Industry assignment')).toBeInTheDocument();
    expect(screen.queryByText('Healthcare Technology')).not.toBeInTheDocument();
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
          job_taxonomy: {
            path: 'Legacy / AI / Category',
          },
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
    expect(relatedJobCard).toHaveTextContent(
      'Technology / Software Development / Backend Development',
    );
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
          job_taxonomy: {
            path: 'Information & Communication Technology / Software Development / Backend Development',
          },
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

      if (url.pathname === '/api/v1/jobs/job-1') {
        return mockJsonResponse(createJobPayload());
      }

      if (url.pathname === '/api/v1/jobs/job-1/similar') {
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
      globalThis.fetch.mock.calls.some(([input]) => String(input).includes('/api/v1/jobs/job-1/similar')),
    ).toBe(false);
  });

  it('waits for runtime capabilities before deciding whether to request related jobs', async () => {
    globalThis.fetch = vi.fn((input) => {
      const url = new URL(String(input), 'http://localhost');

      if (url.pathname === '/api/v1/jobs/job-1') {
        return mockJsonResponse(createJobPayload());
      }

      if (url.pathname === '/api/v1/jobs/job-1/similar') {
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
      globalThis.fetch.mock.calls.some(([input]) => String(input).includes('/api/v1/jobs/job-1/similar')),
    ).toBe(false);
  });
});
