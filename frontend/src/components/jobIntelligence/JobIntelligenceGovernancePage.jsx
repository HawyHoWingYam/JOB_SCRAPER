import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import {
  GOVERNANCE_AREAS,
  fetchGovernanceSummary,
  isStaleGovernanceError,
} from '../../api/jobIntelligence';
import { formatApiErrorDetail } from '../../api/errors';
import AuditTimeline from './AuditTimeline';
import CompanyIndustryContextPanel from './CompanyIndustryContextPanel';
import DecisionDialog from './DecisionDialog';
import EvidencePanel from './EvidencePanel';
import GovernanceQueue from './GovernanceQueue';
import RecommendationPanel from './RecommendationPanel';
import { GOVERNANCE_AREA_ADAPTERS } from './governanceAreas';
import {
  navigateGovernance,
  parseGovernanceHash,
} from './governanceRoute';
import './JobIntelligenceGovernancePage.css';

const GOVERNANCE_PANEL_ID = 'governance-area-panel';
const OPTIONAL_DETAIL_SECTION_LABELS = [
  'Audit timeline',
  'Governed targets',
  'Recommendations',
];

function governanceTabId(area) {
  return `governance-tab-${area}`;
}

function summaryForArea(summary, area) {
  const definition = GOVERNANCE_AREAS.find((item) => item.key === area);
  return summary?.areas?.find((item) => item.key === definition?.summaryKey);
}

function idempotencyKey(area, itemId) {
  const randomId = globalThis.crypto?.randomUUID?.() || `${Date.now()}`;
  return `governance-ui:${area}:${itemId}:${randomId}`;
}

function detailOptions(payload) {
  if (Array.isArray(payload)) return payload;
  return payload?.targets || [];
}

function detailResources(payload) {
  if (!payload || Array.isArray(payload)) return {};
  const { targets: _targets, ...resources } = payload;
  return resources;
}

export default function JobIntelligenceGovernancePage() {
  const [route, setRoute] = useState(() => parseGovernanceHash());
  const [summary, setSummary] = useState(null);
  const [summaryError, setSummaryError] = useState(null);
  const [queue, setQueue] = useState({
    status: 'loading',
    items: [],
    total: 0,
    nextCursor: null,
    error: null,
  });
  const [detail, setDetail] = useState({
    status: 'idle',
    item: null,
    events: [],
    recommendations: [],
    options: [],
    resources: {},
    partialErrors: [],
    error: null,
  });
  const [decision, setDecision] = useState(null);
  const [feedback, setFeedback] = useState(null);
  const [queueFocusTarget, setQueueFocusTarget] = useState(null);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [detailRefreshVersion, setDetailRefreshVersion] = useState(0);
  const decisionTriggerRef = useRef(null);

  useEffect(() => {
    const handleHashChange = () => setRoute(parseGovernanceHash());
    window.addEventListener('hashchange', handleHashChange);
    return () => window.removeEventListener('hashchange', handleHashChange);
  }, []);

  const loadSummary = useCallback(async (signal) => {
    try {
      const payload = await fetchGovernanceSummary({ signal });
      setSummary(payload);
      setSummaryError(null);
    } catch (error) {
      if (signal?.aborted) return;
      setSummaryError(error);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    loadSummary(controller.signal);
    return () => controller.abort();
  }, [loadSummary, refreshVersion]);

  useEffect(() => {
    const controller = new AbortController();
    const adapter = GOVERNANCE_AREA_ADAPTERS[route.area];
    setQueue({
      status: 'loading',
      items: [],
      total: 0,
      nextCursor: null,
      error: null,
    });
    adapter.loadQueue(
      {
        query: route.query || '',
        cursor: route.cursor || null,
        limit: 50,
      },
      { signal: controller.signal },
    )
      .then((payload) => {
        if (controller.signal.aborted) return;
        const items = payload.items || [];
        setQueue({
          status: 'ready',
          items,
          total: payload.total ?? items.length,
          nextCursor: payload.next_cursor || null,
          error: null,
        });
      })
      .catch((error) => {
        if (controller.signal.aborted) return;
        setQueue({
          status: 'error',
          items: [],
          total: 0,
          nextCursor: null,
          error,
        });
      });
    return () => controller.abort();
  }, [route.area, route.cursor, route.query, refreshVersion]);

  useEffect(() => {
    if (!route.itemId) {
      setDetail({
        status: 'idle',
        item: null,
        events: [],
        recommendations: [],
        options: [],
        resources: {},
        partialErrors: [],
        error: null,
      });
      return undefined;
    }

    const controller = new AbortController();
    const adapter = GOVERNANCE_AREA_ADAPTERS[route.area];
    setDetail((current) => ({ ...current, status: 'loading', error: null }));

    const load = async () => {
      try {
        const item = await adapter.loadDetail(route.itemId, {
          signal: controller.signal,
        });
        const optionalLoads = await Promise.allSettled([
          adapter.loadAudit(route.itemId, { signal: controller.signal }),
          adapter.loadOptions({ signal: controller.signal }),
          adapter.loadRecommendations
            ? adapter.loadRecommendations(
                route.itemId,
                { limit: 10 },
                { signal: controller.signal },
              )
            : Promise.resolve(item.recommendations || []),
        ]);
        if (controller.signal.aborted) return;
        const [auditResult, optionsResult, recommendationResult] = optionalLoads;
        setDetail({
          status: 'ready',
          item,
          events:
            auditResult.status === 'fulfilled'
              ? auditResult.value.items || []
              : [],
          options:
            optionsResult.status === 'fulfilled'
              ? detailOptions(optionsResult.value)
              : [],
          resources:
            optionsResult.status === 'fulfilled'
              ? detailResources(optionsResult.value)
              : {},
          recommendations:
            recommendationResult.status === 'fulfilled'
              ? recommendationResult.value || []
              : item.recommendations || [],
          partialErrors: optionalLoads
            .flatMap((result, index) => (
              result.status === 'rejected'
                ? [{
                    section: OPTIONAL_DETAIL_SECTION_LABELS[index],
                    error: result.reason,
                  }]
                : []
            )),
          error: null,
        });
      } catch (error) {
        if (controller.signal.aborted) return;
        setDetail({
          status: 'error',
          item: null,
          events: [],
          recommendations: [],
          options: [],
          resources: {},
          partialErrors: [],
          error,
        });
      }
    };
    load();
    return () => controller.abort();
  }, [route.area, route.itemId, detailRefreshVersion]);

  const activeDefinition = useMemo(
    () => GOVERNANCE_AREAS.find((area) => area.key === route.area),
    [route.area],
  );
  const activeAdapter = GOVERNANCE_AREA_ADAPTERS[route.area];

  const closeDecision = useCallback(() => {
    setDecision(null);
    requestAnimationFrame(() => decisionTriggerRef.current?.focus());
  }, []);

  const clearQueueFocusTarget = useCallback(() => {
    setQueueFocusTarget(null);
  }, []);

  const openDecision = (action, event) => {
    decisionTriggerRef.current = event.currentTarget;
    setDecision({ action, submitting: false, error: null });
  };

  const handleTabKeyDown = (event, currentIndex) => {
    const lastIndex = GOVERNANCE_AREAS.length - 1;
    let nextIndex = null;
    if (event.key === 'ArrowRight') {
      nextIndex = currentIndex === lastIndex ? 0 : currentIndex + 1;
    } else if (event.key === 'ArrowLeft') {
      nextIndex = currentIndex === 0 ? lastIndex : currentIndex - 1;
    } else if (event.key === 'Home') {
      nextIndex = 0;
    } else if (event.key === 'End') {
      nextIndex = lastIndex;
    }

    if (nextIndex === null) return;
    event.preventDefault();
    const nextArea = GOVERNANCE_AREAS[nextIndex];
    document.getElementById(governanceTabId(nextArea.key))?.focus();
    navigateGovernance(nextArea.key);
  };

  const confirmDecision = async ({
    targetId,
    createTarget,
    genericTag,
    rejectionReason,
  }) => {
    const item = detail.item;
    const action = decision.action;
    setDecision((current) => ({ ...current, submitting: true, error: null }));
    const values = {
      action: action.value,
      expectedVersion: item.version,
      idempotencyKey: idempotencyKey(route.area, item.id),
      ...(targetId ? { targetId } : {}),
      ...(route.area === 'skill-candidates' && targetId
        ? { targetSkillId: targetId }
        : {}),
      ...(createTarget ? { createTarget } : {}),
      ...(genericTag ? { genericTag } : {}),
      ...(rejectionReason ? { rejectionReason } : {}),
    };
    try {
      await activeAdapter.decide(item.id, values, {});
      closeDecision();
      setFeedback({ kind: 'success', message: 'Decision recorded. Backlog refreshed.' });
      setQueue({
        status: 'loading',
        items: [],
        total: 0,
        nextCursor: null,
        error: null,
      });
      setQueueFocusTarget('search');
      setRefreshVersion((version) => version + 1);
      navigateGovernance(route.area);
    } catch (error) {
      if (isStaleGovernanceError(error)) {
        closeDecision();
        setFeedback({
          kind: 'conflict',
          message:
            'This item changed before confirmation. Evidence was reloaded; review the latest version.',
        });
        setDetailRefreshVersion((version) => version + 1);
        return;
      }
      setDecision((current) => ({
        ...current,
        submitting: false,
        error,
      }));
    }
  };

  return (
    <section
      className="job-intelligence-page"
      aria-labelledby="job-intelligence-title"
    >
      <header className="job-intelligence-header">
        <div>
          <p className="job-intelligence-eyebrow">Post-collection governance</p>
          <h1 id="job-intelligence-title">Job Intelligence Governance</h1>
          <p>
            Review evidence before changing Canonical Job Taxonomy, governed
            Skills, or Company Industries.
          </p>
        </div>
        <div className="job-intelligence-total" aria-live="polite">
          {summary
            ? `${summary.total_pending} pending decisions`
            : 'Loading backlog…'}
        </div>
      </header>

      {summary?.trusted_local && (
        <div className="trusted-local-warning" role="alert">
          <strong>Trusted local operation only.</strong>{' '}
          {summary.trusted_local.warning}
        </div>
      )}
      {summaryError && (
        <div className="job-intelligence-error" role="status">
          Governance summary unavailable:{' '}
          {formatApiErrorDetail(summaryError, 'Summary request failed')}
        </div>
      )}
      {feedback && (
        <div
          className={`governance-feedback ${feedback.kind}`}
          role="status"
          aria-live="assertive"
        >
          {feedback.message}
        </div>
      )}

      <div
        className="governance-tabs"
        role="tablist"
        aria-label="Governance areas"
      >
        {GOVERNANCE_AREAS.map((area, index) => {
          const areaSummary = summaryForArea(summary, area.key);
          const pending = areaSummary?.pending_count ?? '…';
          const selected = route.area === area.key;
          return (
            <button
              key={area.key}
              type="button"
              role="tab"
              id={governanceTabId(area.key)}
              aria-controls={GOVERNANCE_PANEL_ID}
              aria-selected={selected}
              tabIndex={selected ? 0 : -1}
              className={selected ? 'governance-tab active' : 'governance-tab'}
              onClick={() => navigateGovernance(area.key)}
              onKeyDown={(event) => handleTabKeyDown(event, index)}
            >
              <span>{area.label}</span>
              <span className="governance-tab-count">{pending}</span>
            </button>
          );
        })}
      </div>

      <section
        id={GOVERNANCE_PANEL_ID}
        className="governance-workspace"
        role="tabpanel"
        aria-labelledby={governanceTabId(route.area)}
      >
        {queue.status === 'loading' && (
          <div className="governance-state" role="status">
            Loading {activeDefinition.label}…
          </div>
        )}
        {queue.status === 'error' && (
          <div className="governance-state error" role="alert">
            Could not load {activeDefinition.label}:{' '}
            {formatApiErrorDetail(queue.error, 'Queue request failed')}
          </div>
        )}
        {queue.status === 'ready' && (
          <div className="governance-workspace-grid">
            <GovernanceQueue
              areaLabel={activeDefinition.label}
              adapter={activeAdapter}
              items={queue.items}
              total={queue.total}
              query={route.query || ''}
              nextCursor={queue.nextCursor}
              selectedId={route.itemId}
              focusTarget={queueFocusTarget}
              onFocusTargetHandled={clearQueueFocusTarget}
              onFilter={(query) =>
                navigateGovernance(route.area, null, { query })
              }
              onNextPage={() =>
                navigateGovernance(route.area, null, {
                  query: route.query,
                  cursor: queue.nextCursor,
                })
              }
              onSelect={(itemId) =>
                navigateGovernance(route.area, itemId, {
                  query: route.query,
                  cursor: route.cursor,
                })
              }
            />
            <section className="governance-detail" aria-label="Selected governance item">
              {route.itemId && (
                <button
                  type="button"
                  className="governance-narrow-back"
                  onClick={() => {
                    setQueueFocusTarget(route.itemId);
                    navigateGovernance(route.area, null, {
                      query: route.query,
                      cursor: route.cursor,
                    });
                  }}
                >
                  Back to {activeDefinition.label} queue
                </button>
              )}
              {detail.status === 'idle' && (
                <div className="governance-state empty">
                  Select an item to review its evidence and audit history.
                </div>
              )}
              {detail.status === 'loading' && (
                <div className="governance-state" role="status">
                  Loading selected item…
                </div>
              )}
              {detail.status === 'error' && (
                <div className="governance-state error" role="alert">
                  Could not load selected item:{' '}
                  {formatApiErrorDetail(detail.error, 'Detail request failed')}
                </div>
              )}
              {detail.status === 'ready' && (
                <>
                  {detail.partialErrors.length > 0 && (
                    <div className="governance-partial-warning" role="status">
                      <p>
                        Some detail sections are unavailable. Actions that require
                        missing governed targets are disabled.
                      </p>
                      <ul>
                        {detail.partialErrors.map((partialError) => (
                          <li key={partialError.section}>
                            {partialError.section}:{' '}
                            {formatApiErrorDetail(
                              partialError.error,
                              'Section request failed',
                            )}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  <EvidencePanel area={route.area} item={detail.item} />
                  {route.area === 'company-industries' && (
                    <CompanyIndustryContextPanel
                      tree={detail.resources.tree}
                      mappings={detail.resources.mappings}
                    />
                  )}
                  <RecommendationPanel
                    recommendations={
                      detail.recommendations.length > 0
                        ? detail.recommendations
                        : detail.item.recommendations || []
                    }
                  />
                  <section className="governance-panel">
                    <h2>Decision</h2>
                    <p className="governance-muted">
                      Every action requires explicit confirmation and the current
                      item version.
                    </p>
                    <div className="governance-decision-buttons">
                      {activeAdapter.actions.map((action) => (
                        <button
                          key={action.value}
                          type="button"
                          disabled={action.requiresTarget && detail.options.length === 0}
                          onClick={(event) => openDecision(action, event)}
                        >
                          {action.label}
                        </button>
                      ))}
                    </div>
                  </section>
                  <AuditTimeline events={detail.events} />
                </>
              )}
            </section>
          </div>
        )}
      </section>

      {decision && detail.item && (
        <DecisionDialog
          action={decision.action}
          affectedLabel={activeAdapter.affectedLabel(detail.item)}
          evidenceSummary={activeAdapter.evidenceSummary(detail.item)}
          options={detail.options}
          loadTargetChildren={activeAdapter.loadTargetChildren}
          targetBrowseLabel={activeAdapter.targetBrowseLabel}
          submitting={decision.submitting}
          error={decision.error}
          onCancel={closeDecision}
          onConfirm={confirmDecision}
        />
      )}
    </section>
  );
}
