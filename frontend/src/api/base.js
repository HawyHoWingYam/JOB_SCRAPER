const explicitApiUrl = import.meta.env.VITE_API_URL?.trim();
const shouldUseDevProxy = Boolean(import.meta.env.DEV);

function normalizeApiBase(url) {
  if (!url) {
    return '';
  }

  return url.endsWith('/') ? url.slice(0, -1) : url;
}

export const API_BASE_URL = shouldUseDevProxy ? '' : normalizeApiBase(explicitApiUrl);
