import { describe, expect, it, vi } from 'vitest';

import { apiFetchJson, formatApiErrorDetail } from './client';

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
});
