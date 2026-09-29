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

    await apiFetchJson('/api/capabilities');

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

    await expect(apiFetchJson('/api/capabilities')).rejects.toThrow('retrieval-api unavailable');

    expect(logErrorSpy).toHaveBeenCalledWith(
      'api.request_failed',
      expect.objectContaining({
        requestId: 'req-fixed',
        method: 'GET',
        status: 503,
        url: '/api/capabilities',
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
      const request = apiFetchJson('/api/capabilities', { retryTransient: true });
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
      apiFetchJson('/api/job-intelligence/skills/tree', {
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
      apiFetchJson('/api/capabilities', {
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

    await expect(apiFetchJson('/api/capabilities')).rejects.toThrow('retrieval-api unavailable');
  });

  it('preserves structured conflict metadata', async () => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve({
        ok: false,
        status: 409,
        json: async () => ({
          detail: {
            code: 'SOURCE_CLASSIFICATION_SYNC_CONFLICT',
            message: 'The classification changed',
          },
        }),
      }),
    );

    const error = await apiFetchJson('/api/source-classifications/jobsdb').catch(
      (caught) => caught,
    );

    expect(error).toMatchObject({
      name: 'ApiRequestError',
      message: 'The classification changed',
      status: 409,
      code: 'SOURCE_CLASSIFICATION_SYNC_CONFLICT',
      details: {
        code: 'SOURCE_CLASSIFICATION_SYNC_CONFLICT',
        message: 'The classification changed',
      },
      detail: {
        code: 'SOURCE_CLASSIFICATION_SYNC_CONFLICT',
        message: 'The classification changed',
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
          code: 'SOURCE_CLASSIFICATION_UNKNOWN',
          message: 'Classification does not exist',
          details: { classificationId: 'jobsdb:missing' },
        }),
      }),
    );

    const error = await apiFetchJson('/api/source-classifications/jobsdb').catch(
      (caught) => caught,
    );

    expect(error).toMatchObject({
      name: 'ApiRequestError',
      message: 'Classification does not exist',
      code: 'SOURCE_CLASSIFICATION_UNKNOWN',
      details: { classificationId: 'jobsdb:missing' },
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

      request = apiFetchJson('/api/capabilities', {
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
      apiFetchJson('/api/capabilities', { signal: callerController.signal }),
    ).rejects.toMatchObject({ name: 'AbortError' });
    expect(logErrorSpy).not.toHaveBeenCalled();
  });

  it('reports an internal request timeout instead of the browser abort reason', async () => {
    vi.useFakeTimers();
    try {
      globalThis.fetch = vi.fn((_url, init) => new Promise((_resolve, reject) => {
        init.signal.addEventListener('abort', () => {
          reject(new DOMException('signal is aborted without reason', 'AbortError'));
        });
      }));

      const request = apiFetchJson('/api/ai/runs/run-1/retry-failed', {
        method: 'POST',
        timeoutMs: 25,
      });
      const rejection = request.catch((error) => error);
      await vi.advanceTimersByTimeAsync(25);

      await expect(rejection).resolves.toMatchObject({
        name: 'ApiRequestError',
        message: 'Request timed out after 25 ms',
        code: 'REQUEST_TIMEOUT',
      });
      expect(logErrorSpy).toHaveBeenCalledWith(
        'api.request_failed',
        expect.objectContaining({ detail: 'Request timed out after 25 ms' }),
      );
    } finally {
      vi.useRealTimers();
    }
  });

  it('supports requests governed by a server-side timeout only', async () => {
    vi.useFakeTimers();
    let requestSignal;
    try {
      globalThis.fetch = vi.fn((_url, init) => {
        requestSignal = init.signal;
        return new Promise(() => {});
      });

      apiFetchJson('/api/ai/runs/run-1/retry-failed', {
        method: 'POST',
        timeoutMs: null,
      });
      await vi.advanceTimersByTimeAsync(700_000);

      expect(requestSignal).toBeUndefined();
      expect(logErrorSpy).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

});
