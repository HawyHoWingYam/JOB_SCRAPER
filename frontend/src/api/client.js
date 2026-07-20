import { createMonitoringId, logError } from '../monitoring';
import { formatApiErrorDetail } from './errors';

export class ApiRequestError extends Error {
  constructor(
    message,
    {
      status,
      code = null,
      details = null,
      detail = details,
      requestId = null,
    } = {},
  ) {
    super(message);
    this.name = 'ApiRequestError';
    this.status = status;
    this.code = code;
    this.details = details;
    // Keep the original singular field for existing callers.
    this.detail = detail;
    this.requestId = requestId;
  }
}

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
      const envelope =
        data?.detail && typeof data.detail === 'object' && !Array.isArray(data.detail)
          ? data.detail
          : data && typeof data === 'object' && !Array.isArray(data)
            ? data
            : null;
      const rawDetail = data?.detail ?? data?.details ?? null;
      const message =
        (typeof envelope?.message === 'string' && envelope.message.trim()) ||
        formatApiErrorDetail(rawDetail) ||
        `Request failed with status ${response.status}`;
      const responseRequestId =
        response.headers?.get?.('X-Request-ID') ||
        envelope?.requestId ||
        envelope?.request_id ||
        effectiveRequestId;
      const details =
        envelope?.details ?? envelope?.context ?? rawDetail;

      failureLogged = true;
      logError('api.request_failed', {
        requestId: responseRequestId,
        method,
        status: response.status,
        url,
        durationMs: Date.now() - startedAt,
        detail: message,
      });
      throw new ApiRequestError(message, {
        status: response.status,
        code: envelope?.code || null,
        details,
        detail: rawDetail,
        requestId: responseRequestId,
      });
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
