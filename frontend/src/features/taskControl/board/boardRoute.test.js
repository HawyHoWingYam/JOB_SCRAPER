import { describe, expect, it } from 'vitest';
import { buildCrawlTaskRoute, parseCrawlTaskRoute } from './boardRoute';

describe('Task Control Board routes', () => {
  it('round-trips opaque crawl task IDs without applying Automation ID rules', () => {
    const hash = buildCrawlTaskRoute('crawl/job 7', 'events');
    expect(hash).toBe('#crawl-tasks?task=crawl%2Fjob+7&view=events');
    expect(parseCrawlTaskRoute(hash)).toMatchObject({ kind: 'tasks', taskId: 'crawl/job 7', view: 'events' });
  });
});

it('preserves validated list context through task and events navigation', () => {
  const context = { filters: { status: 'failed', sourceSite: 'jobsdb', crawlMode: 'headed', timeRange: '7d' }, page: 3 };
  expect(parseCrawlTaskRoute(buildCrawlTaskRoute('task-1', 'events', context))).toMatchObject(context);
});

it('normalizes unsupported filters and invalid pages to safe defaults', () => {
  expect(parseCrawlTaskRoute('#crawl-tasks?status=wrong&source=wrong&page=-3')).toMatchObject({
    filters: { status: 'all', sourceSite: 'all', crawlMode: 'all', timeRange: 'all' }, page: 1,
  });
});
