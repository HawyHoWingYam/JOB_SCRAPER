import React, { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import {
  cancelCrawlJob,
  controlError,
  createAutomation,
  dispatchPlan,
  getAutomation,
  getCrawlJob,
  getSourceClassifications,
  prepareDispatchPlan,
  reviewAutomation,
  updateAutomation,
} from '../shared/controlApi';
import {
  buildControlRoute,
  newDraftId,
  parseControlRoute,
} from '../shared/controlRoute';
import { DEFAULT_TIMEZONE, formatControlDateTime, schedulePresetSummary } from '../shared/controlTime';
import ConfirmActionDialog from '../shared/ConfirmActionDialog';
import {
  clearDraft,
  createWizardDraft,
  hasMeaningfulDraft,
  readDraft,
  writeDraft,
} from './wizardDraft';
import {
  buildAutomationMutation,
  buildAutomationReviewRequest,
  buildOneOffRun,
  draftFromAutomation,
  pairedDetailDraft,
  wizardDraftFingerprint,
} from './wizardCommands';
import {
  createWizardState,
  isStepComplete,
  STEP_ORDER,
  wizardReducer,
} from './wizardReducer';
import SourceScopeTree from './SourceScopeTree';
import './TaskControlWizard.css';

const SOURCE_LABELS = { jobsdb: 'JobsDB', ctgoodjobs: 'CTgoodjobs', offertoday: 'OfferToday' };
const TERMINAL_RUN_STATUSES = new Set(['cancelled', 'completed', 'failed']);

function stepTitle(step) {
  return { intent: 'Choose task', scope: 'Choose scope', execution: 'Configure run', review: 'Review and confirm' }[step];
}

function IntentStep({ draft, dispatch, route, onRunWithChanges }) {
  if (route.flow === 'run_now') {
    return (
      <section className="control-subpanel">
        <h3>Run saved configuration</h3>
        <p>Review one run using this Automation’s saved settings. Its recurring schedule stays unchanged.</p>
        <button type="button" onClick={onRunWithChanges}>Run with changes</button>
        <p>To change settings for this run only, open a separate One-off draft.</p>
      </section>
    );
  }
  const automationFlow = route.flow === 'automation';
  return (
    <div className="intent-grid">
      <button type="button" className="intent-card" aria-pressed={draft.intent === 'listing'} onClick={() => dispatch({ type: 'intentChanged', intent: 'listing' })}>
        <strong>{automationFlow ? 'Discover listings' : 'Discover listings now'}</strong>
        <span>{automationFlow ? 'Schedule source listing discovery.' : 'Prepare one reviewed listing run now.'}</span>
      </button>
      <button type="button" className="intent-card" aria-pressed={draft.intent === 'detail'} onClick={() => dispatch({ type: 'intentChanged', intent: 'detail' })}>
        <strong>Fetch job details</strong>
        <span>Collect full descriptions for jobs already discovered. Choose which pending details to fetch next.</span>
      </button>
    </div>
  );
}

function ExecutionStep({ draft, dispatch, onEditScope }) {
  const setExecution = (value) => dispatch({ type: 'executionChanged', value });
  const setSchedule = (value) => dispatch({ type: 'scheduleChanged', value });
  const automationFlow = draft.flow === 'automation';
  const isOfferTodayListing = draft.source_site === 'offertoday' && draft.intent === 'listing';
  if (!draft.intent) return <p>Choose a task before configuring a run.</p>;
  return (
    <div className="execution-stack">
      {draft.intent === 'listing' ? (
        <section className="control-subpanel">
          <h3>Listing workload</h3>
          <div className="control-field-grid">
            <label className="control-field">Page Depth per Query Target<input type="number" min="1" max={isOfferTodayListing ? undefined : '1000'} value={draft.execution.page_depth || ''} onChange={(event) => setExecution({ page_depth: event.target.value })} /></label>
            <label className="control-field">Run Page Cap<input type="number" min="1" value={draft.execution.run_page_cap || ''} onChange={(event) => setExecution({ run_page_cap: event.target.value })} /></label>
          </div>
          {isOfferTodayListing ? (
            <p>Server review resolves the current root, active child categories, and enabled keyword pack. It shows the exact native, keyword, and total page maximum before dispatch.</p>
          ) : (
            <p>Server review resolves Query Target count and verifies <strong>targets × depth</strong> against the operator cap and system ceiling.</p>
          )}
        </section>
      ) : (
        <section className="control-subpanel">
          <h3>Which pending details should run?</h3>
          <div className="control-choice-row">
            {[['source_backlog', 'Entire source backlog'], ['crawl_scope', 'Chosen categories'], ['listing_batch', 'A specific listing run']].map(([value, label]) => <button key={value} type="button" aria-describedby={draft.scope?.mode !== 'all' && value !== 'crawl_scope' ? 'backlog-scope-help' : undefined} disabled={draft.scope?.mode !== 'all' && value !== 'crawl_scope'} aria-pressed={draft.execution.backlog_kind === value} onClick={() => setExecution({ backlog_kind: value })}>{label}</button>)}
          </div>
          {draft.scope?.mode !== 'all' && <p id="backlog-scope-help">Your scope is limited to chosen categories. The entire source backlog and a specific listing run require an all-category scope. {draft.source_site !== 'offertoday' && <button type="button" onClick={onEditScope}>Change scope</button>}</p>}
          {draft.execution.backlog_kind !== 'crawl_scope' && draft.scope?.mode !== 'all' && <p role="alert" className="control-error">This saved backlog choice does not match your scope. Choose Chosen categories{draft.source_site !== 'offertoday' ? ' or change the scope to All major categories' : ''} to continue.</p>}
          {draft.execution.backlog_kind === 'listing_batch' && <label className="control-field">Listing batch Crawl Job ID<input value={draft.execution.source_listing_crawl_job_id || ''} onChange={(event) => setExecution({ source_listing_crawl_job_id: event.target.value })} /></label>}
          <h3>{automationFlow ? 'Maximum details per future scheduled run' : 'How many details should run?'}</h3>
          <div className="control-choice-row">
            {!automationFlow && <button type="button" aria-pressed={draft.execution.limit_kind === 'entire_snapshot'} onClick={() => setExecution({ limit_kind: 'entire_snapshot' })}>Entire eligible snapshot</button>}
            <button type="button" aria-pressed={draft.execution.limit_kind === 'stop_after'} onClick={() => setExecution({ limit_kind: 'stop_after' })}>{automationFlow ? 'Maximum per scheduled run' : 'Stop after N'}</button>
          </div>
          {draft.execution.limit_kind === 'stop_after' && <label className="control-field">Detail Run Cap<input type="number" min="1" value={draft.execution.detail_run_cap || ''} onChange={(event) => setExecution({ detail_run_cap: event.target.value })} /></label>}
          <p>{automationFlow ? 'Eligible-now is a non-frozen estimate. Each due run freezes its own future snapshot.' : 'Review fixes the eligible jobs for this run. Jobs becoming eligible later are left for another run.'}</p>
        </section>
      )}

      <details className="control-subpanel">
        <summary>Advanced execution</summary>
        <label className="control-field">Crawl mode<select value={draft.execution.crawl_mode || 'headless'} onChange={(event) => setExecution({ crawl_mode: event.target.value })}><option value="headless">Headless</option><option value="headed">Headed</option></select></label>
        {draft.source_site === 'ctgoodjobs' && <p>Headless is supported for automatic runs. Choose headed only for explicit debugging or operator recovery.</p>}
      </details>

      {automationFlow && (
        <section className="control-subpanel">
          <h3>Automation schedule</h3>
          <div className="control-field-grid">
            <label className="control-field">Name<input value={draft.schedule.name || ''} onChange={(event) => setSchedule({ name: event.target.value })} /></label>
            <label className="control-field">Preset<select value={draft.schedule.cron_expression || '0 4 * * *'} onChange={(event) => setSchedule({ cron_expression: event.target.value })}><option value="0 * * * *">Every hour</option><option value="0 2 * * *">Daily 02:00</option><option value="0 4 * * *">Daily 04:00</option><option value="0 9 * * 1-5">Weekdays 09:00</option><option value="0 9 * * 1">Mondays 09:00</option></select></label>
          </div>
          <label className="control-field">Description<textarea value={draft.schedule.description || ''} onChange={(event) => setSchedule({ description: event.target.value })} /></label>
          <p>{schedulePresetSummary(draft.schedule.cron_expression, draft.schedule.timezone)}</p>
          <details><summary>Advanced cron and timezone</summary><div className="control-field-grid"><label className="control-field">Cron<input value={draft.schedule.cron_expression || ''} onChange={(event) => setSchedule({ cron_expression: event.target.value })} /></label><label className="control-field">IANA timezone<input value={draft.schedule.timezone || DEFAULT_TIMEZONE} onChange={(event) => setSchedule({ timezone: event.target.value })} /></label></div></details>
          {draft.mode !== 'edit' ? <label className="control-field">Initial state<select value={draft.schedule.initial_state || 'paused'} onChange={(event) => setSchedule({ initial_state: event.target.value })}><option value="paused">Paused</option><option value="active">Active</option></select></label> : <p>Saving changes preserves the current lifecycle state. Pause or resume this Automation from Scheduler.</p>}
        </section>
      )}
    </div>
  );
}

function ReviewProjection({ state, route }) {
  const review = state.review.value;
  const plan = state.plan.value;
  const offerTodayBreakdown = (resolvedScope, pageDepth) => {
    const targets = Array.isArray(resolvedScope?.query_targets)
      ? resolvedScope.query_targets
      : [];
    const keywordTargets = targets.filter(
      (target) => target?.parameters?.target_kind === 'keyword',
    ).length;
    const nativeTargets = targets.length - keywordTargets;
    return {
      nativeTargets,
      keywordTargets,
      nativePages: nativeTargets * pageDepth,
      keywordPages: keywordTargets * pageDepth,
    };
  };
  if (route.flow === 'automation' && review) {
    const workload = review.listingWorkload;
    const detail = review.detailPreview;
    return (
      <div className="review-stack">
        {review.before && <section className="control-subpanel"><h3>Edit before / after</h3><p>Before: {review.before.configuration.name}</p><p>After: {state.draft.schedule.name}</p></section>}
        <section className="control-subpanel"><h3>Work to schedule</h3><dl className="review-facts"><div><dt>Resolved Query Targets</dt><dd>{review.resolvedScope.query_target_count}</dd></div></dl></section>
        {workload && <section className="control-subpanel"><h3>Listing workload</h3><p>{workload.query_target_count} targets × {workload.page_depth} depth = <strong>{workload.estimated_max_pages}</strong> estimated maximum pages.</p>{state.draft.source_site === 'offertoday' && (() => { const counts = offerTodayBreakdown(review.resolvedScope, workload.page_depth); return <p>Native: {counts.nativeTargets} targets / {counts.nativePages} pages. Keywords: {counts.keywordTargets} targets / {counts.keywordPages} pages.</p>; })()}<p>Run Page Cap {workload.run_page_cap}; system ceiling {workload.system_run_page_cap}.</p></section>}
        {detail && <section className="control-subpanel"><h3>Detail preview (not frozen)</h3><p>{detail.eligible_now_count} eligible now; {detail.selected_now_count} would be selected by the current cap.</p><p>Future scheduled membership is frozen only when the Automation becomes due. Absolute safety cap: {detail.absolute_safety_cap}.</p></section>}
        <section className="control-subpanel"><h3>Schedule and readiness</h3><p>{review.scheduleSummary.human_summary}</p><p>Next scheduled time when active: {formatControlDateTime(review.scheduleSummary.next_run_at, review.scheduleSummary.timezone)}</p><p>Status: <strong>{review.readiness.status}</strong></p>{review.readiness.blockingErrors.map((error) => <p key={error.code} className="control-error">{error.code}: {error.message}</p>)}</section>
        <details className="control-subpanel"><summary>Review reference</summary><p>Fingerprint: {review.inputFingerprint}</p></details>
        {review.warnings.map((warning) => <p role="status" className="control-warning" key={warning.code}>{warning.code}: {warning.message}</p>)}
      </div>
    );
  }
  if (plan) {
    const listing = plan.content.listing_settings;
    const detail = plan.content.detail_settings;
    const counts = listing && plan.content.source_site === 'offertoday'
      ? offerTodayBreakdown(plan.content.resolved_scope, listing.page_depth)
      : null;
    return (
      <div className="review-stack">
        <section className="control-subpanel"><h3>Ready to start this run?</h3><dl className="review-facts"><div><dt>Expires</dt><dd>{formatControlDateTime(plan.expiresAt)}</dd></div><div><dt>Readiness</dt><dd>{plan.readiness.status}</dd></div></dl></section>
        {listing && <p>{plan.content.resolved_scope.query_target_count} Query Targets × {listing.page_depth} Page Depth; Run Page Cap {listing.run_page_cap}.</p>}
        {counts && <p>Native: {counts.nativeTargets} targets / {counts.nativePages} pages. Keywords: {counts.keywordTargets} targets / {counts.keywordPages} pages. Total: {counts.nativePages + counts.keywordPages} pages.</p>}
        {detail && <p>Frozen detail snapshot: {plan.detailTargetCount} jobs. Limit: {detail.limit.kind === 'entire_snapshot' ? 'all eligible jobs' : 'up to'}{detail.limit.detail_run_cap ? ` ${detail.limit.detail_run_cap}` : ''}. Jobs outside this snapshot stay available for a later run.</p>}
        <details className="control-subpanel"><summary>Review reference</summary><p>Plan: {plan.planId}</p><p>Fingerprint: {plan.planFingerprint}</p></details>
        {plan.readiness.blockingErrors.map((error) => <p key={error.code} className="control-error">{error.code}: {error.message}</p>)}
      </div>
    );
  }
  return <p role="status" className="control-empty">{state.review.error || state.plan.error ? 'Review could not be completed. Your choices are kept; correct them or refresh the review.' : 'Checking the current scope and readiness…'}</p>;
}

export default function TaskControlWizard({ hash = window.location.hash }) {
  const route = useMemo(() => parseControlRoute(hash), [hash]);
  const draftRoute = useMemo(() => ({
    kind: route.kind,
    flow: route.flow,
    mode: route.mode,
    automationId: route.automationId,
    draftId: route.draftId,
    sourceSite: route.sourceSite,
    step: route.step,
  }), [route.kind, route.flow, route.mode, route.automationId, route.draftId, route.sourceSite, route.step]);
  const initialBundle = useMemo(() => route.kind === 'wizard'
    ? (() => { const bundle = readDraft(globalThis.sessionStorage, route.draftId, route); return route.step ? { ...bundle, draft: { ...bundle.draft, step: route.step } } : bundle; })()
    : { draft: createWizardDraft({ flow: 'automation', mode: 'create', automationId: null, sourceSite: 'jobsdb' }), notice: route.notice }, [route]);
  const [state, dispatch] = useReducer(wizardReducer, initialBundle, (bundle) => createWizardState(bundle.draft, bundle.notice));
  const headingRef = useRef(null);
  const dialogTriggerRef = useRef(null);
  const resultHeadingRef = useRef(null);
  const [automationRetry, setAutomationRetry] = useState(0);
  const draftIdentityRef = useRef(null);
  const authorityRequestRef = useRef(0);
  const [clock, setClock] = useState(Date.now);
  const classificationRequestVersionRef = useRef(0);
  const [classificationRetry, setClassificationRetry] = useState(0);

  useEffect(() => {
    if (draftRoute.kind !== 'wizard') return;
    const identity = JSON.stringify([draftRoute.flow, draftRoute.mode, draftRoute.automationId, draftRoute.draftId, draftRoute.sourceSite]);
    if (draftIdentityRef.current === identity) {
      if (draftRoute.step) dispatch({ type: 'stepChanged', step: draftRoute.step });
      return;
    }
    draftIdentityRef.current = identity;
    const bundle = readDraft(globalThis.sessionStorage, draftRoute.draftId, draftRoute);
    if (draftRoute.step) bundle.draft = { ...bundle.draft, step: draftRoute.step };
    dispatch({ type: 'hydrate', ...bundle });
  }, [draftRoute]);

  useEffect(() => {
    if (route.kind !== 'wizard' || route.draftId) return;
    window.location.hash = buildControlRoute({ ...route, draftId: newDraftId(), sourceSite: route.sourceSite || state.draft.source_site, step: state.draft.step });
  }, [route, state.draft.source_site, state.draft.step]);

  useEffect(() => {
    if (route.kind !== 'wizard' || !route.draftId) return;
    const result = writeDraft(globalThis.sessionStorage, route.draftId, state.draft);
    if (!result.ok && result.notice !== state.notice) dispatch({ type: 'notice', notice: result.notice });
  }, [route.draftId, route.kind, state.draft, state.notice]);

  useEffect(() => {
    headingRef.current?.focus();
  }, [state.draft.step]);

  useEffect(() => {
    if (state.result) resultHeadingRef.current?.focus();
  }, [state.result]);

  useEffect(() => {
    if (route.kind !== 'wizard' || !route.draftId) return undefined;
    const controller = new AbortController();
    const version = classificationRequestVersionRef.current + 1;
    classificationRequestVersionRef.current = version;
    dispatch({ type: 'classificationsStarted', version });
    getSourceClassifications(state.draft.source_site, { signal: controller.signal })
      .then((value) => dispatch({ type: 'classificationsSucceeded', value, version }))
      .catch((error) => {
        if (!controller.signal.aborted) dispatch({ type: 'classificationsFailed', error: controlError(error), version });
      });
    return () => controller.abort();
  }, [classificationRetry, route.draftId, route.kind, state.draft.source_site]);

  const automationRoute = useMemo(() => ({
    kind: route.kind, flow: route.flow, mode: route.mode,
    automationId: route.automationId, draftId: route.draftId, sourceSite: route.sourceSite,
  }), [route.kind, route.flow, route.mode, route.automationId, route.draftId, route.sourceSite]);
  useEffect(() => {
    if (automationRoute.kind !== 'wizard' || !automationRoute.automationId || !automationRoute.draftId) return undefined;
    const controller = new AbortController();
    dispatch({ type: 'automationStarted' });
    getAutomation(automationRoute.automationId, { signal: controller.signal })
      .then((automation) => {
        if (controller.signal.aborted) return;
        const restored = readDraft(globalThis.sessionStorage, automationRoute.draftId, automationRoute).draft;
        const nextDraft = automationRoute.flow !== 'run_now' && restored.intent
          ? restored
          : { ...draftFromAutomation(automationRoute, automation), step: restored.step };
        dispatch({ type: 'automationSucceeded', value: automation, draft: nextDraft });
      })
      .catch((error) => {
        if (!controller.signal.aborted) dispatch({ type: 'automationFailed', error: controlError(error) });
      });
    return () => controller.abort();
  }, [automationRoute, automationRetry]);

  useEffect(() => {
    if (!state.plan.value || state.result) return undefined;
    const timer = window.setInterval(() => setClock(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [state.plan.value, state.result]);

  const requestAuthority = useCallback(async () => {
    if (!state.classifications.value) return;
    const requestVersion = ++authorityRequestRef.current;
    const draftFingerprint = wizardDraftFingerprint(state.draft);
    const kind = route.flow === 'automation' ? 'review' : 'plan';
    dispatch({ type: 'authorityStarted', kind, draftFingerprint });
    try {
      let value;
      if (route.flow === 'automation') {
        value = await reviewAutomation(buildAutomationReviewRequest(state.draft, state.classifications.value));
      } else if (route.flow === 'run_now') {
        value = await prepareDispatchPlan({ kind: 'saved_automation', automation_id: state.automation.value.id });
      } else {
        value = await prepareDispatchPlan(buildOneOffRun(state.draft, state.classifications.value));
      }
      if (requestVersion !== authorityRequestRef.current) return;
      const conflictError = value.readiness?.blockingErrors?.find((error) => error.code === 'DETAIL_RUN_CONFLICT');
      dispatch({ type: 'authoritySucceeded', kind, value, draftFingerprint, conflict: conflictError ? { crawlJobId: conflictError.context.crawl_job_id, status: 'active', error: null } : null });
    } catch (error) {
      if (requestVersion !== authorityRequestRef.current) return;
      dispatch({ type: 'authorityFailed', kind, error: controlError(error), draftFingerprint });
    }
  }, [route.flow, state.automation.value, state.classifications.value, state.draft]);

  useEffect(() => {
    if (state.draft.step !== 'review' || route.kind !== 'wizard' || state.result) return;
    if (route.flow === 'run_now' && !state.automation.value) return;
    requestAuthority();
  }, [requestAuthority, route.flow, route.kind, state.automation.value, state.draft.step, state.result]);

  useEffect(() => {
    if (state.conflict?.status !== 'cancelling') return undefined;
    const controller = new AbortController();
    const timer = window.setInterval(async () => {
      try {
        const run = await getCrawlJob(state.conflict.crawlJobId, { signal: controller.signal });
        if (run.status === 'cancelled') {
          dispatch({ type: 'conflictStatus', status: 'cancelled' });
          requestAuthority();
        } else if (TERMINAL_RUN_STATUSES.has(run.status)) {
          dispatch({ type: 'conflictStatus', status: run.status });
        }
      } catch (error) {
        if (!controller.signal.aborted) dispatch({ type: 'conflictStatus', status: 'cancelling', error: controlError(error) });
      }
    }, 1000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [requestAuthority, state.conflict?.crawlJobId, state.conflict?.status]);

  if (route.kind !== 'wizard') {
    return <section className="task-control-wizard"><h1>Task Control route unavailable</h1><p role="alert">{route.notice}</p><button type="button" onClick={() => { window.location.hash = '#scheduler'; }}>Back to board</button></section>;
  }

  const currentStepIndex = STEP_ORDER.indexOf(state.draft.step);
  const busy = state.mutation.status === 'loading';
  const currentFingerprint = wizardDraftFingerprint(state.draft);
  const authority = route.flow === 'automation' ? state.review : state.plan;
  const authorityCurrent = authority.status === 'success' && authority.draftFingerprint === currentFingerprint;
  const planExpired = state.plan.value && new Date(state.plan.value.expiresAt).valueOf() <= clock;
  const ready = authorityCurrent && (authority.value?.readiness?.status === 'ready') && !planExpired && !state.conflict;

  const goToStep = (step) => {
    if (busy || state.result || route.flow === 'run_now') return;
    const index = STEP_ORDER.indexOf(step);
    if (index > currentStepIndex && !STEP_ORDER.slice(0, index).every((item) => isStepComplete(state.draft, item))) return;
    writeDraft(globalThis.sessionStorage, route.draftId, { ...state.draft, step });
    dispatch({ type: 'stepChanged', step });
    window.location.hash = buildControlRoute({ ...route, sourceSite: state.draft.source_site, step });
  };
  const goNext = () => {
    if (!isStepComplete(state.draft)) return;
    const step = STEP_ORDER[Math.min(currentStepIndex + 1, STEP_ORDER.length - 1)];
    goToStep(step);
  };
  const goBack = () => {
    const step = STEP_ORDER[Math.max(currentStepIndex - 1, 0)];
    goToStep(step);
  };

  const discard = () => {
    clearDraft(globalThis.sessionStorage, route.draftId);
    dispatch({ type: 'dialogClosed' });
    window.location.hash = buildControlRoute({ kind: 'board', sourceSite: state.draft.source_site });
  };

  const saveOrDispatch = async () => {
    if (!ready || busy || state.result) return;
    if (state.plan.value && new Date(state.plan.value.expiresAt).valueOf() <= Date.now()) { setClock(Date.now()); return; }
    dispatch({ type: 'mutationStarted', kind: route.flow === 'automation' ? 'save' : 'dispatch' });
    try {
      let result;
      if (route.flow === 'automation') {
        const request = buildAutomationMutation(state.draft, state.classifications.value, state.review.value);
        const mutationResult = state.draft.mode === 'edit'
          ? await updateAutomation(state.draft.automation_id, request)
          : await createAutomation(request);
        result = await getAutomation(mutationResult.id);
      } else {
        result = await dispatchPlan(state.plan.value.planId, state.plan.value.confirmationToken, state.plan.value.planFingerprint);
      }
      clearDraft(globalThis.sessionStorage, route.draftId);
      dispatch({ type: 'mutationSucceeded', kind: route.flow === 'automation' ? 'save' : 'dispatch', result });
    } catch (error) {
      dispatch({ type: 'mutationFailed', kind: route.flow === 'automation' ? 'save' : 'dispatch', error: controlError(error) });
    }
  };

  const runWithChanges = () => {
    if (!state.automation.value) return;
    const id = newDraftId();
    const targetRoute = { flow: 'one_off', mode: 'create', automationId: null, sourceSite: state.automation.value.sourceSite, draftId: id };
    const base = draftFromAutomation(targetRoute, state.automation.value);
    const draft = { ...base, flow: 'one_off', mode: 'create', automation_id: null, step: 'intent' };
    writeDraft(globalThis.sessionStorage, id, draft);
    window.location.hash = buildControlRoute(targetRoute);
  };

  const createPairedDetail = () => {
    const id = newDraftId();
    const targetRoute = { flow: 'automation', mode: 'create', automationId: null, sourceSite: state.draft.source_site, draftId: id };
    writeDraft(globalThis.sessionStorage, id, pairedDetailDraft({ ...state.draft, flow: 'automation' }));
    window.location.hash = buildControlRoute(targetRoute);
  };

  const confirmCancel = async () => {
    dispatch({ type: 'mutationStarted', kind: 'cancel-conflict' });
    try {
      await cancelCrawlJob(state.conflict.crawlJobId);
      dispatch({ type: 'mutationSucceeded', kind: 'cancel-conflict', result: null });
      dispatch({ type: 'dialogClosed' });
      dispatch({ type: 'conflictStatus', status: 'cancelling' });
    } catch (error) {
      dispatch({ type: 'mutationFailed', kind: 'cancel-conflict', error: controlError(error) });
    }
  };

  return (
    <section className="task-control-wizard">
      <header className="wizard-header"><div><button type="button" className="wizard-back-board" disabled={busy} onClick={() => { window.location.hash = buildControlRoute({ kind: 'board', sourceSite: state.draft.source_site }); }}>← Back to board</button><p className="wizard-eyebrow">{SOURCE_LABELS[state.draft.source_site]} · {route.flow === 'automation' ? 'Recurring collection' : 'One-time collection'}</p><h1>{route.flow === 'automation' ? (route.mode === 'edit' ? 'Edit Automation' : 'New Automation') : route.flow === 'run_now' ? 'Run Automation now' : 'New One-off run'}</h1></div><button type="button" disabled={busy || Boolean(state.result)} onClick={(event) => { dialogTriggerRef.current = event.currentTarget; hasMeaningfulDraft(state.draft) ? dispatch({ type: 'dialogOpened', dialog: { kind: 'discard' } }) : discard(); }}>Discard draft</button></header>
      {state.notice && <p role="status" className="control-warning">{state.notice}</p>}
      {state.classifications.error && <p role="alert" className="control-error">{state.classifications.error.message}</p>}
      {state.automation.error && <div role="alert" className="control-error">{state.automation.error.message}<button type="button" onClick={() => setAutomationRetry((value) => value + 1)}>Retry loading Automation</button></div>}
      {state.automation.status === 'loading' && <p role="status">Loading saved Automation settings…</p>}

      {route.flow !== 'run_now' && <ol className="wizard-progress" aria-label="Wizard progress">{STEP_ORDER.map((step, index) => <li key={step} aria-current={state.draft.step === step ? 'step' : undefined}><button type="button" disabled={busy || Boolean(state.result) || (index > currentStepIndex && !STEP_ORDER.slice(0, index).every((item) => isStepComplete(state.draft, item)))} onClick={() => goToStep(step)}><span>{index + 1}</span>{stepTitle(step)}</button></li>)}</ol>}

      <div className="wizard-layout">
        <main className="wizard-main">
          <fieldset className="wizard-fields" hidden={Boolean(state.result)} disabled={busy || Boolean(state.result) || (route.mode === 'edit' && state.automation.status !== 'success')}>
          <h2 ref={headingRef} tabIndex="-1">{stepTitle(state.draft.step)}</h2>
          {state.draft.step === 'intent' && route.mode !== 'edit' && route.flow !== 'run_now' && <label className="control-field">Source<select aria-label="Source" aria-describedby="source-change-help" value={state.draft.source_site} onChange={(event) => { const sourceSite = event.target.value; dispatch({ type: 'sourceChanged', sourceSite }); window.location.hash = buildControlRoute({ ...route, sourceSite, step: 'intent' }); }}><option value="jobsdb">JobsDB</option><option value="ctgoodjobs">CTgoodjobs</option><option value="offertoday">OfferToday</option></select><small id="source-change-help">Changing Source clears your category and execution choices.</small></label>}
          {state.draft.step === 'intent' && <IntentStep draft={state.draft} dispatch={dispatch} route={route} onRunWithChanges={runWithChanges} />}
          {state.draft.step === 'scope' && state.classifications.status === 'loading' && <p role="status" className="control-empty">Loading major categories…</p>}
          {state.draft.step === 'scope' && state.classifications.status === 'error' && !state.classifications.value && <div className="control-error" role="status"><p>Major categories could not be loaded.</p><button type="button" onClick={() => setClassificationRetry((current) => current + 1)}>Retry loading categories</button></div>}
          {state.draft.step === 'scope' && state.classifications.value && <SourceScopeTree sourceSite={state.draft.source_site} classifications={state.classifications.value.classifications} scope={state.draft.scope} onChange={(scope) => dispatch({ type: 'scopeChanged', scope })} />}
          {state.draft.step === 'execution' && <ExecutionStep draft={state.draft} dispatch={dispatch} onEditScope={() => goToStep('scope')} />}
          {state.draft.step === 'review' && route.flow === 'run_now' && <IntentStep draft={state.draft} dispatch={dispatch} route={route} onRunWithChanges={runWithChanges} />}
          {state.draft.step === 'review' && route.flow !== 'run_now' && <div className="review-edit-actions" aria-label="Edit reviewed choices"><button type="button" onClick={() => goToStep('intent')}>Edit task</button><button type="button" onClick={() => goToStep('scope')}>Edit scope</button><button type="button" onClick={() => goToStep('execution')}>Edit configuration</button></div>}
          {state.draft.step === 'review' && route.flow === 'automation' && <p className="control-notice">{route.mode === 'edit' ? 'Save updates this Automation’s settings. Its lifecycle state is unchanged.' : state.draft.schedule.initial_state === 'active' ? 'Save enables this recurring Automation. Runs follow the schedule below.' : 'Save keeps this Automation paused. Enable it from Scheduler when you are ready.'}</p>}
          {state.draft.step === 'review' && planExpired && <p role="alert" className="control-error">This review has expired. Refresh review to check the current work before starting.</p>}
          {state.draft.step === 'review' && <ReviewProjection state={state} route={route} />}
          {(state.review.error || state.plan.error) && <div className="control-error" role="alert"><p>{(state.review.error || state.plan.error).message}</p></div>}
          {state.conflict && <div className="control-conflict" role="status"><h3>Active manual detail run conflict</h3><p>Run <a href={`#crawl-tasks?task=${encodeURIComponent(state.conflict.crawlJobId)}`}>{state.conflict.crawlJobId}</a> is {state.conflict.status}. A fresh plan is built only after cancelled acknowledgement.</p><button type="button" disabled={state.conflict.status !== 'active' || busy} onClick={(event) => { dialogTriggerRef.current = event.currentTarget; dispatch({ type: 'dialogOpened', dialog: { kind: 'cancel-conflict' } }); }}>{state.conflict.status === 'cancelling' ? 'Cancelling…' : 'Cancel conflicting run'}</button>{state.conflict.error && <p className="control-error">{state.conflict.error.message}</p>}</div>}
          {state.mutation.error && <p className="control-error" role="alert">{state.mutation.error.message}{state.mutation.error.stale && ' Refresh the server review before retrying.'}</p>}
          </fieldset>
          {state.result && <section className="control-success" role="status">
            <h2 ref={resultHeadingRef} tabIndex="-1">{route.flow === 'automation' ? 'Automation saved.' : 'Run request accepted.'}</h2>
            {route.flow === 'automation' ? <><p><strong>{state.result.configuration?.name}</strong> · {state.result.lifecycleState === 'paused' ? 'Paused — no scheduled runs will start until you enable it in Scheduler.' : state.result.lifecycleState === 'active' ? 'Active — future runs follow its schedule.' : state.result.lifecycleState}</p>{state.result.lifecycleState === 'active' && <p>Next run: {formatControlDateTime(state.result.nextRunAt, state.result.configuration?.timezone)}</p>}</> : <><p>The run has been requested. Open its task to follow actual progress.</p><a className="control-primary-link" href={`#crawl-tasks?task=${encodeURIComponent(state.result.crawlJobId)}`}>View task</a></>}
            {route.flow === 'automation' && state.draft.intent === 'listing' && <button type="button" onClick={createPairedDetail}>Create separate detail Automation draft</button>}
            <button type="button" onClick={() => { window.location.hash = buildControlRoute({ kind: 'board', sourceSite: state.draft.source_site }); }}>Back to board</button>
          </section>}
          {!state.result && <nav className="wizard-actions" aria-label="Wizard actions">{currentStepIndex > 0 && route.flow !== 'run_now' && <button type="button" disabled={busy} onClick={goBack}>Back</button>}{state.draft.step !== 'review' ? <button type="button" className="control-primary" disabled={busy || !isStepComplete(state.draft) || (route.mode === 'edit' && state.automation.status !== 'success')} onClick={goNext}>Continue</button> : <><button type="button" onClick={requestAuthority} disabled={busy || authority.status === 'loading'}>{authority.status === 'loading' ? 'Reviewing…' : 'Refresh review'}</button><button type="button" className="control-primary" disabled={!ready || busy} onClick={saveOrDispatch}>{busy ? 'Working…' : route.flow === 'automation' ? 'Save reviewed Automation' : 'Confirm and start'}</button></>}</nav>}

        </main>
        <aside className="wizard-summary" aria-label="Live draft summary">
          <h2>Your {route.flow === 'automation' ? 'Automation' : 'run'}</h2>
          <dl>
            <div><dt>Source</dt><dd>{SOURCE_LABELS[state.draft.source_site]}</dd></div>
            <div><dt>Task</dt><dd>{state.draft.intent === 'listing' ? 'Discover listings' : state.draft.intent === 'detail' ? 'Fetch job details' : 'Not chosen'}</dd></div>
            <div><dt>Categories</dt><dd>{state.draft.scope?.mode === 'all' ? 'All major categories' : state.draft.scope?.classification_ids?.length ? state.draft.scope.classification_ids.map((id) => state.classifications.value?.classifications.find((item) => item.id === id)?.label || id).join(', ') : 'Not chosen'}</dd></div>
            {state.draft.intent === 'listing' && <><div><dt>Pages per query</dt><dd>{state.draft.execution.page_depth || 'Not set'}</dd></div><div><dt>Total page cap</dt><dd>{state.draft.execution.run_page_cap || 'Not set'}</dd></div></>}
            {state.draft.intent === 'detail' && <div><dt>Details</dt><dd>{state.draft.execution.limit_kind === 'entire_snapshot' ? 'All eligible at review time' : `Up to ${state.draft.execution.detail_run_cap || '—'} jobs`}</dd></div>}
            <div><dt>When</dt><dd>{route.flow === 'automation' ? schedulePresetSummary(state.draft.schedule.cron_expression, state.draft.schedule.timezone) : 'Once, after confirmation'}</dd></div>
            {route.mode === 'edit' && <div><dt>Current state</dt><dd>{state.automation.value?.lifecycleState || 'Loading…'}</dd></div>}
          </dl>
          <p>{route.flow === 'automation' ? 'Review your settings before saving. Saving does not launch a one-off run.' : 'Review checks the current work before you confirm a run.'}</p>
          <details><summary>Draft reference</summary><p>{route.draftId || 'Creating…'}</p></details>
        </aside>
      </div>

      {state.dialog?.kind === 'discard' && <ConfirmActionDialog title="Discard this draft?" summary="This clears only the browser draft. It does not mutate an Automation, plan, or run." confirmLabel="Discard draft" pending={false} error={null} restoreFocusRef={dialogTriggerRef} onCancel={() => dispatch({ type: 'dialogClosed' })} onConfirm={discard} />}
      {state.dialog?.kind === 'cancel-conflict' && <ConfirmActionDialog title="Cancel conflicting detail run?" summary="Cancellation is acknowledged in two phases. Committed work stays visible and unfinished work returns to backend-owned backlog." confirmLabel="Request cancellation" pending={busy} error={state.mutation.error} restoreFocusRef={dialogTriggerRef} onCancel={() => dispatch({ type: 'dialogClosed' })} onConfirm={confirmCancel} />}
    </section>
  );
}
