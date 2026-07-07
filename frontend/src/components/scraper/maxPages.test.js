import { describe, expect, it } from 'vitest';

import { resolveDefaultMaxPages } from './maxPages';

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

describe('resolveDefaultMaxPages', () => {
    it('reads default page depth from supplied source metadata', () => {
        const sourceCatalog = {
            ...SOURCE_CATALOG,
            jobsdb: {
                ...SOURCE_CATALOG.jobsdb,
                default_max_pages: 11,
            },
        };

        expect(resolveDefaultMaxPages('jobsdb', sourceCatalog)).toBe(11);
    });
});
