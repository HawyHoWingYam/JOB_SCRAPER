import { describe, expect, it } from 'vitest';

import { resolveDefaultCrawlMode } from './crawlMode';

describe('resolveDefaultCrawlMode', () => {
  it('defaults ctgoodjobs to headless', () => {
    expect(resolveDefaultCrawlMode('ctgoodjobs')).toBe('headless');
  });
});
