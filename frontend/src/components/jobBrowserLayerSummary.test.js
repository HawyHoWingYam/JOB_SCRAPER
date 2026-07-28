import { describe, expect, it } from 'vitest';

import { summarizeJobBrowserLayer } from './jobBrowserLayerSummary';


describe('Job Browser applied layer summaries', () => {
  it('describes every visible structured filter with facet labels', () => {
    expect(summarizeJobBrowserLayer({
      client_id: 'root',
      text_expression: 'platform engineer',
      structured_filters: {
        source_site: 'jobsdb',
        employment_type_codes: ['full_time'],
        canonical_domain_ids: ['technology'],
        company_industry_node_ids: ['J'],
        posted_date_from: '2026-07-01',
        experience_years_to: '3',
      },
    }, {
      sources: [{ id: 'jobsdb', label: 'JobsDB' }],
      employment_types: [{ id: 'full_time', label: 'Full-time' }],
      canonical_job_taxonomy: [{ id: 'technology', label: 'Technology' }],
      company_industries: [{ id: 'J', label: 'Information and communications' }],
    })).toEqual(expect.arrayContaining([
      'Text: platform engineer',
      'Source: JobsDB',
      'Employment Type: Full-time',
      'Canonical Job Taxonomy: Technology',
      'Company Industry: Information and communications',
      'Posted from: 2026-07-01',
      'Experience: up to 3 years',
    ]));
  });
});
