import React, {
  useCallback,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
} from 'react';
import {
  catalogErrorState,
  createPublicationReview,
  createRollbackReview,
  discoverCandidate,
  getCandidate,
  getCatalogSummaries,
  getPublishedCatalog,
  getRevisionHistory,
  getValidationRuns,
  publishCandidate,
  rollbackRevision,
  startValidation,
} from './sourceCatalogsApi';
import {
  createSourceCatalogState,
  sourceCatalogsReducer,
} from './sourceCatalogsReducer';
import {
  DIFF_CATEGORIES,
  impactRows,
  isPublishable,
  projectCandidateDiff,
} from './sourceCatalogsProjection';
import {
  parseSourceCatalogRoute,
  SOURCE_CATALOG_SOURCES,
  sourceCatalogHash,
} from './sourceCatalogsRoute';
import CatalogActionDialog from './components/CatalogActionDialog';
import './SourceCatalogsPage.css';

const SOURCE_LABELS = {
  jobsdb: 'JobsDB',
  ctgoodjobs: 'CTgoodjobs',
  offertoday: 'OfferToday',
};

const ACTIVE_VALIDATION_STATUSES = new Set(['pending', 'running']);

function formatDate(value) {
  if (!value) return 'Not available';
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString();
}

function formatJsonSummary(value) {
  const entries = Object.entries(value || {});
  if (!entries.length) return 'Not recorded';
  return entries
    .slice(0, 4)
    .map(([key, item]) => `${key}: ${String(item)}`)
    .join(' · ');
}

function Status({ children, tone = 'neutral' }) {
  return <span className={`catalog-status catalog-status-${tone}`}>{children}</span>;
}

function ResourceError({ resource, onRetry }) {
  if (!resource.error) return null;
  return (
    <div className="catalog-error" role="alert">
      <span>{resource.error.message}</span>
      {resource.error.requestId && <small>Request {resource.error.requestId}</small>}
      {onRetry && <button type="button" onClick={onRetry}>Retry</button>}
    </div>
  );
}

export default function SourceCatalogsPage() {
  const initialSource = parseSourceCatalogRoute().source;
  const [state, dispatch] = useReducer(
    sourceCatalogsReducer,
    initialSource,
    createSourceCatalogState,
  );
  const [diffFilters, setDiffFilters] = useState(() =>
    new Set(DIFF_CATEGORIES.map(([key]) => key)),
  );
  const [selectedRollback, setSelectedRollback] = useState(null);
  const dialogTriggerRef = useRef(null);
  const summariesRef = useRef([]);

  const selectedSummary = useMemo(
    () => state.summaries.value?.find((row) => row.sourceSite === state.source) || null,
    [state.source, state.summaries.value],
  );

  const refresh = useCallback(() => dispatch({ type: 'refreshRequested' }), []);

  useEffect(() => {
    const handleHashChange = () => {
      const next = parseSourceCatalogRoute().source;
      if (next !== state.source) dispatch({ type: 'sourceChanged', source: next });
    };
    window.addEventListener('hashchange', handleHashChange);
    return () => window.removeEventListener('hashchange', handleHashChange);
  }, [state.source]);

  useEffect(() => {
    const controller = new AbortController();
    const version = state.requestVersion;
    const load = async () => {
      for (const resource of ['summaries', 'published', 'history']) {
        dispatch({ type: 'resourceStarted', resource, version });
      }
      let summaries = summariesRef.current;
      try {
        summaries = await getCatalogSummaries({ signal: controller.signal });
        summariesRef.current = summaries;
        dispatch({ type: 'resourceSucceeded', resource: 'summaries', value: summaries, version });
      } catch (error) {
        if (controller.signal.aborted) return;
        dispatch({ type: 'resourceFailed', resource: 'summaries', error: catalogErrorState(error), version });
      }

      const summary = summaries.find((row) => row.sourceSite === state.source);
      const publishedPromise = getPublishedCatalog(state.source, { signal: controller.signal })
        .then((value) => dispatch({ type: 'resourceSucceeded', resource: 'published', value, version }))
        .catch((error) => {
          if (controller.signal.aborted) return;
          const mapped = catalogErrorState(error);
          if (mapped.kind === 'not-published') {
            dispatch({ type: 'resourceSucceeded', resource: 'published', value: null, version });
          } else {
            dispatch({ type: 'resourceFailed', resource: 'published', error: mapped, version });
          }
        });
      const historyPromise = getRevisionHistory(state.source, { signal: controller.signal })
        .then((value) => dispatch({ type: 'resourceSucceeded', resource: 'history', value, version }))
        .catch((error) => {
          if (!controller.signal.aborted) {
            dispatch({ type: 'resourceFailed', resource: 'history', error: catalogErrorState(error), version });
          }
        });

      if (summary?.latestCandidate?.id) {
        dispatch({ type: 'resourceStarted', resource: 'candidate', version });
        dispatch({ type: 'resourceStarted', resource: 'validation', version });
        try {
          const candidate = await getCandidate(
            state.source,
            summary.latestCandidate.id,
            { signal: controller.signal },
          );
          dispatch({ type: 'resourceSucceeded', resource: 'candidate', value: candidate, version });
          const runs = await getValidationRuns(state.source, candidate.id, {
            signal: controller.signal,
          });
          dispatch({ type: 'resourceSucceeded', resource: 'validation', value: runs, version });
        } catch (error) {
          if (!controller.signal.aborted) {
            const mapped = catalogErrorState(error);
            const resource = mapped.kind === 'stale-candidate' ? 'candidate' : 'validation';
            dispatch({ type: 'resourceFailed', resource, error: mapped, version });
          }
        }
      } else {
        dispatch({ type: 'resourceSucceeded', resource: 'candidate', value: null, version });
        dispatch({ type: 'resourceSucceeded', resource: 'validation', value: [], version });
      }
      await Promise.allSettled([publishedPromise, historyPromise]);
    };
    load();
    return () => controller.abort();
    // requestVersion is the explicit authoritative-refetch trigger.
  }, [state.requestVersion, state.source]);

  const validationActive = state.validation.value?.some((run) =>
    ACTIVE_VALIDATION_STATUSES.has(run.status),
  );

  useEffect(() => {
    if (!validationActive || !state.candidate.value) return undefined;
    const controller = new AbortController();
    const version = state.requestVersion;
    const timer = window.setInterval(async () => {
      try {
        const runs = await getValidationRuns(state.source, state.candidate.value.id, {
          signal: controller.signal,
        });
        dispatch({ type: 'resourceSucceeded', resource: 'validation', value: runs, version });
        if (!runs.some((run) => ACTIVE_VALIDATION_STATUSES.has(run.status))) refresh();
      } catch (error) {
        if (!controller.signal.aborted) {
          dispatch({ type: 'resourceFailed', resource: 'validation', error: catalogErrorState(error), version });
        }
      }
    }, 3000);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [refresh, state.candidate.value, state.requestVersion, state.source, validationActive]);

  const runMutation = async (kind, operation, successMessage, { refreshAfter = true } = {}) => {
    if (state.mutation.status === 'loading') return null;
    dispatch({ type: 'mutationStarted', kind });
    try {
      const value = await operation();
      dispatch({ type: 'mutationSucceeded', kind, message: successMessage });
      if (refreshAfter) refresh();
      return value;
    } catch (error) {
      dispatch({ type: 'mutationFailed', kind, error: catalogErrorState(error) });
      return null;
    }
  };

  const handleDiscover = () => runMutation(
    'discover',
    () => discoverCandidate(state.source),
    'Candidate discovery completed. The active revision was not changed.',
  );

  const handleValidation = () => runMutation(
    'validation',
    () => startValidation(state.source, state.candidate.value.id),
    'Durable validation was queued.',
  );

  const handlePublicationReview = async (event) => {
    dialogTriggerRef.current = event.currentTarget;
    dispatch({ type: 'mutationStarted', kind: 'publication-review' });
    try {
      const review = await createPublicationReview(state.source, state.candidate.value.id);
      dispatch({ type: 'reviewSucceeded', kind: 'publication-review', value: review });
      dispatch({ type: 'dialogOpened', dialog: { kind: 'publish' } });
    } catch (error) {
      dispatch({ type: 'mutationFailed', kind: 'publication-review', error: catalogErrorState(error) });
    }
  };

  const handleRollbackReview = async (revision, event) => {
    dialogTriggerRef.current = event.currentTarget;
    setSelectedRollback(revision);
    dispatch({ type: 'mutationStarted', kind: 'rollback-review' });
    try {
      const review = await createRollbackReview(state.source, revision.id);
      dispatch({ type: 'reviewSucceeded', kind: 'rollback-review', value: review });
      dispatch({ type: 'dialogOpened', dialog: { kind: 'rollback' } });
    } catch (error) {
      dispatch({ type: 'mutationFailed', kind: 'rollback-review', error: catalogErrorState(error) });
    }
  };

  const closeDialog = () => {
    dispatch({ type: 'dialogClosed' });
    window.requestAnimationFrame(() => dialogTriggerRef.current?.focus());
  };

  const confirmDialog = async () => {
    const review = state.impactReview.value;
    const rollback = state.dialog?.kind === 'rollback';
    const target = rollback ? selectedRollback : state.candidate.value;
    const result = await runMutation(
      rollback ? 'rollback' : 'publish',
      () => rollback
        ? rollbackRevision(state.source, target.id, review.reviewToken)
        : publishCandidate(state.source, target.id, review.reviewToken),
      rollback ? 'Rollback completed and authoritative state was refreshed.' : 'Publication completed and authoritative state was refreshed.',
      { refreshAfter: false },
    );
    if (result) {
      closeDialog();
      refresh();
    }
  };

  const candidate = state.candidate.value;
  const diffRows = projectCandidateDiff(candidate, state.published.value).filter((row) =>
    diffFilters.has(row.category),
  );
  const reviewRows = impactRows(state.impactReview.value);
  const mutationBusy = state.mutation.status === 'loading';
  const activeRevision = selectedSummary?.publishedRevision;

  const selectSource = (source) => {
    if (source === state.source) return;
    window.location.hash = sourceCatalogHash(source);
  };

  const handleTabKeyDown = (event, index) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    let next = index;
    if (event.key === 'ArrowLeft') next = (index - 1 + SOURCE_CATALOG_SOURCES.length) % SOURCE_CATALOG_SOURCES.length;
    if (event.key === 'ArrowRight') next = (index + 1) % SOURCE_CATALOG_SOURCES.length;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = SOURCE_CATALOG_SOURCES.length - 1;
    const source = SOURCE_CATALOG_SOURCES[next];
    selectSource(source);
    document.getElementById(`source-tab-${source}`)?.focus();
  };

  return (
    <section className="source-catalogs-page">
      <header className="source-catalogs-header">
        <div>
          <p className="catalog-eyebrow">Crawl Control governance</p>
          <h1>Source Catalogs</h1>
          <p>Discover and validate source-native classifications before explicitly changing executable catalog revisions.</p>
        </div>
        <button type="button" className="catalog-primary" disabled={mutationBusy} onClick={handleDiscover}>
          {state.mutation.kind === 'discover' && mutationBusy ? 'Checking…' : 'Check for updates'}
        </button>
      </header>
      <p className="catalog-safety-note" role="note">
        Checking creates a non-executable candidate. It never changes the active revision.
      </p>

      <div className="catalog-source-tabs" role="tablist" aria-label="Source Catalog">
        {SOURCE_CATALOG_SOURCES.map((source, index) => {
          const summary = state.summaries.value?.find((row) => row.sourceSite === source);
          const selected = state.source === source;
          return (
            <button
              id={`source-tab-${source}`}
              key={source}
              type="button"
              role="tab"
              aria-selected={selected}
              aria-controls="source-catalog-workspace"
              tabIndex={selected ? 0 : -1}
              className={selected ? 'active' : ''}
              onClick={() => selectSource(source)}
              onKeyDown={(event) => handleTabKeyDown(event, index)}
            >
              <strong>{SOURCE_LABELS[source]}</strong>
              <span>{summary?.publishedRevision ? `r${summary.publishedRevision.sequence}` : 'Setup required'}</span>
              <Status tone={summary?.latestCandidate ? 'warning' : 'success'}>
                {summary?.latestCandidate?.state || 'No candidate'}
              </Status>
            </button>
          );
        })}
      </div>

      {state.feedback && <div className="catalog-feedback" role="status" aria-live="assertive">{state.feedback}</div>}
      {state.mutation.error && <div className="catalog-error" role="alert">{state.mutation.error.message}</div>}
      <ResourceError resource={state.summaries} onRetry={refresh} />

      <div id="source-catalog-workspace" role="tabpanel" aria-labelledby={`source-tab-${state.source}`} className="catalog-workspace">
        <section className="catalog-summary" aria-labelledby="catalog-summary-title">
          <div className="catalog-section-heading">
            <div>
              <h2 id="catalog-summary-title">Active revision</h2>
              <p>Authoritative read-only state; loading this page performs no discovery.</p>
            </div>
            {state.published.status === 'loading' && <Status>Refreshing…</Status>}
          </div>
          <ResourceError resource={state.published} onRetry={refresh} />
          {!state.published.value && state.published.status !== 'loading' ? (
            <div className="catalog-empty" role="status">No published revision. Governance setup is required and execution remains blocked.</div>
          ) : state.published.value && (
            <dl className="catalog-summary-grid">
              <div><dt>Revision</dt><dd>r{activeRevision?.sequence}</dd></div>
              <div><dt>Fingerprint</dt><dd><code>{activeRevision?.fingerprint.slice(0, 16)}</code></dd></div>
              <div><dt>Published</dt><dd>{formatDate(activeRevision?.publishedAt)}</dd></div>
              <div><dt>Actor</dt><dd>{activeRevision?.publishedBy}</dd></div>
              <div><dt>Nodes / Query Targets</dt><dd>{activeRevision?.nodeCount} / {activeRevision?.queryTargetCount}</dd></div>
              <div><dt>Validation health</dt><dd>{activeRevision?.validationSummary?.status || 'Not recorded'}</dd></div>
              <div><dt>Affected Automations</dt><dd>{selectedSummary?.affectedAutomationCount ?? 0}</dd></div>
              <div><dt>Provenance</dt><dd>{formatJsonSummary(activeRevision?.provenance)}</dd></div>
            </dl>
          )}
        </section>

        <section className="catalog-panel" aria-labelledby="candidate-title">
          <div className="catalog-section-heading">
            <div><h2 id="candidate-title">Candidate diff</h2><p>Source-native identity and hierarchy are primary; canonical matches are annotations only.</p></div>
            {candidate && <Status tone={candidate.state === 'validated' ? 'success' : 'warning'}>{candidate.state}</Status>}
          </div>
          <ResourceError resource={state.candidate} onRetry={refresh} />
          {!candidate ? (
            <div className="catalog-empty" role="status">No candidate. Use Check for updates to discover without changing execution.</div>
          ) : (
            <>
              <dl className="catalog-inline-facts">
                <div><dt>Candidate</dt><dd><code>{candidate.fingerprint.slice(0, 16)}</code></dd></div>
                <div><dt>Base revision</dt><dd>{candidate.baseRevisionId || 'Initial publication'}</dd></div>
                <div><dt>Discovered</dt><dd>{formatDate(candidate.createdAt)}</dd></div>
                <div><dt>Provenance</dt><dd>{formatJsonSummary(candidate.provenance)}</dd></div>
              </dl>
              <fieldset className="catalog-diff-filters">
                <legend>Visible changes</legend>
                {DIFF_CATEGORIES.map(([key, label]) => (
                  <label key={key}>
                    <input
                      type="checkbox"
                      checked={diffFilters.has(key)}
                      onChange={() => setDiffFilters((current) => {
                        const next = new Set(current);
                        if (next.has(key)) next.delete(key); else next.add(key);
                        return next;
                      })}
                    />
                    {label} ({candidate.diff[key]?.length || 0})
                  </label>
                ))}
              </fieldset>
              {projectCandidateDiff(candidate, state.published.value).length === 0 ? (
                <div className="catalog-empty" role="status">No source changes. This candidate cannot create a pointless revision.</div>
              ) : diffRows.length === 0 ? (
                <div className="catalog-empty" role="status">No changes match the selected filters.</div>
              ) : (
                <ul className="catalog-diff-list">
                  {diffRows.map((row) => (
                    <li key={row.id}>
                      <div><Status tone={row.executionAffecting ? 'danger' : 'neutral'}>{row.categoryLabel}</Status>{row.executionAffecting && <span className="catalog-risk">Execution-affecting</span>}</div>
                      <strong>{row.nativePath}</strong>
                      {row.classificationId && <code>{row.classificationId}</code>}
                      <span>{formatJsonSummary(row.change)}</span>
                      {row.canonicalMatch && <small>Canonical clean_match: {row.canonicalMatch} (annotation only)</small>}
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </section>

        <section className="catalog-panel" aria-labelledby="validation-title">
          <div className="catalog-section-heading">
            <div><h2 id="validation-title">Durable validation</h2><p>Full-catalog offline checks are separate from bounded live smoke.</p></div>
            <button type="button" disabled={!candidate || mutationBusy || candidate.state === 'published'} onClick={handleValidation}>
              {state.mutation.kind === 'validation' && mutationBusy ? 'Queuing…' : 'Start / retry validation'}
            </button>
          </div>
          <ResourceError resource={state.validation} onRetry={refresh} />
          {state.source === 'ctgoodjobs' && <div className="catalog-headed-note" role="note"><strong>Headed only.</strong> CTgoodjobs live validation never offers headless execution.</div>}
          {!state.validation.value?.length ? <div className="catalog-empty" role="status">No durable validation runs yet.</div> : (
            <div className="catalog-validation-grid">
              {[
                ['offline', 'Offline full-catalog checks'],
                ['live_smoke', 'Changed-target bounded live smoke'],
              ].map(([kind, title]) => {
                const runs = state.validation.value.filter((run) => run.validationKind === kind);
                return <div key={kind}><h3>{title}</h3>{!runs.length ? <p>No runs required.</p> : <ul>{runs.map((run) => <li key={run.id}><div><Status tone={run.status === 'passed' ? 'success' : run.status === 'failed' ? 'danger' : 'warning'}>{run.status}</Status><strong>{run.classificationId || 'Full catalog'}</strong><span>Attempt {run.attempt}</span></div><code>{run.targetHashPrefix}</code><p>{formatJsonSummary(run.evidence)}</p>{run.error && <p className="catalog-error-inline">{formatJsonSummary(run.error)}</p>}{run.manualAction && <div className="catalog-manual-action"><strong>Manual action required{state.source === 'ctgoodjobs' ? ' — headed only' : ''}</strong><p>{formatJsonSummary(run.manualAction)}</p><button type="button" disabled={mutationBusy} onClick={handleValidation}>Resume / retry validation</button></div>}</li>)}</ul>}</div>;
              })}
            </div>
          )}
        </section>

        <section className="catalog-panel" aria-labelledby="impact-title">
          <div className="catalog-section-heading">
            <div><h2 id="impact-title">Automation impact</h2><p>Review Exact, Subtree, all-scope, Query Target and workload-cap consequences.</p></div>
            <button ref={dialogTriggerRef} type="button" disabled={!isPublishable(candidate) || mutationBusy} onClick={handlePublicationReview}>Review impact &amp; publish</button>
          </div>
          {!isPublishable(candidate) && <div className="catalog-empty" role="status">Publish remains disabled until required validation passes.</div>}
          {state.impactReview.error && <div className="catalog-error" role="alert">{state.impactReview.error.message}</div>}
          {reviewRows.length > 0 ? (
            <div className="catalog-table-scroll"><table><caption>Current Automation impact review</caption><thead><tr><th>Automation</th><th>Scope</th><th>Before / after targets</th><th>Workload cap</th><th>Result</th></tr></thead><tbody>{reviewRows.map((row) => <tr key={row.id}><td><strong>{row.id}</strong><br />r{row.revision} · {row.lifecycle} · {row.phase}</td><td>{row.scopeLabel}</td><td>{row.beforeCount} → {row.afterCount}</td><td>{row.capEffect}</td><td><Status tone={row.status === 'compatible' ? 'success' : 'danger'}>{row.status}</Status>{row.reasons.length > 0 && <small>{row.reasons.join(', ')}</small>}</td></tr>)}</tbody></table></div>
          ) : state.impactReview.value && <div className="catalog-empty" role="status">No versioned Automations are affected.</div>}
        </section>

        <section className="catalog-panel" aria-labelledby="history-title">
          <div className="catalog-section-heading"><div><h2 id="history-title">Immutable publication history</h2><p>Revision rows and append-only publish/rollback events are never edited in place.</p></div></div>
          <ResourceError resource={state.history} onRetry={refresh} />
          {!state.history.value?.revisions?.length ? <div className="catalog-empty" role="status">No publication history.</div> : (
            <div className="catalog-table-scroll"><table><caption>Source Catalog revision history</caption><thead><tr><th>Revision</th><th>Fingerprint</th><th>Provenance / validation</th><th>Published by / time</th><th>Status / action</th></tr></thead><tbody>{state.history.value.revisions.map((revision) => { const active = revision.id === activeRevision?.id; const events = state.history.value.publications.filter((event) => event.revisionId === revision.id); return <tr key={revision.id}><td>r{revision.sequence}</td><td><code>{revision.fingerprint.slice(0, 16)}</code></td><td>{formatJsonSummary(revision.provenance)}<br /><small>{formatJsonSummary(revision.validationSummary)}</small></td><td>{revision.publishedBy}<br />{formatDate(revision.publishedAt)}</td><td>{active ? <Status tone="success">Active</Status> : <button type="button" disabled={mutationBusy} onClick={(event) => handleRollbackReview(revision, event)}>Review rollback</button>}{events.map((event) => <small key={event.id}>{event.operation} · {event.actor} · {formatDate(event.createdAt)}</small>)}</td></tr>; })}</tbody></table></div>
          )}
        </section>
      </div>

      {state.dialog && (
        <CatalogActionDialog
          kind={state.dialog.kind}
          source={state.source}
          fingerprint={state.dialog.kind === 'rollback' ? selectedRollback?.fingerprint : candidate?.fingerprint}
          activeRevision={activeRevision?.id}
          impact={state.impactReview.value?.impact}
          submitting={mutationBusy && ['publish', 'rollback'].includes(state.mutation.kind)}
          error={state.mutation.error}
          onCancel={closeDialog}
          onConfirm={confirmDialog}
        />
      )}
    </section>
  );
}
