const explicitApiUrl = import.meta.env.VITE_API_URL?.trim();
const shouldUseDevProxy = Boolean(import.meta.env.DEV);

function normalizeApiBase(url) {
  if (!url) {
    return '';
  }

  return url.endsWith('/') ? url.slice(0, -1) : url;
}

export const API_BASE_URL = shouldUseDevProxy ? '' : normalizeApiBase(explicitApiUrl);

/** Single current API prefix. */
export const API_PREFIX = '/api';

/**
 * Build a full API path relative to the backend root.
 * Usage: apiPath('/jobs/search') → "/api/jobs/search"
 *        apiPath('') → "/api"
 */
export function apiPath(path) {
  if (!path) {
    return `${API_BASE_URL}${API_PREFIX}`;
  }
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  return `${API_BASE_URL}${API_PREFIX}${normalizedPath}`;
}
