import { describe, expect, it } from 'vitest';
import { buildCrawlTaskRoute, parseCrawlTaskRoute } from './boardRoute';

describe('Task Control Board routes', () => {
  it('round-trips opaque crawl task IDs without applying Automation ID rules', () => {
    const hash = buildCrawlTaskRoute('crawl/job 7', 'events');
    expect(hash).toBe('#crawl-tasks?task=crawl%2Fjob+7&view=events');
    expect(parseCrawlTaskRoute(hash)).toEqual({ kind: 'tasks', taskId: 'crawl/job 7', view: 'events' });
  });
});
