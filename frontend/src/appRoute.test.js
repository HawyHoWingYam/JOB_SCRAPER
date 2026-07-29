import { describe, expect, it } from 'vitest';
import {
  hashForClassificationRoute,
  hashForJobsRoute,
  hashForView,
  parseClassificationRoute,
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

  it('round-trips exact Skill codes', () => {
    const hash = hashForJobsRoute({
      skillIds: ['skill:python'],
    });

    expect(hash).toBe('#jobs?skill_ids=skill%3Apython');
    expect(parseJobsRoute(hash)).toEqual({
      skillIds: ['skill:python'],
    });
  });

  it('keeps bare Jobs navigation and safely drops invalid route values', () => {
    expect(parseJobsRoute('#jobs')).toEqual({
      skillIds: [],
    });
    expect(
      parseJobsRoute(
        '#jobs?skill_ids=python%20label&skill_ids=python&skill_ids=python',
      ),
    ).toEqual({ skillIds: ['python'] });
    expect(hashForJobsRoute({ skillIds: ['python label'] })).toBe('#jobs');
  });

  it('parses durable Classification targets and keeps the bare default', () => {
    expect(parseClassificationRoute('#classification')).toEqual({
      target: 'skill',
    });
    expect(parseClassificationRoute('#classification?target=skill')).toEqual({
      target: 'skill',
    });
  });

  it('round-trips valid Classification targets and safely rejects invalid ones', () => {
    expect(hashForClassificationRoute('skill')).toBe(
      '#classification?target=skill',
    );
    expect(
      parseClassificationRoute('#classification?target=company_industry'),
    ).toEqual({ target: 'company_industry' });
    expect(hashForClassificationRoute('unknown')).toBe(
      '#classification?target=skill',
    );
  });
});
