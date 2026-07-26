import { describe, expect, it } from 'vitest';
import { hashForView, resolveAppView } from './appRoute';

describe('app hash routing', () => {
  it('preserves Job Intelligence area and item deep links as one top-level view', () => {
    expect(
      resolveAppView(
        '#job-intelligence/company-industries?item=50000000-0000-0000-0000-000000000001',
      ),
    ).toBe('job-intelligence');
    expect(hashForView('job-intelligence')).toBe(
      '#job-intelligence/job-taxonomy',
    );
  });

  it('keeps existing single-segment views and rejects unknown hashes', () => {
    expect(resolveAppView('#jobs')).toBe('jobs');
    expect(resolveAppView('#unknown')).toBe('dashboard');
  });
});
