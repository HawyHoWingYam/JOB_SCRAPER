import { apiPath } from '../../api/base';
import { apiFetchJson } from '../../api/client';
import { createMonitoringId } from '../../monitoring';

const API_BASE = apiPath('');
const DEFAULT_MANUAL_ACTION_HELPER_URL = 'http://127.0.0.1:47652';

function buildManualActionHelperUnavailableMessage(actionLabel) {
  return `Manual-action helper is unavailable. Start the dedicated helper service and retry ${actionLabel}.`;
}

function resolveManualActionHelperUrl(helperUrl) {
  return helperUrl || DEFAULT_MANUAL_ACTION_HELPER_URL;
}

async function postManualActionHelper({ crawlJobId, helperUrl, path, actionLabel, fallbackDetail }) {
  const requestId = createMonitoringId('req');

  try {
    return await apiFetchJson(`${resolveManualActionHelperUrl(helperUrl)}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ crawl_job_id: crawlJobId }),
      requestId,
    });
  } catch (error) {
    const isTransportFailure =
      error instanceof Error && (error.name === 'TypeError' || error.name === 'AbortError');
    const detail = isTransportFailure
      ? buildManualActionHelperUnavailableMessage(actionLabel)
      : error instanceof Error && error.message
        ? error.message
        : fallbackDetail;

    throw new Error(detail);
  }
}

export async function resumeCrawlJob(crawlJobId, strategy) {
  const body = strategy ? JSON.stringify({ strategy }) : null;

  return apiFetchJson(`${API_BASE}/crawl-jobs/${crawlJobId}/resume`, {
    method: 'POST',
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body,
    requestId: createMonitoringId('req'),
  });
}

export async function cancelCrawlJob(crawlJobId) {
  return apiFetchJson(`${API_BASE}/crawl-jobs/${crawlJobId}/cancel`, {
    method: 'POST',
    requestId: createMonitoringId('req'),
  });
}

export async function openManualActionBrowser(crawlJobId, helperUrl) {
  return postManualActionHelper({
    crawlJobId,
    helperUrl,
    path: '/manual-actions/open-browser',
    actionLabel: 'opening the verification browser',
    fallbackDetail: 'Failed to open verification browser',
  });
}

export async function getManualActionReuseStatus(crawlJobId, helperUrl) {
  return postManualActionHelper({
    crawlJobId,
    helperUrl,
    path: '/manual-actions/reuse-status',
    actionLabel: 'the attach status check',
    fallbackDetail: 'Failed to check open-browser reuse status',
  });
}

export async function closeManualActionWindows(crawlJobId, helperUrl) {
  return postManualActionHelper({
    crawlJobId,
    helperUrl,
    path: '/manual-actions/close-profile-windows',
    actionLabel: 'closing the verification profile windows',
    fallbackDetail: 'Failed to close profile windows',
  });
}
