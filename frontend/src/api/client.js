import { createMonitoringId, logError } from '../monitoring';
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
  const { timeoutMs = 15000, requestId = createMonitoringId('req'), ...fetchOptions } = options;
  const startedAt = Date.now();
  const headers = new Headers(fetchOptions.headers || {});
  const effectiveRequestId = headers.get('X-Request-ID') || requestId;
  const method = (fetchOptions.method || 'GET').toUpperCase();
  let failureLogged = false;

  headers.set('X-Request-ID', effectiveRequestId);

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  const { signal, cleanup } = mergeAbortSignals(fetchOptions.signal, controller.signal);

  try {
    const response = await fetch(url, {
      ...fetchOptions,
      headers,
      signal,
    });
    const data = await response.json().catch(() => null);

    if (!response.ok) {
      const message = formatApiErrorDetail(data?.detail) || `Request failed with status ${response.status}`;

      failureLogged = true;
      logError('api.request_failed', {
        requestId: effectiveRequestId,
        method,
        status: response.status,
        url,
        durationMs: Date.now() - startedAt,
        detail: message,
      });
      throw new Error(message);
    }

    return data;
  } catch (error) {
    if (!failureLogged) {
      logError('api.request_failed', {
        requestId: effectiveRequestId,
        method,
        url,
        durationMs: Date.now() - startedAt,
        detail: error,
      });
    }

    throw error;
  } finally {
    clearTimeout(timeout);
    cleanup();
  }
}
