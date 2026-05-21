export const CRAWL_PHASE_OPTIONS = [
  { value: 'listing', label: 'Job ID Crawl' },
  { value: 'detail', label: 'Job Detail Crawl' },
];

export function resolveDefaultCrawlPhase() {
  return 'listing';
}

export function formatCrawlPhaseLabel(crawlPhase) {
  return crawlPhase === 'detail' ? 'Job Detail Crawl' : 'Job ID Crawl';
}
