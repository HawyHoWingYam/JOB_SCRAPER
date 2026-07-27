import { describe, expect, it } from 'vitest';
import { hashForView, resolveAppView } from './appRoute';

describe('app hash routing', () => {
  it('rejects removed Job Intelligence governance deep links', () => {
    expect(
      resolveAppView(
        '#job-intelligence/company-industries?item=50000000-0000-0000-0000-000000000001',
      ),
    ).toBe('dashboard');
    expect(hashForView('job-intelligence')).toBe('#dashboard');
  });

  it('keeps existing single-segment views and rejects unknown hashes', () => {
    expect(resolveAppView('#jobs')).toBe('jobs');
    expect(resolveAppView('#unknown')).toBe('dashboard');
  });
});
