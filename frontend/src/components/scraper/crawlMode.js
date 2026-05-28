const DEFAULT_CRAWL_MODE_BY_SOURCE = {
  jobsdb: 'headed',
  ctgoodjobs: 'headed',
};

export const CRAWL_MODE_OPTIONS = [
  { value: 'headless', label: 'Headless' },
  { value: 'headed', label: 'Headed' },
];
const CRAWL_MODE_OPTIONS_BY_SOURCE = {
  jobsdb: CRAWL_MODE_OPTIONS,
  ctgoodjobs: CRAWL_MODE_OPTIONS.filter((option) => option.value === 'headed'),
};

export function resolveDefaultCrawlMode(sourceSite) {
  return DEFAULT_CRAWL_MODE_BY_SOURCE[sourceSite] || 'headless';
}

export function getCrawlModeOptionsForSource(sourceSite) {
  return CRAWL_MODE_OPTIONS_BY_SOURCE[sourceSite] || CRAWL_MODE_OPTIONS;
}

export function formatCrawlModeLabel(crawlMode) {
  return crawlMode === 'headed' ? 'Headed' : 'Headless';
}
