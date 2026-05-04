import { describe, expect, it } from 'vitest';

import {
  countPendingQueryChanges,
  formatDateInputValue,
  getDateValidationError,
  getDatePresetForQuery,
  normalizeDraftKeyword,
  normalizeQueryForSubmit,
  queriesAreEqual,
} from './jobBrowserQueryUtils';

describe('jobBrowserQueryUtils', () => {
  it('normalizes keyword separators into single spaces', () => {
    expect(normalizeDraftKeyword(' python,  banking backend ')).toBe('python banking backend');
  });

  it('treats identical logical queries as equal', () => {
    expect(
      queriesAreEqual(
        {
          search_query: '',
          employment_type: '',
          subcategory_ids: [],
          industry: '',
          experience_years_from: '',
          experience_years_to: '',
          posted_date_from: '2026-04-10',
          posted_date_to: '2026-04-16',
        },
        {
          search_query: '',
          employment_type: '',
          subcategory_ids: [],
          industry: '',
          experience_years_from: '',
          experience_years_to: '',
          posted_date_from: '2026-04-10',
          posted_date_to: '2026-04-16',
        },
      ),
    ).toBe(true);
  });

  it('treats experience ranges as part of query equality', () => {
    expect(
      queriesAreEqual(
        {
          search_query: '',
          employment_type: '',
          subcategory_ids: [],
          industry: '',
          experience_years_from: '2',
          experience_years_to: '5',
          posted_date_from: '2026-04-10',
          posted_date_to: '2026-04-16',
        },
        {
          search_query: '',
          employment_type: '',
          subcategory_ids: [],
          industry: '',
          experience_years_from: '3',
          experience_years_to: '5',
          posted_date_from: '2026-04-10',
          posted_date_to: '2026-04-16',
        },
      ),
    ).toBe(false);
  });

  it('counts a posting window as one logical pending change', () => {
    expect(
      countPendingQueryChanges(
        {
          search_query: '',
          employment_type: '',
          subcategory_ids: [],
          industry: '',
          experience_years_from: '',
          experience_years_to: '',
          posted_date_from: '',
          posted_date_to: '',
        },
        {
          search_query: '',
          employment_type: '',
          subcategory_ids: [],
          industry: '',
          experience_years_from: '',
          experience_years_to: '',
          posted_date_from: '2026-04-10',
          posted_date_to: '2026-04-16',
        },
      ),
    ).toBe(1);
  });

  it('counts an experience range as one logical pending change', () => {
    expect(
      countPendingQueryChanges(
        {
          search_query: '',
          employment_type: '',
          subcategory_ids: [],
          industry: '',
          experience_years_from: '',
          experience_years_to: '',
          posted_date_from: '',
          posted_date_to: '',
        },
        {
          search_query: '',
          employment_type: '',
          subcategory_ids: [],
          industry: '',
          experience_years_from: '2',
          experience_years_to: '5',
          posted_date_from: '',
          posted_date_to: '',
        },
      ),
    ).toBe(1);
  });

  it('normalizes zero-valued experience filters into canonical integer strings', () => {
    expect(
      normalizeQueryForSubmit({
        experience_years_from: 0,
        experience_years_to: '00',
      }),
    ).toMatchObject({
      experience_years_from: '0',
      experience_years_to: '0',
    });
  });

  it('rejects invalid experience filter inputs', () => {
    expect(
      getDateValidationError({
        experience_years_from: '2.5',
      }),
    ).toMatch(/whole numbers greater than or equal to 0/i);

    expect(
      getDateValidationError({
        experience_years_from: '-1',
      }),
    ).toMatch(/whole numbers greater than or equal to 0/i);

    expect(
      getDateValidationError({
        experience_years_from: '2e3',
      }),
    ).toMatch(/whole numbers greater than or equal to 0/i);
  });

  it('returns custom for a non-preset date range', () => {
    const today = new Date();
    const customStart = new Date(today);
    customStart.setDate(today.getDate() - 8);

    expect(
      getDatePresetForQuery({
        posted_date_from: formatDateInputValue(customStart),
        posted_date_to: formatDateInputValue(today),
      }),
    ).toBe('custom');
  });
});
