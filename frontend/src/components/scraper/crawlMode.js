export const CRAWL_MODE_OPTIONS = [
  { value: 'headless', label: 'Headless' },
  { value: 'headed', label: 'Headed' },
];

export function getCrawlModeOptionsForSource(sourceSite, sources = {}) {
  const supportedModeSet = new Set(sources?.[sourceSite]?.supported_crawl_modes || []);
  const crawlModeOptions = CRAWL_MODE_OPTIONS.filter((option) => supportedModeSet.has(option.value));

  return crawlModeOptions.length > 0 ? crawlModeOptions : CRAWL_MODE_OPTIONS;
}

export function resolveDefaultCrawlMode(sourceSite, sources = {}) {
  const crawlModeOptions = getCrawlModeOptionsForSource(sourceSite, sources);
  const configuredDefault = sources?.[sourceSite]?.default_crawl_mode;

  if (crawlModeOptions.some((option) => option.value === configuredDefault)) {
    return configuredDefault;
  }

  return crawlModeOptions[0]?.value || 'headless';
}

export function formatCrawlModeLabel(crawlMode) {
  return crawlMode === 'headed' ? 'Headed' : 'Headless';
}
