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

  it('rejects a governance-looking area under an unrelated hash prefix', () => {
    expect(parseGovernanceHash('#foo/company-industries?item=review-1')).toEqual({
      area: 'job-taxonomy',
      itemId: null,
    });
  });
});
