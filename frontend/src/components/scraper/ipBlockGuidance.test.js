import { describe, expect, it } from 'vitest';

import { buildIpBlockGuidance } from './ipBlockGuidance';


describe('buildIpBlockGuidance', () => {
  it.each([
    ['ctgoodjobs', 'CTGoodJobs'],
    ['jobsdb', 'JobsDB'],
    ['offertoday', 'OfferToday'],
  ])('builds source-aware same-task recovery text for %s', (sourceSite, sourceLabel) => {
    const guidance = buildIpBlockGuidance({ sourceSite });

    expect(guidance.title).toContain(sourceLabel);
    expect(guidance.message).toContain(sourceLabel);
    expect(guidance.message).toMatch(/change.+IP|change.+network/i);
    expect(guidance.message).toContain('resume this same task');
    expect(guidance.message).toContain('progress is preserved');
  });

  it('uses a safe unknown-source fallback and keeps explicit context', () => {
    const guidance = buildIpBlockGuidance({
      sourceSite: 'partner-site',
      message: 'The upstream gateway rejected access.',
    });

    expect(guidance.title).toContain('partner-site');
    expect(guidance.message).toContain('The upstream gateway rejected access.');
    expect(guidance.message).toContain('resume this same task');
  });
});
