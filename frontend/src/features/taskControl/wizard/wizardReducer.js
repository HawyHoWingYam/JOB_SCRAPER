export const STEP_ORDER = ['intent', 'scope', 'execution', 'review'];

export function createWizardState(draft, notice = null) {
  return {
    draft,
    notice,
    catalog: { status: 'idle', value: null, error: null, requestVersion: 0 },
    automation: { status: 'idle', value: null, error: null },
    review: { status: 'idle', value: null, draftFingerprint: null, error: null },
    plan: { status: 'idle', value: null, draftFingerprint: null, error: null },
    mutation: { status: 'idle', kind: null, error: null },
    conflict: null,
    result: null,
    dialog: null,
  };
}

function invalidateAuthority(state, draft) {
  return {
    ...state,
    draft,
    review: { status: 'idle', value: null, draftFingerprint: null, error: null },
    plan: { status: 'idle', value: null, draftFingerprint: null, error: null },
    conflict: null,
    result: null,
  };
}

export function wizardReducer(state, action) {
  switch (action.type) {
    case 'hydrate':
      return createWizardState(action.draft, action.notice);
    case 'notice':
      return { ...state, notice: action.notice };
    case 'sourceChanged':
      return invalidateAuthority(state, {
        ...state.draft,
        source_site: action.sourceSite,
        scope: null,
        execution: {},
        step: 'intent',
      });
    case 'intentChanged':
      return invalidateAuthority(state, {
        ...state.draft,
        intent: action.intent,
        scope: null,
        execution: action.intent === 'listing'
          ? { page_depth: 1, run_page_cap: 100, crawl_mode: state.draft.source_site === 'ctgoodjobs' ? 'headed' : 'headless' }
          : { backlog_kind: 'crawl_scope', limit_kind: 'stop_after', detail_run_cap: 100, crawl_mode: state.draft.source_site === 'ctgoodjobs' ? 'headed' : 'headless' },
      });
    case 'scopeChanged':
      return invalidateAuthority(state, { ...state.draft, scope: action.scope });
    case 'executionChanged':
      return invalidateAuthority(state, { ...state.draft, execution: { ...state.draft.execution, ...action.value } });
    case 'scheduleChanged':
      return invalidateAuthority(state, { ...state.draft, schedule: { ...state.draft.schedule, ...action.value } });
    case 'runChoiceChanged':
      return { ...state, draft: { ...state.draft, run_choice: action.value } };
    case 'stepChanged':
      return { ...state, draft: { ...state.draft, step: action.step } };
    case 'catalogStarted':
      return { ...state, catalog: { ...state.catalog, status: 'loading', error: null, requestVersion: action.version } };
    case 'catalogSucceeded':
      if (action.version !== state.catalog.requestVersion) return state;
      return { ...state, catalog: { ...state.catalog, status: 'success', value: action.value, error: null } };
    case 'catalogFailed':
      if (action.version !== state.catalog.requestVersion) return state;
      return { ...state, catalog: { ...state.catalog, status: 'error', error: action.error } };
    case 'automationStarted':
      return { ...state, automation: { status: 'loading', value: null, error: null } };
    case 'automationSucceeded':
      return { ...state, automation: { status: 'success', value: action.value, error: null }, draft: action.draft || state.draft };
    case 'automationFailed':
      return { ...state, automation: { ...state.automation, status: 'error', error: action.error } };
    case 'authorityStarted':
      return { ...state, [action.kind]: { status: 'loading', value: null, draftFingerprint: action.draftFingerprint, error: null }, mutation: { status: 'idle', kind: null, error: null }, result: null };
    case 'authoritySucceeded':
      return { ...state, [action.kind]: { status: 'success', value: action.value, draftFingerprint: action.draftFingerprint, error: null }, conflict: action.conflict || null };
    case 'authorityFailed':
      return { ...state, [action.kind]: { status: 'error', value: null, draftFingerprint: action.draftFingerprint, error: action.error } };
    case 'mutationStarted':
      if (state.mutation.status === 'loading') return state;
      return { ...state, mutation: { status: 'loading', kind: action.kind, error: null } };
    case 'mutationSucceeded':
      return { ...state, mutation: { status: 'success', kind: action.kind, error: null }, result: action.result };
    case 'mutationFailed':
      return { ...state, mutation: { status: 'error', kind: action.kind, error: action.error } };
    case 'dialogOpened':
      return { ...state, dialog: action.dialog };
    case 'dialogClosed':
      return { ...state, dialog: null };
    case 'conflictStatus':
      return { ...state, conflict: state.conflict ? { ...state.conflict, status: action.status, error: action.error || null } : null };
    default:
      return state;
  }
}

export function isStepComplete(draft, step = draft.step) {
  if (step === 'intent') return Boolean(draft.intent);
  if (step === 'scope') return draft.scope?.mode === 'all' || (draft.scope?.mode === 'rules' && draft.scope.rules?.length > 0);
  if (step === 'execution') {
    if (draft.intent === 'listing') {
      return Number(draft.execution.page_depth) > 0 && Number(draft.execution.run_page_cap) > 0;
    }
    if (!draft.execution.backlog_kind || !draft.execution.limit_kind) return false;
    if (draft.execution.backlog_kind === 'listing_batch' && !draft.execution.source_listing_crawl_job_id) return false;
    return draft.execution.limit_kind === 'entire_snapshot' || Number(draft.execution.detail_run_cap) > 0;
  }
  return true;
}
