import { formatApiErrorDetail } from './errors';

function mergeAbortSignals(callerSignal, timeoutSignal) {
  if (!callerSignal) {
    return { signal: timeoutSignal, cleanup: () => {} };
  }

  if (typeof AbortSignal !== 'undefined' && typeof AbortSignal.any === 'function') {
    return { signal: AbortSignal.any([callerSignal, timeoutSignal]), cleanup: () => {} };
  }

  const controller = new AbortController();
  const abort = () => {
    if (!controller.signal.aborted) {
      controller.abort();
    }
  };

  callerSignal.addEventListener('abort', abort, { once: true });
  timeoutSignal.addEventListener('abort', abort, { once: true });

  if (callerSignal.aborted || timeoutSignal.aborted) {
    abort();
  }

  return {
    signal: controller.signal,
    cleanup: () => {
      callerSignal.removeEventListener('abort', abort);
      timeoutSignal.removeEventListener('abort', abort);
    },
  };
}

export async function apiFetchJson(url, options = {}) {
  const { timeoutMs = 15000, ...fetchOptions } = options;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  const { signal, cleanup } = mergeAbortSignals(fetchOptions.signal, controller.signal);

  try {
    const response = await fetch(url, {
      ...fetchOptions,
      signal,
    });
    const data = await response.json().catch(() => null);

    if (!response.ok) {
      throw new Error(formatApiErrorDetail(data?.detail) || `Request failed with status ${response.status}`);
    }

    return data;
  } finally {
    clearTimeout(timeout);
    cleanup();
  }
}
