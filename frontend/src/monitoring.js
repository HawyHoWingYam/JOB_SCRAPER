export const APP_MONITOR_PREFIX = 'APP_MONITOR';

function stringifyField(value) {
  if (value instanceof Error) {
    return `${value.name}: ${value.message}`;
  }
  if (typeof value === 'string') {
    return value;
  }
  if (value == null) {
    return value;
  }

  try {
    return JSON.parse(JSON.stringify(value));
  } catch {
    return String(value);
  }
}

function emit(level, event, fields = {}) {
  const logger = level === 'error' ? console.error : level === 'warn' ? console.warn : console.info;
  const normalized = Object.fromEntries(
    Object.entries(fields).map(([key, value]) => [key, stringifyField(value)]),
  );

  logger(`${APP_MONITOR_PREFIX} ${event}`, normalized);
}

export function createMonitoringId(prefix = 'req') {
  if (globalThis.crypto && typeof globalThis.crypto.randomUUID === 'function') {
    return `${prefix}-${globalThis.crypto.randomUUID()}`;
  }

  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

export function logInfo(event, fields = {}) {
  emit('info', event, fields);
}

export function logWarn(event, fields = {}) {
  emit('warn', event, fields);
}

export function logError(event, fields = {}) {
  emit('error', event, fields);
}

export function registerGlobalMonitoringHandlers() {
  const handleWindowError = (event) => {
    logError('window.error', {
      message: event.message,
      filename: event.filename,
      lineno: event.lineno,
      colno: event.colno,
      error: event.error,
    });
  };

  const handleUnhandledRejection = (event) => {
    logError('window.unhandledrejection', {
      reason: event.reason,
    });
  };

  window.addEventListener('error', handleWindowError);
  window.addEventListener('unhandledrejection', handleUnhandledRejection);

  return () => {
    window.removeEventListener('error', handleWindowError);
    window.removeEventListener('unhandledrejection', handleUnhandledRejection);
  };
}
