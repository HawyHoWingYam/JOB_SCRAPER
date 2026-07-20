import { apiPath } from '../../../api/base';
import { apiFetchJson } from '../../../api/client';
import { cancelCrawlJob } from '../../../components/scraper/crawlTaskActions';
import { decodeBoard, decodeDeleteReview, decodeTaskDetail } from './boardDecoders';

const json = (body, method = 'POST') => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});

export async function getTaskControlBoard(sourceSite, { signal } = {}) {
  const query = new URLSearchParams({ version: '2', source_site: sourceSite });
  return decodeBoard(await apiFetchJson(apiPath(`/task-control-board?${query}`), { signal }));
}

export async function getCrawlTaskDetail(taskId, { signal } = {}) {
  return decodeTaskDetail(await apiFetchJson(
    apiPath(`/crawl-jobs/tasks/${encodeURIComponent(taskId)}`),
    { signal },
  ));
}

export async function transitionAutomation(automationId, action, expectedRevision) {
  return apiFetchJson(
    apiPath(`/automations/${encodeURIComponent(automationId)}/${action}`),
    json({ expected_revision: expectedRevision, ...(action === 'restore' ? { activate: false } : {}) }),
  );
}

export async function reviewAutomationDelete(automationId) {
  return decodeDeleteReview(await apiFetchJson(
    apiPath(`/automations/${encodeURIComponent(automationId)}/delete-reviews`),
    json({}),
  ));
}

export async function permanentlyDeleteAutomation(automationId, expectedRevision, reviewToken) {
  return apiFetchJson(
    apiPath(`/automations/${encodeURIComponent(automationId)}`),
    json({ expected_revision: expectedRevision, review_token: reviewToken }, 'DELETE'),
  );
}

export async function resumeManualTask(taskId, strategy = 'fresh_profile') {
  return apiFetchJson(
    apiPath(`/crawl-jobs/${encodeURIComponent(taskId)}/resume`),
    json({ strategy }),
  );
}

export { cancelCrawlJob };
