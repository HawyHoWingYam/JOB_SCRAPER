export function parseSettingsRoute(hash = window.location.hash, fallback = 'ai-runtime') {
  const [path, query] = hash.replace(/^#/, '').split('?', 2);
  const params = new URLSearchParams(path === 'settings' ? query : '');
  const section = params.get('section') || fallback;
  const returnRun = params.get('returnRun');
  return {
    section: section === 'scraper-pacing' ? section : 'ai-runtime',
    profile: ['jobs', 'companies', 'jev', 'throughput'].includes(params.get('profile')) ? params.get('profile') : null,
    returnToAI: params.get('return') === 'ai',
    returnRun: returnRun && returnRun.length <= 255 ? returnRun : null,
  };
}

export function buildSettingsRoute({ section = 'ai-runtime', profile, returnToAI, returnRun } = {}) {
  const params = new URLSearchParams({ section });
  if (profile) params.set('profile', profile);
  if (returnToAI) params.set('return', 'ai');
  if (returnToAI && returnRun) params.set('returnRun', returnRun);
  return `#settings?${params}`;
}
