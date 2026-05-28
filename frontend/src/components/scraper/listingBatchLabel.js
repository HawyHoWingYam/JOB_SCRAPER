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
    const backlogParts = [
        `${formatCount(batch?.listings_staged)} staged`,
        `${formatCount(batch?.detail_pending)} pending`,
    ];
    if (Number(batch?.detail_running || 0) > 0) {
        backlogParts.push(`${formatCount(batch?.detail_running)} running`);
    }
    if (Number(batch?.detail_completed || 0) > 0) {
        backlogParts.push(`${formatCount(batch?.detail_completed)} completed`);
    }
    if (Number(batch?.detail_failed || 0) > 0) {
        backlogParts.push(`${formatCount(batch?.detail_failed)} failed`);
    }
    if (Number(batch?.detail_manual_action_required || 0) > 0) {
        backlogParts.push(`${formatCount(batch?.detail_manual_action_required)} manual review`);
    }
    const backlogLabel = backlogParts.join(' / ');

    return [identity, queuedLabel, backlogLabel].filter(Boolean).join(' - ');
}
