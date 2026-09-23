import { apiPath } from './base';
import { apiFetchJson, ApiRequestError } from './client';

const ROOT = '/offertoday-keyword-packs';

export function fetchOfferTodayKeywordPacks(options) {
  return apiFetchJson(apiPath(ROOT), options);
}

export async function downloadOfferTodayKeywordPacksCsv() {
  const response = await fetch(apiPath(`${ROOT}/csv`));
  if (!response.ok) {
    throw new ApiRequestError('Could not download the CSV. Please retry.', { status: response.status });
  }
  return response.blob();
}

export function previewOfferTodayKeywordPacksCsv(csvContent, options) {
  return apiFetchJson(apiPath(`${ROOT}/csv/preview`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ csv_content: csvContent }),
    ...options,
  });
}

export function confirmOfferTodayKeywordPacksCsv(preview, options) {
  return apiFetchJson(apiPath(`${ROOT}/csv/confirm`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      confirmation_token: preview.confirmation_token,
      csv_hash: preview.csv_hash,
    }),
    ...options,
  });
}
