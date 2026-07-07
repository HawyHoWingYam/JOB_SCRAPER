import { apiPath } from './base';
import { apiFetchJson } from './client';

export function fetchCapabilities() {
  return apiFetchJson(apiPath('/capabilities'), { timeoutMs: 8000 });
}
