import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  APP_MONITOR_PREFIX,
  createMonitoringId,
  registerGlobalMonitoringHandlers,
} from './monitoring';

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
    const unregister = registerGlobalMonitoringHandlers();

    window.dispatchEvent(new ErrorEvent('error', { message: 'boom', error: new Error('boom') }));
    const rejectionEvent = new Event('unhandledrejection');
    Object.defineProperty(rejectionEvent, 'reason', { value: new Error('denied') });
    window.dispatchEvent(rejectionEvent);

    expect(console.error).toHaveBeenCalledWith(
      `${APP_MONITOR_PREFIX} window.error`,
      expect.objectContaining({ message: 'boom' }),
    );
    expect(console.error).toHaveBeenCalledWith(
      `${APP_MONITOR_PREFIX} window.unhandledrejection`,
      expect.objectContaining({ reason: 'Error: denied' }),
    );

    unregister();
  });
});
