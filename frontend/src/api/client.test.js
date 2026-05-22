import { describe, expect, it, vi } from 'vitest';

import { apiFetchJson, formatApiErrorDetail } from './client';
import { fetchOperatorHealth } from './operatorHealth';

describe('api client', () => {
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

  it('routes operator health requests through the shared JSON client with the operator endpoint', async () => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve({
        ok: true,
        json: async () => ({ status: 'ok' }),
      }),
    );

    const result = await fetchOperatorHealth({ method: 'POST', headers: { 'X-Test': '1' }, timeoutMs: 2000 });

    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/v1/operator/health',
      expect.objectContaining({
        method: 'POST',
        headers: { 'X-Test': '1' },
        signal: expect.any(AbortSignal),
      }),
    );
    expect(result).toEqual({ status: 'ok' });
  });

  it('applies the default operator health timeout when no override is provided', async () => {
    vi.useFakeTimers();
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

      request = fetchOperatorHealth();
      const requestRejection = request.catch((error) => error);

      await vi.advanceTimersByTimeAsync(14999);
      expect(requestSignal.aborted).toBe(false);

      await vi.advanceTimersByTimeAsync(1);
      expect(requestSignal.aborted).toBe(true);
      expect((await requestRejection).message).toBe('request aborted');
    } finally {
      request?.catch(() => {});
      vi.useRealTimers();
    }
  });
});
