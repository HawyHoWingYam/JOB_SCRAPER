const ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;
const WIZARD_STEPS = new Set(['intent', 'scope', 'execution', 'review']);

function query(raw) {
  const [, value = ''] = raw.split('?', 2);
  return new URLSearchParams(value);
}

function safeId(value) {
  const decoded = decodeURIComponent(value || '');
  return ID_PATTERN.test(decoded) ? decoded : null;
}

export function parseControlRoute(hash = window.location.hash) {
  const raw = String(hash || '').replace(/^#/, '');
  const [path] = raw.split('?', 1);
  const parts = path.split('/').filter(Boolean);
  if (parts[0] !== 'scheduler') return { kind: 'invalid', notice: 'Unsupported Task Control route.' };
  const params = query(raw);
  const boardSource = params.get('source')?.toLowerCase() || 'jobsdb';
  if (parts.length === 1) {
    return {
      kind: 'board',
      sourceSite: ['jobsdb', 'ctgoodjobs', 'offertoday'].includes(boardSource) ? boardSource : 'jobsdb',
    };
  }
  const draftId = safeId(params.get('draft'));
  const sourceSite = params.get('source')?.toLowerCase() || null;
  const step = WIZARD_STEPS.has(params.get('step')) ? params.get('step') : null;
  if (parts[1] === 'automation' && parts[2] === 'new' && parts.length === 3) {
    return { kind: 'wizard', flow: 'automation', mode: 'create', automationId: null, draftId, sourceSite, step };
  }
  if (parts[1] === 'automation' && parts[3] === 'edit' && parts.length === 4) {
    const automationId = safeId(parts[2]);
    return automationId
      ? { kind: 'wizard', flow: 'automation', mode: 'edit', automationId, draftId, sourceSite, step }
      : { kind: 'invalid', notice: 'Invalid Automation ID.' };
  }
  if (parts[1] === 'one-off' && parts[2] === 'new' && parts.length === 3) {
    return { kind: 'wizard', flow: 'one_off', mode: 'create', automationId: null, draftId, sourceSite, step };
  }
  if (parts[1] === 'run' && parts[3] === 'review' && parts.length === 4) {
    const automationId = safeId(parts[2]);
    return automationId
      ? { kind: 'wizard', flow: 'run_now', mode: 'review', automationId, draftId, sourceSite, step }
      : { kind: 'invalid', notice: 'Invalid Run-now Automation ID.' };
  }
  return { kind: 'invalid', notice: 'Unsupported Task Control route.' };
}

function params(sourceSite, draftId, step) {
  const value = new URLSearchParams();
  if (sourceSite) value.set('source', sourceSite);
  if (draftId) value.set('draft', draftId);
  if (WIZARD_STEPS.has(step)) value.set('step', step);
  const encoded = value.toString();
  return encoded ? `?${encoded}` : '';
}

export function buildControlRoute({ flow, mode, automationId, sourceSite, draftId, step }) {
  if (!flow) return sourceSite ? `#scheduler?source=${encodeURIComponent(sourceSite)}` : '#scheduler';
  if (flow === 'automation' && mode === 'create') {
    return `#scheduler/automation/new${params(sourceSite, draftId, step)}`;
  }
  if (flow === 'automation' && mode === 'edit' && safeId(automationId)) {
    return `#scheduler/automation/${encodeURIComponent(automationId)}/edit${params(sourceSite, draftId, step)}`;
  }
  if (flow === 'one_off') {
    return `#scheduler/one-off/new${params(sourceSite, draftId, step)}`;
  }
  if (flow === 'run_now' && safeId(automationId)) {
    return `#scheduler/run/${encodeURIComponent(automationId)}/review${params(sourceSite, draftId, step)}`;
  }
  throw new Error('Cannot build unsupported Task Control route');
}

export function newDraftId() {
  return globalThis.crypto?.randomUUID?.() || `draft-${Date.now().toString(36)}`;
}
