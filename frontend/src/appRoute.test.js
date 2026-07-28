import { describe, expect, it } from 'vitest';
import {
  hashForJobsRoute,
  hashForView,
  parseJobsRoute,
  resolveAppView,
} from './appRoute';

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
    expect(resolveAppView('#jobs?skill_ids=python')).toBe('jobs');
    expect(resolveAppView('#unknown')).toBe('dashboard');
  });

  it('round-trips exact canonical Job and Skill codes', () => {
    const hash = hashForJobsRoute({
      canonicalSubcategoryIds: ['job.backend'],
      skillIds: ['skill:python'],
    });

    expect(hash).toBe(
      '#jobs?canonical_subcategory_ids=job.backend&skill_ids=skill%3Apython',
    );
    expect(parseJobsRoute(hash)).toEqual({
      canonicalSubcategoryIds: ['job.backend'],
      skillIds: ['skill:python'],
    });
  });

  it('keeps bare Jobs navigation and safely drops invalid route values', () => {
    expect(parseJobsRoute('#jobs')).toEqual({
      canonicalSubcategoryIds: [],
      skillIds: [],
    });
    expect(
      parseJobsRoute(
        '#jobs?skill_ids=python%20label&skill_ids=python&skill_ids=python',
      ),
    ).toEqual({ canonicalSubcategoryIds: [], skillIds: ['python'] });
    expect(hashForJobsRoute({ skillIds: ['python label'] })).toBe('#jobs');
  });
});
