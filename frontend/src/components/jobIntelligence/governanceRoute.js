import { GOVERNANCE_AREAS } from '../../api/jobIntelligence';

const DEFAULT_AREA = GOVERNANCE_AREAS[0].key;
const AREA_KEYS = new Set(GOVERNANCE_AREAS.map((area) => area.key));

export function parseGovernanceHash(hash = window.location.hash) {
  const raw = String(hash || '').replace(/^#/, '');
  const [path, query = ''] = raw.split('?');
  const segments = path.split('/').filter(Boolean);
  const isGovernanceRoute = segments.length === 2 && segments[0] === 'job-intelligence';
  if (!isGovernanceRoute) {
    return { area: DEFAULT_AREA, itemId: null };
  }
  const area = AREA_KEYS.has(segments[1]) ? segments[1] : DEFAULT_AREA;
  const params = new URLSearchParams(query);
  const queueQuery = params.get('q');
  const cursor = params.get('cursor');
  return {
    area,
    itemId: params.get('item'),
    ...(queueQuery ? { query: queueQuery } : {}),
    ...(cursor ? { cursor } : {}),
  };
}

export function governanceHash(area, itemId = null, filters = {}) {
  const safeArea = AREA_KEYS.has(area) ? area : DEFAULT_AREA;
  const params = new URLSearchParams();
  if (itemId) params.set('item', itemId);
  if (filters.query) params.set('q', filters.query);
  if (filters.cursor) params.set('cursor', filters.cursor);
  const query = params.toString();
  return `#job-intelligence/${safeArea}${query ? `?${query}` : ''}`;
}

export function navigateGovernance(area, itemId = null, filters = {}) {
  const nextHash = governanceHash(area, itemId, filters);
  if (window.location.hash === nextHash) {
    window.dispatchEvent(new HashChangeEvent('hashchange'));
    return;
  }
  window.location.hash = nextHash;
}
