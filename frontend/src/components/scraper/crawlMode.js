const DEFAULT_CRAWL_MODE_BY_SOURCE = {
  jobsdb: 'headed',
  ctgoodjobs: 'headed',
};

export const CRAWL_MODE_OPTIONS = [
  { value: 'headless', label: 'Headless' },
  { value: 'headed', label: 'Headed' },
];

export function resolveDefaultCrawlMode(sourceSite) {
  return DEFAULT_CRAWL_MODE_BY_SOURCE[sourceSite] || 'headless';
}

export function formatCrawlModeLabel(crawlMode) {
  return crawlMode === 'headed' ? 'Headed' : 'Headless';
}
