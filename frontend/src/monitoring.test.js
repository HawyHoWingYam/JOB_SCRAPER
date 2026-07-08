import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  APP_MONITOR_PREFIX,
  createMonitoringId,
  registerGlobalMonitoringHandlers,
} from './monitoring';

function dispatchWindowError(message) {
  const errorEvent = new Event('error');
  Object.defineProperties(errorEvent, {
    message: { value: message },
    error: { value: null },
    filename: { value: '' },
    lineno: { value: 0 },
    colno: { value: 0 },
  });

  window.dispatchEvent(errorEvent);
}

describe('monitoring helpers', () => {
  beforeEach(() => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('creates stable prefixed monitoring ids', () => {
    expect(createMonitoringId('req')).toMatch(/^req-/);
    expect(createMonitoringId('stream')).toMatch(/^stream-/);
  });

  it('registers global handlers and logs browser errors and rejections', () => {
    const boomError = new Error('boom');
    boomError.stack = 'Error: boom\n    at boom-stack';
    const deniedError = new Error('denied');
    deniedError.stack = 'Error: denied\n    at denied-stack';
    const unregister = registerGlobalMonitoringHandlers();

    window.dispatchEvent(new ErrorEvent('error', { message: 'boom', error: boomError }));
    const rejectionEvent = new Event('unhandledrejection');
    Object.defineProperty(rejectionEvent, 'reason', { value: deniedError });
    window.dispatchEvent(rejectionEvent);

    expect(console.error).toHaveBeenCalledWith(
      `${APP_MONITOR_PREFIX} window.error`,
      expect.objectContaining({ message: 'boom', error: boomError.stack }),
    );
    expect(console.error).toHaveBeenCalledWith(
      `${APP_MONITOR_PREFIX} window.unhandledrejection`,
      expect.objectContaining({ reason: deniedError.stack }),
    );

    unregister();
  });

  it('registers global handlers idempotently', () => {
    const firstUnregister = registerGlobalMonitoringHandlers();
    const secondUnregister = registerGlobalMonitoringHandlers();

    dispatchWindowError('first');
    expect(console.error).toHaveBeenCalledTimes(1);

    firstUnregister();

    dispatchWindowError('second');
    expect(console.error).toHaveBeenCalledTimes(2);

    secondUnregister();

    dispatchWindowError('third');
    expect(console.error).toHaveBeenCalledTimes(2);
  });
});
