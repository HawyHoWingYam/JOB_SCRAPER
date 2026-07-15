import { resolveDefaultCrawlMode } from './crawlMode';
import { resolveDefaultCrawlPhase } from './crawlPhase';
import { resolveDefaultMaxPages } from './maxPages';

const EMPTY_SOURCE_CATALOG = {};

export function normalizeCategoryIdsForSource(sourceSite, categoryIds) {
    if (!Array.isArray(categoryIds)) {
        return [];
    }

    if (sourceSite === 'offertoday') {
        return categoryIds
            .map((value) => Number.parseInt(`${value}`, 10))
            .filter((value) => Number.isInteger(value));
    }

    if (sourceSite === 'ctgoodjobs') {
        return categoryIds.filter(
            (value) => typeof value === 'string' && value.startsWith('ctgoodjobs:')
        );
    }

    return categoryIds
        .map((value) => Number.parseInt(`${value}`, 10))
        .filter((value) => Number.isInteger(value));
}

export function buildImmediateScrapePayload(
    form,
    sourceSite,
    sourceCatalog = EMPTY_SOURCE_CATALOG,
) {
    const crawlPhase = form?.crawl_phase || resolveDefaultCrawlPhase();
    const categoryIds = normalizeCategoryIdsForSource(sourceSite, form?.category_ids);
    const maxPages = Number.parseInt(`${form?.max_pages ?? ''}`, 10);
    const detailLimit = Number.parseInt(`${form?.detail_limit ?? ''}`, 10);
    const sourceListingCrawlJobId = `${form?.source_listing_crawl_job_id ?? ''}`.trim();

    if (crawlPhase === 'listing' && categoryIds.length === 0 && sourceSite !== 'offertoday') {
        return { error: 'Please select at least one category.' };
    }

    if (crawlPhase === 'listing' && (!Number.isInteger(maxPages) || maxPages < 1 || maxPages > 9999)) {
        return { error: 'Max pages must be a whole number between 1 and 1000.' };
    }

    if (
        crawlPhase === 'detail'
        && categoryIds.length === 0
        && !sourceListingCrawlJobId
        && sourceSite !== 'offertoday'
    ) {
        return { error: 'Detail runs need categories or a source listing crawl job ID.' };
    }

    if (crawlPhase === 'detail' && (!Number.isInteger(detailLimit) || detailLimit < 1 || detailLimit > 5000)) {
        return { error: 'Detail batch size must be a whole number between 1 and 5000.' };
    }

    return {
        payload: {
            source_site: sourceSite,
            crawl_phase: crawlPhase,
            crawl_mode: form?.crawl_mode || resolveDefaultCrawlMode(sourceSite, sourceCatalog),
            category_ids: crawlPhase === 'detail' && sourceSite === 'offertoday'
                ? []
                : categoryIds,
            max_pages: Number.isInteger(maxPages)
                ? maxPages
                : resolveDefaultMaxPages(sourceSite, sourceCatalog),
            detail_limit: crawlPhase === 'detail' ? detailLimit : 100,
            // Listing skips already-published jobs; detail retries persisted backlog rows.
            skip_existing: crawlPhase !== 'detail',
            ...(crawlPhase === 'detail' && sourceSite === 'offertoday'
                ? { detail_scope: sourceListingCrawlJobId ? 'listing_batch' : 'global' }
                : {}),
            ...(sourceListingCrawlJobId
                ? { source_listing_crawl_job_id: sourceListingCrawlJobId }
                : {}),
        },
    };
}
