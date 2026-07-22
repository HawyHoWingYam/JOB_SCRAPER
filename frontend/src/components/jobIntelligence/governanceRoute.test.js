import { describe, expect, it } from 'vitest';

import { governanceHash, parseGovernanceHash } from './governanceRoute';

describe('governance hash routing', () => {
  it('round-trips a valid area and item deep link', () => {
    const hash = governanceHash('company-industries', 'review-1');

    expect(hash).toBe('#job-intelligence/company-industries?item=review-1');
    expect(parseGovernanceHash(hash)).toEqual({
      area: 'company-industries',
      itemId: 'review-1',
    });
  });

  it('round-trips queue filters and an opaque pagination cursor', () => {
    const hash = governanceHash('skill-candidates', 'candidate-1', {
      query: 'rust async',
      cursor: 'created-at+candidate-id',
    });

    expect(hash).toBe(
      '#job-intelligence/skill-candidates?item=candidate-1&q=rust+async&cursor=created-at%2Bcandidate-id',
    );
    expect(parseGovernanceHash(hash)).toEqual({
      area: 'skill-candidates',
      itemId: 'candidate-1',
      query: 'rust async',
      cursor: 'created-at+candidate-id',
    });
  });

  it('round-trips a scoped AI batch and direct page number', () => {
    const hash = governanceHash('job-taxonomy', null, {
      source_sites: ['offertoday'],
      source_classification_ids: ['offertoday:121000'],
      source_subclassification_ids: ['offertoday:121015'],
      posted_date_from: '2026-07-01',
      posted_date_to: '2026-07-22',
      pendingLimit: 50,
      reason: 'source_catalog_provenance_missing',
      page: 3,
      jobIds: ['job-1', 'job-2'],
    });

    expect(hash).toBe(
      '#job-intelligence/job-taxonomy?source_site=offertoday&source_classification_id=offertoday%3A121000&source_subclassification_id=offertoday%3A121015&job_id=job-1&job_id=job-2&posted_date_from=2026-07-01&posted_date_to=2026-07-22&pending_limit=50&reason=source_catalog_provenance_missing&page=3',
    );
    expect(parseGovernanceHash(hash)).toEqual({
      area: 'job-taxonomy',
      itemId: null,
      page: 3,
      scope: {
        sourceSites: ['offertoday'],
        sourceClassificationIds: ['offertoday:121000'],
        sourceSubclassificationIds: ['offertoday:121015'],
        postedDateFrom: '2026-07-01',
        postedDateTo: '2026-07-22',
        pendingLimit: 50,
        reason: 'source_catalog_provenance_missing',
        jobIds: ['job-1', 'job-2'],
      },
    });
  });

  it('rejects a governance-looking area under an unrelated hash prefix', () => {
    expect(parseGovernanceHash('#foo/company-industries?item=review-1')).toEqual({
      area: 'job-taxonomy',
      itemId: null,
    });
  });
});
