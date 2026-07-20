const SOURCES = new Set(['jobsdb', 'ctgoodjobs', 'offertoday']);
const STEPS = new Set(['intent', 'scope', 'execution', 'review']);
const INTENTS = new Set(['listing', 'detail']);

export const DRAFT_PREFIX = 'taskControl.draft.v1.';

export function createWizardDraft(route, sourceSite = route.sourceSite || 'jobsdb') {
  return {
    version: 1,
    updated_at: new Date().toISOString(),
    flow: route.flow,
    mode: route.mode,
    automation_id: route.automationId || null,
    expected_revision: null,
    source_site: SOURCES.has(sourceSite) ? sourceSite : 'jobsdb',
    step: route.flow === 'run_now' ? 'review' : 'intent',
    run_choice: route.flow === 'run_now' ? 'saved' : null,
    intent: null,
    scope: null,
    execution: {},
    schedule: {
      name: '',
      description: '',
      cron_expression: '0 4 * * *',
      timezone: 'Asia/Hong_Kong',
      initial_state: 'paused',
    },
  };
}

function validDraft(value, route) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  if (value.version !== 1 || value.flow !== route.flow || value.mode !== route.mode) return false;
  if (!SOURCES.has(value.source_site) || !STEPS.has(value.step)) return false;
  if (value.intent !== null && !INTENTS.has(value.intent)) return false;
  if (value.automation_id !== (route.automationId || null)) return false;
  if (route.sourceSite && value.source_site !== route.sourceSite) return false;
  if (!value.updated_at || Number.isNaN(new Date(value.updated_at).valueOf())) return false;
  if (!value.execution || typeof value.execution !== 'object' || Array.isArray(value.execution)) return false;
  if (!value.schedule || typeof value.schedule !== 'object' || Array.isArray(value.schedule)) return false;
  return true;
}

export function readDraft(storage, draftId, route) {
  const clean = createWizardDraft(route);
  if (!draftId) return { draft: clean, notice: 'A new recoverable draft was created.' };
  try {
    const raw = storage?.getItem(`${DRAFT_PREFIX}${draftId}`);
    if (!raw) return { draft: clean, notice: null };
    const value = JSON.parse(raw);
    if (!validDraft(value, route)) {
      return { draft: clean, notice: 'The saved draft was malformed, outdated, or belonged to another route. A clean draft is open.' };
    }
    return { draft: value, notice: null };
  } catch (error) {
    return { draft: clean, notice: `Draft storage is unavailable; work continues in memory (${error.name || 'storage error'}).` };
  }
}

export function writeDraft(storage, draftId, draft) {
  if (!draftId) return { ok: false, notice: 'Draft ID is unavailable; work continues in memory.' };
  try {
    const value = { ...draft, version: 1, updated_at: new Date().toISOString() };
    storage?.setItem(`${DRAFT_PREFIX}${draftId}`, JSON.stringify(value));
    return { ok: true, notice: null, draft: value };
  } catch (error) {
    return { ok: false, notice: `Draft could not be saved; work continues in memory (${error.name || 'storage error'}).` };
  }
}

export function clearDraft(storage, draftId) {
  try {
    if (draftId) storage?.removeItem(`${DRAFT_PREFIX}${draftId}`);
    return { ok: true, notice: null };
  } catch (error) {
    return { ok: false, notice: `Draft could not be cleared (${error.name || 'storage error'}).` };
  }
}

export function hasMeaningfulDraft(draft) {
  return Boolean(
    draft.intent ||
    draft.scope ||
    Object.keys(draft.execution || {}).length ||
    draft.schedule?.name,
  );
}
