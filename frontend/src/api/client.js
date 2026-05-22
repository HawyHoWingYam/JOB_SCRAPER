export function formatApiErrorDetail(detail) {
  if (!detail) {
    return null;
  }

  if (typeof detail === 'string') {
    return detail;
  }

  if (Array.isArray(detail)) {
    return detail
      .map((item) => item?.message || item?.msg || String(item))
      .filter(Boolean)
      .join('; ');
  }

  if (typeof detail === 'object') {
    return detail.message || detail.error || detail.reason || JSON.stringify(detail);
  }

  return String(detail);
}

export async function apiFetchJson(url, options = {}) {
  const { timeoutMs = 15000, ...fetchOptions } = options;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(url, {
      ...fetchOptions,
      signal: fetchOptions.signal || controller.signal,
    });
    const data = await response.json().catch(() => null);

    if (!response.ok) {
      throw new Error(formatApiErrorDetail(data?.detail) || `Request failed with status ${response.status}`);
    }

    return data;
  } finally {
    clearTimeout(timeout);
  }
}
