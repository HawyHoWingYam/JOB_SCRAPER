import { apiFetchJson } from './client';

export function fetchOperatorHealth(options = {}) {
  return apiFetchJson('/api/v1/operator/health', { timeoutMs: 15000, ...options });
}
