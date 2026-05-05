import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import JobDetailModal from './JobDetailModal';

function mockJsonResponse(payload) {
  return Promise.resolve({
    ok: true,
    json: async () => payload,
  });
}

function createJobPayload(overrides = {}) {
  return {
    id: 'job-1',
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
    ai_summary: 'Builds internal platform services and backend APIs.',
    job_taxonomy: {
      path: 'Information & Communication Technology / Software Development / Backend Development',
    },
    ai_enriched_at: '2026-04-15T12:34:56Z',
    source_classification_name: 'Information & Communication Technology',
    source_subclassification_name: 'Platform Engineering',
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

describe('JobDetailModal', () => {
  beforeEach(() => {
    vi.spyOn(Date, 'now').mockReturnValue(new Date('2026-04-16T00:00:00Z').getTime());
  });

  afterEach(() => {
    vi.restoreAllMocks();
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

  it('shows explicit unenriched ai states when enrichment has not run yet', async () => {
    renderModalWithPayload(
      createJobPayload({
        ai_enriched_at: null,
        skills: [],
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
        ai_summary: null,
        job_taxonomy: null,
        experience_level: 'not_specified',
        experience_summary: null,
      }),
    );

    expect(await screen.findByRole('heading', { name: /senior platform engineer/i })).toBeInTheDocument();
    expect(screen.getByText('No technical skills extracted from this posting')).toBeInTheDocument();
    expect(screen.getByText('No AI summary extracted from this posting')).toBeInTheDocument();
    expect(screen.getByText('No governed job taxonomy assigned')).toBeInTheDocument();
    expect(screen.getByText('No explicit experience requirement found in the posting')).toBeInTheDocument();
  });

  it('renders provisional skills separately when governed skills are unavailable', async () => {
    renderModalWithPayload(
      createJobPayload({
        skills: [],
        provisional_skills: ['Google Suite', 'Zoom'],
      }),
    );

    expect(await screen.findByRole('heading', { name: /senior platform engineer/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /provisional skills/i })).toBeInTheDocument();
    expect(screen.getByText('Google Suite')).toBeInTheDocument();
    expect(screen.getByText('Zoom')).toBeInTheDocument();
    expect(screen.getByText('No governed skills matched yet')).toBeInTheDocument();
  });

  it('prefers a normalized numeric experience label over free-text summary text', async () => {
    renderModalWithPayload(createJobPayload());

    expect(await screen.findByRole('heading', { name: /senior platform engineer/i })).toBeInTheDocument();
    expect(screen.getByText('3-5 years')).toBeInTheDocument();
    expect(
      screen.queryByText('Typically seeks 3-5 years of backend platform experience.'),
    ).not.toBeInTheDocument();
  });

  it('renders the new role and company context fields', async () => {
    renderModalWithPayload(
      createJobPayload({
        job_id: '7f3a-platform-engineer',
        original_job_url: 'https://hk.jobsdb.com/job/7f3a-platform-engineer',
      }),
    );

    expect(await screen.findByRole('heading', { name: /senior platform engineer/i })).toBeInTheDocument();
    expect(screen.getByText('Source classification')).toBeInTheDocument();
    expect(screen.getByText('Information & Communication Technology')).toBeInTheDocument();
    expect(screen.getByText('Source sub-classification')).toBeInTheDocument();
    expect(screen.getByText('Platform Engineering')).toBeInTheDocument();
    expect(screen.getByText('Company industry')).toBeInTheDocument();
    expect(screen.getByText('Healthcare Technology')).toBeInTheDocument();
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
});
