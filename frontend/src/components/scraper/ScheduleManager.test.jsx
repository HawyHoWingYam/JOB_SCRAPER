import { describe, expect, it } from 'vitest';

import { buildImmediateScrapePayload } from './schedulePayload';


const baseForm = {
  crawl_phase: 'detail',
  crawl_mode: 'headless',
  category_ids: [118000],
  max_pages: 1,
  detail_limit: 5000,
  source_listing_crawl_job_id: '',
};


describe('OfferToday immediate detail scope', () => {
  it('submits an empty batch selector as the global OfferToday backlog', () => {
    const result = buildImmediateScrapePayload(baseForm, 'offertoday');

    expect(result.error).toBeUndefined();
    expect(result.payload).toMatchObject({
      source_site: 'offertoday',
      crawl_phase: 'detail',
      detail_scope: 'global',
      category_ids: [],
      detail_limit: 5000,
      skip_existing: false,
    });
    expect(result.payload).not.toHaveProperty('source_listing_crawl_job_id');
  });

  it('persists an explicitly selected listing batch', () => {
    const result = buildImmediateScrapePayload({
      ...baseForm,
      source_listing_crawl_job_id: 'listing-task',
    }, 'offertoday');

    expect(result.payload).toMatchObject({
      detail_scope: 'listing_batch',
      source_listing_crawl_job_id: 'listing-task',
      category_ids: [],
    });
  });

  it('keeps the category requirement for non-OfferToday detail runs', () => {
    const result = buildImmediateScrapePayload({
      ...baseForm,
      category_ids: [],
    }, 'jobsdb');

    expect(result).toEqual({
      error: 'Detail runs need categories or a source listing crawl job ID.',
    });
  });
});
