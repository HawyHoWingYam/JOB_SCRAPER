import { beforeEach, describe, expect, it, vi } from 'vitest';
import { formatApiErrorDetail } from './errors';

const { logErrorSpy } = vi.hoisted(() => ({
  logErrorSpy: vi.fn(),
}));

vi.mock('../monitoring', () => ({
  createMonitoringId: vi.fn(() => 'req-fixed'),
  logError: logErrorSpy,
}));

import { apiFetchJson } from './client';

describe('api client', () => {
  beforeEach(() => {
    logErrorSpy.mockReset();
  });

  it('attaches a request id header to monitored JSON fetches', async () => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve({
        ok: true,
        json: async () => ({ ok: true }),
      }),
    );

    await apiFetchJson('/api/v1/capabilities');

    const headers = globalThis.fetch.mock.calls[0][1].headers;
    expect(headers.get('X-Request-ID')).toBe('req-fixed');
  });

  it('logs structured failure context for non-ok responses', async () => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve({
        ok: false,
        status: 503,
        json: async () => ({ detail: { message: 'retrieval-api unavailable' } }),
      }),
    );

    await expect(apiFetchJson('/api/v1/capabilities')).rejects.toThrow('retrieval-api unavailable');

    expect(logErrorSpy).toHaveBeenCalledWith(
      'api.request_failed',
      expect.objectContaining({
        requestId: 'req-fixed',
        method: 'GET',
        status: 503,
        url: '/api/v1/capabilities',
      }),
    );
  });

  it('retries transient GET failures and only logs after the final attempt', async () => {
    vi.useFakeTimers();
    let attempts = 0;
    globalThis.fetch = vi.fn(() => {
      attempts += 1;
      if (attempts < 3) {
        return Promise.resolve({
          ok: false,
          status: 503,
          json: async () => ({ detail: { message: 'backend warming up' } }),
        });
      }
      return Promise.resolve({ ok: true, json: async () => ({ ok: true }) });
    });

    try {
      const request = apiFetchJson('/api/v1/capabilities', { retryTransient: true });
      await vi.advanceTimersByTimeAsync(250);
      await vi.advanceTimersByTimeAsync(500);
      await expect(request).resolves.toEqual({ ok: true });
      expect(globalThis.fetch).toHaveBeenCalledTimes(3);
      expect(logErrorSpy).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it('does not retry a request-size client error', async () => {
    globalThis.fetch = vi.fn(() => Promise.resolve({
      ok: false,
      status: 431,
      json: async () => null,
    }));

    await expect(
      apiFetchJson('/api/v1/job-intelligence/governance/job-taxonomy/review-items', {
        retryTransient: true,
      }),
    ).rejects.toMatchObject({ status: 431 });
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
  });

  it('reuses a caller supplied request id for headers and failure logs', async () => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve({
        ok: false,
        status: 503,
        json: async () => ({ detail: { message: 'retrieval-api unavailable' } }),
      }),
    );

    await expect(
      apiFetchJson('/api/v1/capabilities', {
        headers: {
          'X-Request-ID': 'req-caller',
        },
      }),
    ).rejects.toThrow('retrieval-api unavailable');

    const headers = globalThis.fetch.mock.calls[0][1].headers;
    expect(headers.get('X-Request-ID')).toBe('req-caller');
    expect(logErrorSpy).toHaveBeenCalledWith(
      'api.request_failed',
      expect.objectContaining({
        requestId: 'req-caller',
      }),
    );
  });

  it('extracts backend detail messages from failed JSON responses', async () => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve({
        ok: false,
        status: 503,
        json: async () => ({ detail: { message: 'retrieval-api unavailable' } }),
      }),
    );

    await expect(apiFetchJson('/api/v1/capabilities')).rejects.toThrow('retrieval-api unavailable');
  });

  it('preserves stable conflict metadata for governance reload handling', async () => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve({
        ok: false,
        status: 409,
        json: async () => ({
          detail: {
            code: 'GOVERNANCE_DECISION_STALE_VERSION',
            message: 'The review item changed',
          },
        }),
      }),
    );

    const error = await apiFetchJson('/api/v1/job-intelligence/review').catch(
      (caught) => caught,
    );

    expect(error).toMatchObject({
      name: 'ApiRequestError',
      message: 'The review item changed',
      status: 409,
      code: 'GOVERNANCE_DECISION_STALE_VERSION',
      details: {
        code: 'GOVERNANCE_DECISION_STALE_VERSION',
        message: 'The review item changed',
      },
      detail: {
        code: 'GOVERNANCE_DECISION_STALE_VERSION',
        message: 'The review item changed',
      },
      requestId: 'req-fixed',
    });
  });

  it('retains structured details and the server request id without breaking detail', async () => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve({
        ok: false,
        status: 409,
        headers: new Headers({ 'X-Request-ID': 'req-server' }),
        json: async () => ({
          code: 'CATALOG_IMPACT_STALE',
          message: 'Impact changed',
          details: { candidateId: 'candidate-1' },
        }),
      }),
    );

    const error = await apiFetchJson('/api/v1/source-catalogs/jobsdb').catch(
      (caught) => caught,
    );

    expect(error).toMatchObject({
      name: 'ApiRequestError',
      message: 'Impact changed',
      code: 'CATALOG_IMPACT_STALE',
      details: { candidateId: 'candidate-1' },
      requestId: 'req-server',
    });
    expect(logErrorSpy).toHaveBeenCalledWith(
      'api.request_failed',
      expect.objectContaining({ requestId: 'req-server' }),
    );
  });

  it('formats array details into readable messages', () => {
    expect(formatApiErrorDetail([{ msg: 'field required' }, { message: 'bad source' }])).toBe(
      'field required; bad source',
    );
  });

  it('keeps timeout abort behavior when the caller provides an abort signal', async () => {
    vi.useFakeTimers();
    const callerController = new AbortController();
    let requestSignal = null;
    let request;

    try {
      globalThis.fetch = vi.fn((_url, init) => {
        requestSignal = init.signal;

        return new Promise((_resolve, reject) => {
          init.signal.addEventListener('abort', () => {
            reject(new Error('request aborted'));
          });
        });
      });

      request = apiFetchJson('/api/v1/capabilities', {
        signal: callerController.signal,
        timeoutMs: 25,
      });
      const requestRejection = request.catch((error) => error);

      await vi.advanceTimersByTimeAsync(25);

      expect(requestSignal.aborted).toBe(true);
      expect((await requestRejection).message).toBe('request aborted');
    } finally {
      request?.catch(() => {});
      vi.useRealTimers();
    }
  });

  it('does not log caller-cancelled requests as application failures', async () => {
    const callerController = new AbortController();
    globalThis.fetch = vi.fn(() => {
      callerController.abort();
      return Promise.reject(new DOMException('The operation was aborted.', 'AbortError'));
    });

    await expect(
      apiFetchJson('/api/v1/capabilities', { signal: callerController.signal }),
    ).rejects.toMatchObject({ name: 'AbortError' });
    expect(logErrorSpy).not.toHaveBeenCalled();
  });

});
