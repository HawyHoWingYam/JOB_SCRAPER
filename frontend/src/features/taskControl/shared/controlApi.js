import { apiPath } from '../../../api/base';
import { apiFetchJson, ApiRequestError } from '../../../api/client';
import { cancelCrawlJob } from '../../../components/scraper/crawlTaskActions';
import { getPublishedCatalog as getGovernedPublishedCatalog } from '../../sourceCatalogs/sourceCatalogsApi';
import {
  decodeAutomation,
  decodeAutomationReview,
  decodeCrawlJob,
  decodeDispatchPreparation,
  decodeDispatchResult,
} from './controlDecoders';

const json = (body, method = 'POST') => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});

export function getPublishedCatalog(source, options) {
  return getGovernedPublishedCatalog(source, options);
}

export async function getAutomation(id, { signal } = {}) {
  return decodeAutomation(
    await apiFetchJson(apiPath(`/automations/${encodeURIComponent(id)}`), { signal }),
  );
}

export async function reviewAutomation(request, { signal } = {}) {
  return decodeAutomationReview(
    await apiFetchJson(apiPath('/automations/reviews'), { ...json(request), signal }),
  );
}

export async function createAutomation(request) {
  return decodeAutomation(await apiFetchJson(apiPath('/automations'), json(request)));
}

export async function updateAutomation(id, request) {
  return decodeAutomation(
    await apiFetchJson(apiPath(`/automations/${encodeURIComponent(id)}`), json(request, 'PUT')),
  );
}

export async function prepareDispatchPlan(request, { signal } = {}) {
  return decodeDispatchPreparation(
    await apiFetchJson(apiPath('/dispatch-plans'), { ...json(request), signal }),
  );
}

export async function getDispatchPlan(id, { signal } = {}) {
  const payload = await apiFetchJson(apiPath(`/dispatch-plans/${encodeURIComponent(id)}`), { signal });
  return decodeDispatchPreparation({ plan: payload, confirmation_token: null });
}

export async function dispatchPlan(id, confirmationToken, expectedFingerprint) {
  return decodeDispatchResult(
    await apiFetchJson(
      apiPath(`/dispatch-plans/${encodeURIComponent(id)}/dispatch`),
      json({
        confirmation_token: confirmationToken,
        expected_plan_fingerprint: expectedFingerprint,
      }),
    ),
  );
}

export async function getCrawlJob(id, { signal } = {}) {
  return decodeCrawlJob(
    await apiFetchJson(apiPath(`/crawl-jobs/${encodeURIComponent(id)}`), { signal }),
  );
}

export { cancelCrawlJob };

export function controlError(error) {
  if (error instanceof ApiRequestError) {
    return {
      code: error.code,
      message: error.message,
      details: error.details,
      requestId: error.requestId,
      stale: [
        'AUTOMATION_REVIEW_STALE',
        'AUTOMATION_REVISION_CONFLICT',
        'DISPATCH_PLAN_EXPIRED',
        'DISPATCH_PLAN_STALE',
        'DISPATCH_PLAN_ALREADY_CONSUMED',
        'DISPATCH_PLAN_FINGERPRINT_MISMATCH',
      ].includes(error.code),
    };
  }
  return { code: null, message: error?.message || 'Request failed', details: null, requestId: null, stale: false };
}
