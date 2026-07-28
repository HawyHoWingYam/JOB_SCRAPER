import { normalizeScopeForSubmit } from './jobBrowserScopeUtils';


export const JOB_BROWSER_SESSION_KEY = 'job-browser-applied-scope:v1';
const SESSION_VERSION = 1;


export function writeJobBrowserSession(storage, scope) {
  if (!storage) return;
  const normalizedScope = normalizeScopeForSubmit(scope);
  if (normalizedScope.layers.length === 0) {
    storage.removeItem(JOB_BROWSER_SESSION_KEY);
    return;
  }
  storage.setItem(JOB_BROWSER_SESSION_KEY, JSON.stringify({
    version: SESSION_VERSION,
    scope: normalizedScope,
  }));
}


export function readJobBrowserSession(storage) {
  if (!storage) return null;
  try {
    const raw = storage.getItem(JOB_BROWSER_SESSION_KEY);
    if (!raw) return null;
    const payload = JSON.parse(raw);
    if (payload?.version !== SESSION_VERSION || !Array.isArray(payload?.scope?.layers)) {
      return null;
    }
    return normalizeScopeForSubmit(payload.scope);
  } catch {
    return null;
  }
}


export function clearJobBrowserSession(storage) {
  storage?.removeItem(JOB_BROWSER_SESSION_KEY);
}
