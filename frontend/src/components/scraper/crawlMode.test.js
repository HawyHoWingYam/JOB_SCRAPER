import { describe, expect, it } from 'vitest';

import { getCrawlModeOptionsForSource, resolveDefaultCrawlMode } from './crawlMode';

const SOURCE_CATALOG = {
  jobsdb: {
    supported_crawl_modes: ['headless', 'headed'],
    default_crawl_mode: 'headed',
    default_max_pages: 3,
    label: 'JobsDB Live',
  },
  ctgoodjobs: {
    supported_crawl_modes: ['headed'],
    default_crawl_mode: 'headed',
    default_max_pages: 3,
    label: 'CTGoodJobs Live',
  },
  offertoday: {
    supported_crawl_modes: ['headless', 'headed'],
    default_crawl_mode: 'headless',
    default_max_pages: 50,
    label: 'OfferToday Live',
  },
};

describe('getCrawlModeOptionsForSource', () => {
  it('reads supported crawl modes from supplied source metadata', () => {
    const sourceCatalog = {
      ...SOURCE_CATALOG,
      jobsdb: {
        ...SOURCE_CATALOG.jobsdb,
        supported_crawl_modes: ['headless'],
      },
    };

    expect(getCrawlModeOptionsForSource('jobsdb', sourceCatalog)).toEqual([
      { value: 'headless', label: 'Headless' },
    ]);
  });
});

describe('resolveDefaultCrawlMode', () => {
  it('reads the default crawl mode from supplied source metadata', () => {
    const sourceCatalog = {
      ...SOURCE_CATALOG,
      jobsdb: {
        ...SOURCE_CATALOG.jobsdb,
        default_crawl_mode: 'headless',
      },
    };

    expect(resolveDefaultCrawlMode('jobsdb', sourceCatalog)).toBe('headless');
  });

  it('supports single-mode sources from supplied metadata', () => {
    expect(getCrawlModeOptionsForSource('ctgoodjobs', SOURCE_CATALOG)).toEqual([
      { value: 'headed', label: 'Headed' },
    ]);
  });
});
