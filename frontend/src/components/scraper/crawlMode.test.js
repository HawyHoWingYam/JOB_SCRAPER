import { describe, expect, it } from 'vitest';

import { getCrawlModeOptionsForSource, resolveDefaultCrawlMode } from './crawlMode';

describe('resolveDefaultCrawlMode', () => {
  it('defaults ctgoodjobs to headed', () => {
    expect(resolveDefaultCrawlMode('ctgoodjobs')).toBe('headed');
  });

  it('limits ctgoodjobs crawl mode options to headed only', () => {
    expect(getCrawlModeOptionsForSource('ctgoodjobs')).toEqual([
      { value: 'headed', label: 'Headed' },
    ]);
  });
});
