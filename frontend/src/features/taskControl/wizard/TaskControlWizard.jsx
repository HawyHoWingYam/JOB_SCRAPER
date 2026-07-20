import React, { useCallback, useEffect, useMemo, useReducer, useRef } from 'react';
import {
  cancelCrawlJob,
  controlError,
  createAutomation,
  dispatchPlan,
  getAutomation,
  getCrawlJob,
  getPublishedCatalog,
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
  return { intent: 'Choose intent', scope: 'Choose Source scope', execution: 'Configure execution', review: 'Review and confirm' }[step];
}

function IntentStep({ draft, dispatch, route, automation, onRunWithChanges }) {
  if (route.flow === 'run_now') {
    return (
      <div className="intent-grid">
        <button type="button" className="intent-card" aria-pressed={draft.run_choice === 'saved'} onClick={() => dispatch({ type: 'runChoiceChanged', value: 'saved' })}>
          <strong>Run saved configuration</strong><span>Prepare a plan from Automation r{automation?.revision || '…'} without edits.</span>
        </button>
        <button type="button" className="intent-card" onClick={onRunWithChanges}>
          <strong>Run with changes</strong><span>Open a separate One-off draft. The Automation is not edited.</span>
        </button>
      </div>
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
        <strong>{automationFlow ? 'Enrich job details' : 'Recover detail backlog'}</strong>
        <span>{automationFlow ? 'Schedule bounded detail recovery from an explicit backlog.' : 'Freeze and recover an explicit finite detail snapshot.'}</span>
      </button>
    </div>
  );
}

function ExecutionStep({ draft, dispatch }) {
  const setExecution = (value) => dispatch({ type: 'executionChanged', value });
  const setSchedule = (value) => dispatch({ type: 'scheduleChanged', value });
  const automationFlow = draft.flow === 'automation';
  return (
    <div className="execution-stack">
      {draft.intent === 'listing' ? (
        <section className="control-subpanel">
          <h3>Listing workload</h3>
          <div className="control-field-grid">
            <label className="control-field">Page Depth per Query Target<input type="number" min="1" max="1000" value={draft.execution.page_depth || ''} onChange={(event) => setExecution({ page_depth: event.target.value })} /></label>
            <label className="control-field">Run Page Cap<input type="number" min="1" value={draft.execution.run_page_cap || ''} onChange={(event) => setExecution({ run_page_cap: event.target.value })} /></label>
          </div>
          <p>Server review resolves Query Target count and verifies <strong>targets × depth</strong> against the operator cap and system ceiling.</p>
        </section>
      ) : (
        <section className="control-subpanel">
          <h3>Detail backlog population</h3>
          <div className="control-choice-row">
            {[['source_backlog', 'Source backlog'], ['crawl_scope', 'Source-classification Crawl Scope'], ['listing_batch', 'Named listing batch']].map(([value, label]) => <button key={value} type="button" aria-pressed={draft.execution.backlog_kind === value} onClick={() => setExecution({ backlog_kind: value })}>{label}</button>)}
          </div>
          {draft.execution.backlog_kind === 'listing_batch' && <label className="control-field">Listing batch Crawl Job ID<input value={draft.execution.source_listing_crawl_job_id || ''} onChange={(event) => setExecution({ source_listing_crawl_job_id: event.target.value })} /></label>}
          <h3>{automationFlow ? 'Maximum details per future scheduled run' : 'Finite One-off snapshot limit'}</h3>
          <div className="control-choice-row">
            {!automationFlow && <button type="button" aria-pressed={draft.execution.limit_kind === 'entire_snapshot'} onClick={() => setExecution({ limit_kind: 'entire_snapshot' })}>Entire eligible snapshot</button>}
            <button type="button" aria-pressed={draft.execution.limit_kind === 'stop_after'} onClick={() => setExecution({ limit_kind: 'stop_after' })}>{automationFlow ? 'Maximum per scheduled run' : 'Stop after N'}</button>
          </div>
          {draft.execution.limit_kind === 'stop_after' && <label className="control-field">Detail Run Cap<input type="number" min="1" value={draft.execution.detail_run_cap || ''} onChange={(event) => setExecution({ detail_run_cap: event.target.value })} /></label>}
          <p>{automationFlow ? 'Eligible-now is a non-frozen estimate. Each due run freezes its own future snapshot.' : 'Review freezes exact membership and cutoff. Recovery Segment is intentionally hidden.'}</p>
        </section>
      )}

      <details className="control-subpanel">
        <summary>Advanced execution</summary>
        {draft.source_site === 'ctgoodjobs' ? <p><strong>Headed only.</strong> CTgoodjobs requires headed-worker/manual-action readiness.</p> : <label className="control-field">Crawl mode<select value={draft.execution.crawl_mode || 'headless'} onChange={(event) => setExecution({ crawl_mode: event.target.value })}><option value="headless">Headless</option><option value="headed">Headed</option></select></label>}
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
          <label className="control-field">Initial state<select value={draft.schedule.initial_state || 'paused'} onChange={(event) => setSchedule({ initial_state: event.target.value })}><option value="paused">Paused</option><option value="active">Active</option></select></label>
        </section>
      )}
    </div>
  );
}

function ReviewProjection({ state, route }) {
  const review = state.review.value;
  const plan = state.plan.value;
  if (route.flow === 'automation' && review) {
    const workload = review.listingWorkload;
    const detail = review.detailPreview;
    return (
      <div className="review-stack">
        {review.before && <section className="control-subpanel"><h3>Edit before / after</h3><p>Before: {review.before.configuration.name} · r{review.before.revision}</p><p>After: {state.draft.schedule.name} · expected r{state.draft.expected_revision}</p></section>}
        <section className="control-subpanel"><h3>Server-owned scope</h3><dl className="review-facts"><div><dt>Catalog revision</dt><dd>{review.catalogRevisionId}</dd></div><div><dt>Authored mode</dt><dd>{review.authoredScope.mode}</dd></div><div><dt>Resolved Query Targets</dt><dd>{review.resolvedScope.query_target_count}</dd></div><div><dt>Review fingerprint</dt><dd><code>{review.inputFingerprint.slice(0, 16)}</code></dd></div></dl></section>
        {workload && <section className="control-subpanel"><h3>Listing workload</h3><p>{workload.query_target_count} targets × {workload.page_depth} depth = <strong>{workload.estimated_max_pages}</strong> estimated maximum pages.</p><p>Run Page Cap {workload.run_page_cap}; system ceiling {workload.system_run_page_cap}.</p></section>}
        {detail && <section className="control-subpanel"><h3>Detail preview (not frozen)</h3><p>{detail.eligible_now_count} eligible now; {detail.selected_now_count} would be selected by the current cap.</p><p>Future scheduled membership is frozen only when the Automation becomes due. Absolute safety cap: {detail.absolute_safety_cap}.</p></section>}
        <section className="control-subpanel"><h3>Schedule and readiness</h3><p>{review.scheduleSummary.human_summary}</p><p>Next: {formatControlDateTime(review.scheduleSummary.next_run_at, review.scheduleSummary.timezone)}</p><p>Status: <strong>{review.readiness.status}</strong></p>{review.readiness.blockingErrors.map((error) => <p key={error.code} className="control-error">{error.code}: {error.message}</p>)}</section>
        {review.warnings.map((warning) => <p role="status" className="control-warning" key={warning.code}>{warning.code}: {warning.message}</p>)}
      </div>
    );
  }
  if (plan) {
    const listing = plan.content.listing_settings;
    const detail = plan.content.detail_settings;
    return (
      <div className="review-stack">
        <section className="control-subpanel"><h3>Immutable Dispatch Plan</h3><dl className="review-facts"><div><dt>Plan</dt><dd>{plan.planId}</dd></div><div><dt>Fingerprint</dt><dd><code>{plan.planFingerprint.slice(0, 16)}</code></dd></div><div><dt>Expires</dt><dd>{formatControlDateTime(plan.expiresAt)}</dd></div><div><dt>Readiness</dt><dd>{plan.readiness.status}</dd></div></dl></section>
        {listing && <p>{plan.content.resolved_scope.query_target_count} Query Targets × {listing.page_depth} Page Depth; Run Page Cap {listing.run_page_cap}.</p>}
        {detail && <p>Frozen detail snapshot: {plan.detailTargetCount} canonical targets. Limit: {detail.limit.kind}{detail.limit.detail_run_cap ? ` ${detail.limit.detail_run_cap}` : ''}. Recovery Segment is not operator authority.</p>}
        {plan.readiness.blockingErrors.map((error) => <p key={error.code} className="control-error">{error.code}: {error.message}</p>)}
      </div>
    );
  }
  return <p role="status" className="control-empty">Preparing a current server review…</p>;
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
  const catalogVersionRef = useRef(0);

  useEffect(() => {
    if (draftRoute.kind !== 'wizard') return;
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
    if (route.kind !== 'wizard') return undefined;
    const controller = new AbortController();
    const version = catalogVersionRef.current + 1;
    catalogVersionRef.current = version;
    dispatch({ type: 'catalogStarted', version });
    getPublishedCatalog(state.draft.source_site, { signal: controller.signal })
      .then((value) => dispatch({ type: 'catalogSucceeded', value, version }))
      .catch((error) => {
        if (!controller.signal.aborted) dispatch({ type: 'catalogFailed', error: controlError(error), version });
      });
    return () => controller.abort();
  }, [route.kind, state.draft.source_site]);

  useEffect(() => {
    if (route.kind !== 'wizard' || !route.automationId) return undefined;
    const controller = new AbortController();
    dispatch({ type: 'automationStarted' });
    getAutomation(route.automationId, { signal: controller.signal })
      .then((automation) => {
        const shouldHydrate = state.draft.expected_revision == null || route.flow === 'run_now';
        dispatch({ type: 'automationSucceeded', value: automation, draft: shouldHydrate ? draftFromAutomation(route, automation) : null });
      })
      .catch((error) => {
        if (!controller.signal.aborted) dispatch({ type: 'automationFailed', error: controlError(error) });
      });
    return () => controller.abort();
  }, [route, state.draft.expected_revision]);

  const requestAuthority = useCallback(async () => {
    if (!state.catalog.value) return;
    const draftFingerprint = wizardDraftFingerprint(state.draft);
    const kind = route.flow === 'automation' ? 'review' : 'plan';
    dispatch({ type: 'authorityStarted', kind, draftFingerprint });
    try {
      let value;
      if (route.flow === 'automation') {
        value = await reviewAutomation(buildAutomationReviewRequest(state.draft, state.catalog.value));
      } else if (route.flow === 'run_now') {
        value = await prepareDispatchPlan({ version: 1, kind: 'saved_automation', automation_id: state.automation.value.id, expected_revision: state.automation.value.revision });
      } else {
        value = await prepareDispatchPlan(buildOneOffRun(state.draft, state.catalog.value));
      }
      if (wizardDraftFingerprint(state.draft) !== draftFingerprint) return;
      const conflictError = value.readiness?.blockingErrors?.find((error) => error.code === 'DETAIL_RUN_CONFLICT');
      dispatch({ type: 'authoritySucceeded', kind, value, draftFingerprint, conflict: conflictError ? { crawlJobId: conflictError.context.crawl_job_id, status: 'active', error: null } : null });
    } catch (error) {
      dispatch({ type: 'authorityFailed', kind, error: controlError(error), draftFingerprint });
    }
  }, [route.flow, state.automation.value, state.catalog.value, state.draft]);

  useEffect(() => {
    if (state.draft.step !== 'review' || route.kind !== 'wizard') return;
    if (route.flow === 'run_now' && !state.automation.value) return;
    requestAuthority();
  }, [requestAuthority, route.flow, route.kind, state.automation.value, state.draft.step]);

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
  const planExpired = state.plan.value && new Date(state.plan.value.expiresAt) <= new Date();
  const ready = authorityCurrent && (authority.value?.readiness?.status === 'ready') && !planExpired && !state.conflict;

  const goNext = () => {
    if (!isStepComplete(state.draft)) return;
    const step = STEP_ORDER[Math.min(currentStepIndex + 1, STEP_ORDER.length - 1)];
    dispatch({ type: 'stepChanged', step });
    window.location.hash = buildControlRoute({ ...route, step });
  };
  const goBack = () => {
    const step = STEP_ORDER[Math.max(currentStepIndex - 1, 0)];
    dispatch({ type: 'stepChanged', step });
    window.location.hash = buildControlRoute({ ...route, step });
  };

  const discard = () => {
    clearDraft(globalThis.sessionStorage, route.draftId);
    dispatch({ type: 'dialogClosed' });
    window.location.hash = buildControlRoute({ kind: 'board' });
  };

  const saveOrDispatch = async () => {
    if (!ready || busy) return;
    dispatch({ type: 'mutationStarted', kind: route.flow === 'automation' ? 'save' : 'dispatch' });
    try {
      let result;
      if (route.flow === 'automation') {
        const request = buildAutomationMutation(state.draft, state.catalog.value, state.review.value);
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
    const draft = { ...base, flow: 'one_off', mode: 'create', automation_id: null, expected_revision: null, step: 'intent' };
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
      <header className="wizard-header"><div><button type="button" className="wizard-back-board" onClick={() => { window.location.hash = buildControlRoute({ kind: 'board' }); }}>← Back to board</button><p className="wizard-eyebrow">Task Control authoring</p><h1>{route.flow === 'automation' ? (route.mode === 'edit' ? 'Edit Automation' : 'New Automation') : route.flow === 'run_now' ? 'Run Automation now' : 'New One-off run'}</h1></div><button type="button" onClick={(event) => { dialogTriggerRef.current = event.currentTarget; hasMeaningfulDraft(state.draft) ? dispatch({ type: 'dialogOpened', dialog: { kind: 'discard' } }) : discard(); }}>Discard draft</button></header>
      {state.notice && <p role="status" className="control-warning">{state.notice}</p>}
      {state.catalog.error && <p role="alert" className="control-error">{state.catalog.error.message}</p>}
      {state.automation.error && <p role="alert" className="control-error">{state.automation.error.message}</p>}

      <ol className="wizard-progress" aria-label="Wizard progress">{STEP_ORDER.map((step, index) => <li key={step} aria-current={state.draft.step === step ? 'step' : undefined}><span>{index + 1}</span>{stepTitle(step)}</li>)}</ol>

      <div className="wizard-layout">
        <main className="wizard-main">
          <h2 ref={headingRef} tabIndex="-1">{stepTitle(state.draft.step)}</h2>
          {state.draft.step === 'intent' && <IntentStep draft={state.draft} dispatch={dispatch} route={route} automation={state.automation.value} onRunWithChanges={runWithChanges} />}
          {state.draft.step === 'scope' && state.catalog.value && <SourceScopeTree sourceSite={state.draft.source_site} catalog={state.catalog.value.catalog} scope={state.draft.scope} onChange={(scope) => dispatch({ type: 'scopeChanged', scope })} />}
          {state.draft.step === 'execution' && <ExecutionStep draft={state.draft} dispatch={dispatch} />}
          {state.draft.step === 'review' && route.flow === 'run_now' && <IntentStep draft={state.draft} dispatch={dispatch} route={route} automation={state.automation.value} onRunWithChanges={runWithChanges} />}
          {state.draft.step === 'review' && <ReviewProjection state={state} route={route} />}
          {(state.review.error || state.plan.error) && <div className="control-error" role="alert"><p>{(state.review.error || state.plan.error).message}</p></div>}
          {state.conflict && <div className="control-conflict" role="status"><h3>Active manual detail run conflict</h3><p>Run <a href={`#crawl-tasks?task=${encodeURIComponent(state.conflict.crawlJobId)}`}>{state.conflict.crawlJobId}</a> is {state.conflict.status}. A fresh plan is built only after cancelled acknowledgement.</p><button type="button" disabled={state.conflict.status !== 'active' || busy} onClick={(event) => { dialogTriggerRef.current = event.currentTarget; dispatch({ type: 'dialogOpened', dialog: { kind: 'cancel-conflict' } }); }}>{state.conflict.status === 'cancelling' ? 'Cancelling…' : 'Cancel conflicting run'}</button>{state.conflict.error && <p className="control-error">{state.conflict.error.message}</p>}</div>}
          {state.mutation.error && <p className="control-error" role="alert">{state.mutation.error.message}{state.mutation.error.stale && ' Refresh the server review before retrying.'}</p>}
          {state.result && <div className="control-success" role="status"><strong>{route.flow === 'automation' ? 'Automation saved.' : 'Reviewed plan dispatched.'}</strong>{route.flow !== 'automation' && <a href={`#crawl-tasks?task=${encodeURIComponent(state.result.crawlJobId)}`}>View task</a>}{route.flow === 'automation' && state.draft.intent === 'listing' && <button type="button" onClick={createPairedDetail}>Create separate detail Automation draft</button>}<button type="button" onClick={() => { window.location.hash = buildControlRoute({ kind: 'board' }); }}>Back to board</button></div>}
          <nav className="wizard-actions" aria-label="Wizard actions">{currentStepIndex > 0 && state.draft.step !== 'review' && <button type="button" onClick={goBack}>Back</button>}{state.draft.step !== 'review' ? <button type="button" disabled={!isStepComplete(state.draft)} onClick={goNext}>Continue</button> : <><button type="button" onClick={requestAuthority} disabled={busy}>{authority.status === 'loading' ? 'Reviewing…' : 'Refresh review'}</button><button type="button" disabled={!ready || busy || Boolean(state.result)} onClick={saveOrDispatch}>{busy ? 'Working…' : route.flow === 'automation' ? 'Save reviewed Automation' : 'Confirm and start'}</button></>}</nav>
        </main>
        <aside className="wizard-summary" aria-label="Live draft summary"><h2>Live summary</h2><dl><div><dt>Flow</dt><dd>{route.flow.replace('_', ' ')}</dd></div><div><dt>Source</dt><dd>{SOURCE_LABELS[state.draft.source_site]}</dd></div><div><dt>Intent</dt><dd>{state.draft.intent || 'Not chosen'}</dd></div><div><dt>Scope</dt><dd>{state.draft.scope?.mode || 'Not chosen'}{state.draft.scope?.rules?.length ? ` · ${state.draft.scope.rules.length} rule(s)` : ''}</dd></div><div><dt>Catalog</dt><dd>{state.catalog.value?.revision?.id || state.catalog.status}</dd></div><div><dt>Draft</dt><dd>{route.draftId || 'Creating…'}</dd></div></dl>{route.mode !== 'edit' && route.flow !== 'run_now' && <label className="control-field">Source<select value={state.draft.source_site} onChange={(event) => { const sourceSite = event.target.value; dispatch({ type: 'sourceChanged', sourceSite }); window.location.hash = buildControlRoute({ ...route, sourceSite }); }}><option value="jobsdb">JobsDB</option><option value="ctgoodjobs">CTgoodjobs</option><option value="offertoday">OfferToday</option></select></label>}</aside>
      </div>

      {state.dialog?.kind === 'discard' && <ConfirmActionDialog title="Discard this draft?" summary="This clears only the browser draft. It does not mutate an Automation, plan, or run." confirmLabel="Discard draft" pending={false} error={null} restoreFocusRef={dialogTriggerRef} onCancel={() => dispatch({ type: 'dialogClosed' })} onConfirm={discard} />}
      {state.dialog?.kind === 'cancel-conflict' && <ConfirmActionDialog title="Cancel conflicting detail run?" summary="Cancellation is acknowledged in two phases. Committed work stays visible and unfinished work returns to backend-owned backlog." confirmLabel="Request cancellation" pending={busy} error={state.mutation.error} restoreFocusRef={dialogTriggerRef} onCancel={() => dispatch({ type: 'dialogClosed' })} onConfirm={confirmCancel} />}
    </section>
  );
}
