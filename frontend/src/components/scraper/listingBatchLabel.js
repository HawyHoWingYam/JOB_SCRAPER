function formatCount(value) {
    return Number(value || 0).toLocaleString();
}

export function formatScraperSourceLabel(sourceSite) {
    if (sourceSite === 'ctgoodjobs') {
        return 'CTgoodjobs';
    }

    if (sourceSite === 'jobsdb') {
        return 'JobsDB';
    }

    return sourceSite || 'Unknown source';
}

export function formatListingBatchIdentity({ sourceSite, crawlJobId }) {
    if (!crawlJobId) {
        return 'Any pending listing batch';
    }

    return `${formatScraperSourceLabel(sourceSite)} batch ${crawlJobId}`;
}

export function formatListingBatchOptionLabel(batch, formatTimestamp) {
    const identity = formatListingBatchIdentity({
        sourceSite: batch?.source_site,
        crawlJobId: batch?.crawl_job_id,
    });
    const queuedLabel = batch?.queued_at ? `Queued ${formatTimestamp(batch.queued_at)}` : null;
    const backlogLabel = `${formatCount(batch?.detail_pending)} pending / ${formatCount(batch?.listings_staged)} staged`;

    return [identity, queuedLabel, backlogLabel].filter(Boolean).join(' - ');
}
