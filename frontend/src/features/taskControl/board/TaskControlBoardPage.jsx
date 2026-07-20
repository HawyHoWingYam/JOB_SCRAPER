import React, { useCallback, useEffect, useMemo, useReducer, useRef } from 'react';
import { controlError } from '../shared/controlApi';
import { buildControlRoute, newDraftId, parseControlRoute } from '../shared/controlRoute';
import { formatControlDateTime } from '../shared/controlTime';
import ConfirmActionDialog from '../shared/ConfirmActionDialog';
import {
  cancelCrawlJob,
  getTaskControlBoard,
  permanentlyDeleteAutomation,
  resumeManualTask,
  reviewAutomationDelete,
  transitionAutomation,
} from './boardApi';
import { boardReducer, createBoardState } from './boardReducer';
import { buildCrawlTaskRoute } from './boardRoute';
import './TaskControlBoardPage.css';

const SOURCE_LABELS = { jobsdb: 'JobsDB', ctgoodjobs: 'CTgoodjobs', offertoday: 'OfferToday' };

function actionLabel(action) {
  return {
    view_task: 'Task', view_logs: 'Logs', open_catalog: 'Catalog', edit: 'Edit', run_now: 'Run now',
    pause: 'Pause', resume: 'Resume', archive: 'Archive', restore: 'Restore',
    delete_review: 'Delete permanently', cancel: 'Cancel', resume_manual_action: 'Resume',
  }[action] || action;
}

function scopeSummary(scope) {
  if (scope?.mode === 'all') return 'All source classifications';
  return `${scope?.rules?.length || 0} Exact/Subtree rule(s)`;
}

function RunProgress({ run }) {
  if (run.phase === 'listing' && run.listingWorkload) {
    const workload = run.listingWorkload;
    return <p>{workload.query_target_count} targets · {workload.pages_requested}/{workload.run_page_cap} pages requested · depth {workload.page_depth}</p>;
  }
  const detail = run.detailSnapshot;
  if (!detail) return null;
  return <p>{detail.fetched_count} fetched · {detail.saved_count} saved · {detail.remaining_count} remaining in snapshot · {detail.future_eligible_count} eligible later</p>;
}

export default function TaskControlBoardPage({ hash = window.location.hash }) {
  const route = useMemo(() => parseControlRoute(hash), [hash]);
  const sourceSite = route.kind === 'board' ? route.sourceSite : 'jobsdb';
  const [state, dispatch] = useReducer(boardReducer, sourceSite, createBoardState);
  const requestVersionRef = useRef(0);
  const dialogTriggerRef = useRef(null);

  useEffect(() => {
    if (state.sourceSite !== sourceSite) dispatch({ type: 'sourceChanged', sourceSite });
  }, [sourceSite, state.sourceSite]);

  const loadBoard = useCallback(async ({ signal } = {}) => {
    const version = requestVersionRef.current + 1;
    requestVersionRef.current = version;
    dispatch({ type: 'loadStarted', version });
    try {
      const value = await getTaskControlBoard(sourceSite, { signal });
      dispatch({ type: 'loadSucceeded', version, value });
    } catch (error) {
      if (!signal?.aborted) dispatch({ type: 'loadFailed', version, error: controlError(error) });
    }
  }, [sourceSite]);

  const hasCancelling = state.board.value?.activeRuns.some(({ run }) => run.status === 'cancelling');
  useEffect(() => {
    const controller = new AbortController();
    loadBoard({ signal: controller.signal });
    const timer = window.setInterval(
      () => loadBoard(),
      hasCancelling ? 1000 : 30000,
    );
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [hasCancelling, loadBoard]);

  const board = state.board.value;
  const busy = state.mutation.status === 'loading';

  const navigateAction = (action, entity) => {
    if (action === 'view_task') window.location.hash = buildCrawlTaskRoute(entity.id);
    else if (action === 'view_logs') window.location.hash = buildCrawlTaskRoute(entity.id, 'events');
    else if (action === 'open_catalog') window.location.hash = `#source-catalogs?source=${encodeURIComponent(entity.sourceSite || sourceSite)}`;
    else if (action === 'edit') window.location.hash = buildControlRoute({ flow: 'automation', mode: 'edit', automationId: entity.id, sourceSite: entity.sourceSite, draftId: newDraftId(), step: 'intent' });
    else if (action === 'run_now') window.location.hash = buildControlRoute({ flow: 'run_now', mode: 'review', automationId: entity.id, sourceSite: entity.sourceSite, draftId: newDraftId(), step: 'review' });
  };

  const mutateAutomation = async (automation, action) => {
    if (busy) return;
    dispatch({ type: 'mutationStarted', entityId: automation.id, kind: action });
    try {
      await transitionAutomation(automation.id, action, automation.revision);
      dispatch({ type: 'mutationSucceeded', entityId: automation.id, kind: action, notice: `${automation.name}: ${action} completed.` });
      await loadBoard();
    } catch (error) {
      dispatch({ type: 'mutationFailed', error: controlError(error) });
      if (error?.code === 'AUTOMATION_REVISION_CONFLICT') await loadBoard();
    }
  };

  const handleAction = async (descriptor, entity, event) => {
    if (!descriptor.enabled || busy) return;
    const action = descriptor.action;
    if (['view_task', 'view_logs', 'open_catalog', 'edit', 'run_now'].includes(action)) {
      navigateAction(action, entity);
      return;
    }
    if (action === 'archive' || action === 'cancel') {
      dialogTriggerRef.current = event.currentTarget;
      dispatch({ type: 'dialogOpened', dialog: { kind: action, entity } });
      return;
    }
    if (action === 'delete_review') {
      dispatch({ type: 'mutationStarted', entityId: entity.id, kind: action });
      try {
        const deleteReview = await reviewAutomationDelete(entity.id);
        dialogTriggerRef.current = event.currentTarget;
        dispatch({ type: 'dialogOpened', dialog: { kind: 'delete', entity }, deleteReview });
      } catch (error) {
        dispatch({ type: 'mutationFailed', error: controlError(error) });
      }
      return;
    }
    if (action === 'resume_manual_action') {
      dispatch({ type: 'mutationStarted', entityId: entity.id, kind: action });
      try {
        await resumeManualTask(entity.id);
        dispatch({ type: 'mutationSucceeded', entityId: entity.id, kind: action, notice: 'Manual-action recovery requested.' });
        await loadBoard();
      } catch (error) {
        dispatch({ type: 'mutationFailed', error: controlError(error) });
      }
      return;
    }
    await mutateAutomation(entity, action);
  };

  const confirmDialog = async () => {
    const { kind, entity } = state.dialog;
    if (kind === 'archive') return mutateAutomation(entity, 'archive');
    if (kind === 'cancel') {
      dispatch({ type: 'mutationStarted', entityId: entity.id, kind });
      try {
        await cancelCrawlJob(entity.id);
        dispatch({ type: 'mutationSucceeded', entityId: entity.id, kind, notice: 'Cancellation requested; waiting for acknowledgement.' });
        await loadBoard();
      } catch (error) {
        dispatch({ type: 'mutationFailed', error: controlError(error) });
      }
      return undefined;
    }
    if (kind === 'delete') {
      dispatch({ type: 'mutationStarted', entityId: entity.id, kind });
      try {
        await permanentlyDeleteAutomation(entity.id, entity.revision, state.deleteReview.reviewToken);
        dispatch({ type: 'mutationSucceeded', entityId: entity.id, kind, notice: `${entity.name} permanently deleted; execution history was preserved.` });
        await loadBoard();
      } catch (error) {
        dispatch({ type: 'mutationFailed', error: controlError(error) });
      }
    }
    return undefined;
  };

  const renderActions = (actions, entity) => (
    <div className="board-actions">{actions.map((action) => (
      <button key={action.action} type="button" disabled={!action.enabled || busy} title={action.reasonCode || undefined} onClick={(event) => handleAction(action, entity, event)}>{actionLabel(action.action)}</button>
    ))}</div>
  );

  if (!board && state.board.status === 'loading') return <section className="task-control-board"><h1>Task Control Board</h1><p role="status">Loading server-owned operations…</p></section>;
  if (!board && state.board.error) return <section className="task-control-board"><h1>Task Control Board</h1><p role="alert">{state.board.error.message}</p><button type="button" onClick={() => loadBoard()}>Retry</button></section>;

  const automations = state.showArchived ? board?.archivedAutomations || [] : board?.upcoming || [];
  const crossSourceAttention = board?.sourceSummaries.filter((summary) => summary.sourceSite !== sourceSite && summary.attentionCount > 0) || [];
  const impact = state.deleteReview?.impact;

  return (
    <section className="task-control-board">
      <header className="board-header"><div><p className="board-eyebrow">Desktop operations</p><h1>Task Control Board</h1><p>Server-owned sections, normalized run authority, and revision-safe actions.</p></div><div className="board-header-actions"><button type="button" onClick={() => { window.location.hash = buildControlRoute({ flow: 'automation', mode: 'create', sourceSite, draftId: newDraftId(), step: 'intent' }); }}>New Automation</button><button type="button" onClick={() => { window.location.hash = buildControlRoute({ flow: 'one_off', mode: 'create', sourceSite, draftId: newDraftId(), step: 'intent' }); }}>One-off Run</button></div></header>

      <div className="board-source-tabs" role="tablist" aria-label="Task Control Source">{board?.sourceSummaries.map((summary) => <button role="tab" aria-selected={summary.sourceSite === sourceSite} key={summary.sourceSite} type="button" onClick={() => { window.location.hash = buildControlRoute({ kind: 'board', sourceSite: summary.sourceSite }); }}><strong>{SOURCE_LABELS[summary.sourceSite]}</strong><span>{summary.state.replace('_', ' ')} · {summary.attentionCount} attention · {summary.activeRunCount} running</span></button>)}</div>
      {crossSourceAttention.length > 0 && <aside className="cross-source-banner" role="status"><strong>Attention exists on another Source.</strong>{crossSourceAttention.map((summary) => <button key={summary.sourceSite} type="button" onClick={() => { window.location.hash = buildControlRoute({ kind: 'board', sourceSite: summary.sourceSite }); }}>Open {SOURCE_LABELS[summary.sourceSite]} ({summary.attentionCount})</button>)}</aside>}
      {state.board.stale && <p className="board-warning" role="alert">Refresh failed; prior good data remains visible. {state.board.error.message}</p>}
      {state.notice && <p className="board-success" role="status">{state.notice}</p>}
      {state.mutation.error && <p className="board-error" role="alert">{state.mutation.error.message}</p>}

      {board?.allClear && <section className="board-all-clear"><h2>All clear</h2><p>No attention items, active runs, or upcoming Automations for {SOURCE_LABELS[sourceSite]}.</p></section>}

      {board?.needsAttention.length > 0 && <section className="board-section"><h2>Needs attention</h2><div className="attention-list">{board.needsAttention.map((item) => <article key={item.id} className="attention-card"><p className="board-code">{item.code}</p><h3>{item.title}</h3><p>{item.summary}</p>{renderActions([item.primaryAction, ...item.secondaryActions], { id: item.entityId, sourceSite: item.sourceSite })}</article>)}</div></section>}

      {board?.activeRuns.length > 0 && <section className="board-section"><h2>Active runs</h2><div className="active-run-list">{board.activeRuns.map(({ run, issue, manualActionGuidance, actions }) => <article key={run.id} className="active-run-card"><div><p className="board-code">{run.phase} · {run.mode}</p><h3>{run.status}</h3><RunProgress run={run} />{issue && <p className="board-warning">{issue.code || issue.issueClass}: {issue.summary}</p>}{manualActionGuidance && <p>{manualActionGuidance.message}</p>}</div>{renderActions(actions, { id: run.id, sourceSite: run.sourceSite })}</article>)}</div></section>}

      <section className="board-section"><div className="section-heading"><div><h2>{state.showArchived ? 'Archived Automations' : 'Upcoming Automations'}</h2><p>Backend order is preserved. Lifecycle actions carry the displayed revision.</p></div><button type="button" onClick={() => dispatch({ type: 'archivedToggled' })}>{state.showArchived ? 'Show upcoming' : `Show archived (${board?.archivedAutomations.length || 0})`}</button></div>{automations.length === 0 ? <p className="board-empty">No {state.showArchived ? 'archived' : 'upcoming'} Automations for this Source.</p> : <div className="automation-table-wrap"><table className="automation-table"><caption>{state.showArchived ? 'Archived' : 'Upcoming'} Automation operations</caption><thead><tr><th>Automation</th><th>Intent / scope</th><th>Schedule / timezone</th><th>Last outcome</th><th>Next run</th><th>Lifecycle / Catalog</th><th>Actions</th></tr></thead><tbody>{automations.map((automation) => { const expanded = state.expanded.has(automation.id); return <React.Fragment key={automation.id}><tr><th scope="row"><button type="button" className="disclosure" aria-expanded={expanded} aria-controls={`automation-${automation.id}`} onClick={() => dispatch({ type: 'expandedToggled', id: automation.id })}>{expanded ? '▾' : '▸'} {automation.name}</button><small>r{automation.revision}</small></th><td>{automation.phase} · {scopeSummary(automation.authoredScope)}</td><td>{automation.schedule.humanSummary}</td><td>{automation.latestOutcome ? `${automation.latestOutcome.status}` : 'No run recorded'}</td><td>{automation.schedule.nextRunAt ? formatControlDateTime(automation.schedule.nextRunAt, automation.schedule.timezone) : 'Not scheduled'}</td><td>{automation.lifecycleState}<br /><a href={`#source-catalogs?source=${automation.sourceSite}`}>{automation.catalogHealth.state}</a></td><td>{renderActions(automation.actions, automation)}</td></tr>{expanded && <tr id={`automation-${automation.id}`} className="automation-expanded"><td colSpan="7"><dl><div><dt>Catalog revision</dt><dd>{automation.catalogHealth.revisionId || 'Not published'}</dd></div><div><dt>Resolved Query Targets</dt><dd>{automation.resolvedScopeSummary?.query_target_count ?? 'No recent resolved run'}</dd></div><div><dt>Execution</dt><dd>{automation.phase} · {automation.mode}</dd></div><div><dt>Current run</dt><dd>{automation.currentRun ? <a href={buildCrawlTaskRoute(automation.currentRun.id)}>{automation.currentRun.status}</a> : 'None'}</dd></div></dl></td></tr>}</React.Fragment>; })}</tbody></table></div>}</section>

      {state.dialog && <ConfirmActionDialog title={state.dialog.kind === 'archive' ? `Archive ${state.dialog.entity.name}?` : state.dialog.kind === 'cancel' ? 'Cancel this run?' : `Permanently delete ${state.dialog.entity.name}?`} summary={state.dialog.kind === 'archive' ? 'Future dispatch stops. Existing runs, jobs, and history remain.' : state.dialog.kind === 'cancel' ? 'Committed work remains visible. Unfinished detail work returns to backend-owned later backlog after cancelled acknowledgement.' : `Remove the Automation and ${impact?.automation_revision_count ?? 0} revision(s). Preserve ${impact?.schedule_execution_count ?? 0} schedule execution(s), ${impact?.crawl_job_count ?? 0} Crawl Job(s), and run history. Review expires ${state.deleteReview?.expiresAt ? formatControlDateTime(state.deleteReview.expiresAt) : 'soon'}.`} confirmLabel={state.dialog.kind === 'archive' ? 'Archive Automation' : state.dialog.kind === 'cancel' ? 'Request cancellation' : 'Delete permanently'} pending={busy} error={state.mutation.error} restoreFocusRef={dialogTriggerRef} onCancel={() => dispatch({ type: 'dialogClosed' })} onConfirm={confirmDialog} />}
    </section>
  );
}
