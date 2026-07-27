import {
  OFFERTODAY_DEFAULT_PAGE_DEPTH,
  OFFERTODAY_DEFAULT_RUN_PAGE_CAP,
  offerTodayEstimatedMaxPages,
} from './wizardPolicy';

export const STEP_ORDER = ['intent', 'scope', 'execution', 'review'];

export function createWizardState(draft, notice = null) {
  return {
    draft,
    notice,
    classifications: { status: 'idle', value: null, error: null, requestVersion: 0 },
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

function resetClassifications(state) {
  return {
    status: 'idle',
    value: null,
    error: null,
    requestVersion: state.classifications.requestVersion + 1,
  };
}

export function wizardReducer(state, action) {
  switch (action.type) {
    case 'hydrate': {
      const nextState = createWizardState(action.draft, action.notice);
      return {
        ...nextState,
        classifications: state.draft.source_site === action.draft.source_site
          ? state.classifications
          : resetClassifications(state),
      };
    }
    case 'notice':
      return { ...state, notice: action.notice };
    case 'sourceChanged': {
      const nextState = invalidateAuthority(state, {
        ...state.draft,
        source_site: action.sourceSite,
        scope: null,
        execution: {},
        step: 'intent',
      });
      return { ...nextState, classifications: resetClassifications(state) };
    }
    case 'intentChanged':
      return invalidateAuthority(state, {
        ...state.draft,
        intent: action.intent,
        scope: null,
        execution: action.intent === 'listing'
          ? state.draft.source_site === 'offertoday'
            ? {
              page_depth: OFFERTODAY_DEFAULT_PAGE_DEPTH,
              run_page_cap: OFFERTODAY_DEFAULT_RUN_PAGE_CAP,
              crawl_mode: 'headless',
            }
            : { page_depth: 1, run_page_cap: 100, crawl_mode: 'headless' }
          : { backlog_kind: 'crawl_scope', limit_kind: 'stop_after', detail_run_cap: 100, crawl_mode: 'headless' },
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
    case 'classificationsStarted':
      return { ...state, classifications: { ...state.classifications, status: 'loading', error: null, requestVersion: action.version } };
    case 'classificationsSucceeded':
      if (action.version !== state.classifications.requestVersion) return state;
      return { ...state, classifications: { ...state.classifications, status: 'success', value: action.value, error: null } };
    case 'classificationsFailed':
      if (action.version !== state.classifications.requestVersion) return state;
      return { ...state, classifications: { ...state.classifications, status: 'error', error: action.error } };
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
  if (step === 'scope') {
    if (draft.source_site === 'offertoday') {
      return draft.scope?.mode === 'selected'
        && draft.scope.classification_ids?.length === 1;
    }
    return draft.scope?.mode === 'all'
      || (draft.scope?.mode === 'selected' && draft.scope.classification_ids?.length > 0);
  }
  if (step === 'execution') {
    if (draft.intent === 'listing') {
      const pageDepth = Number(draft.execution.page_depth);
      const runPageCap = Number(draft.execution.run_page_cap);
      return Number.isSafeInteger(pageDepth)
        && Number.isSafeInteger(runPageCap)
        && pageDepth > 0
        && runPageCap > 0
        && (
          draft.source_site !== 'offertoday'
          || (
            offerTodayEstimatedMaxPages(pageDepth) !== null
            && runPageCap >= offerTodayEstimatedMaxPages(pageDepth)
          )
        );
    }
    if (!draft.execution.backlog_kind || !draft.execution.limit_kind) return false;
    if (draft.execution.backlog_kind === 'listing_batch' && !draft.execution.source_listing_crawl_job_id) return false;
    return draft.execution.limit_kind === 'entire_snapshot' || Number(draft.execution.detail_run_cap) > 0;
  }
  return true;
}
