import { API_BASE_URL } from './base';
import { apiFetchJson } from './client';

export function fetchCapabilities() {
  return apiFetchJson(`${API_BASE_URL}/api/v1/capabilities`, { timeoutMs: 8000 });
}
