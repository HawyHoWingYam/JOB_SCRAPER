import { describe, expect, it } from 'vitest';

import { formatExperienceDisplay } from './experienceDisplay';

describe('formatExperienceDisplay', () => {
  it.each([
    [{ experience_min_years: 2, experience_max_years: null }, '2+', 'At least 2 years'],
    [{ experience_min_years: 1, experience_max_years: 2 }, '1+', '1–2 years'],
    [{ experience_min_years: 0, experience_max_years: 0 }, '0+', 'No experience required'],
    [{ experience_min_years: null, experience_max_years: 2 }, '≤2', 'Up to 2 years'],
    [{ experience_level: 'not_specified' }, 'Not specified', 'The posting does not specify experience'],
  ])('formats %# without changing the original range', (job, label, detail) => {
    expect(formatExperienceDisplay(job)).toEqual({ label, detail, estimated: false });
  });

  it('marks inferred bounds as estimated', () => {
    expect(
      formatExperienceDisplay({
        experience_min_years: 3,
        experience_max_years: 5,
        experience_provenance: 'inferred',
      }),
    ).toEqual({ label: 'About 3+', detail: 'Estimated 3–5 years', estimated: true });
  });

  it('does not fabricate an estimate from a level without numeric bounds', () => {
    expect(formatExperienceDisplay({ experience_level: 'senior_level' })).toEqual({
      label: 'Senior Level',
      detail: 'Seniority level only; no year range is available',
      estimated: false,
    });
  });
});
