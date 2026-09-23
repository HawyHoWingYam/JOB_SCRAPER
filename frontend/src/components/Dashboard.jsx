import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  BrainCircuit,
  Clock3,
  Database,
  RefreshCw,
} from "lucide-react";
import SkillChart from "./charts/SkillChart";
import { apiPath } from "../api/base";
import "./Dashboard.css";

const SECTION_ENDPOINTS = {
  overview: "/stats/overview",
  aiOverview: "/ai/overview",
  skills: "/stats/skills?limit=30",
};

function initialSections() {
  return Object.fromEntries(
    Object.keys(SECTION_ENDPOINTS).map((key) => [
      key,
      { data: null, error: null, loading: true, lastUpdated: null },
    ]),
  );
}

function formatUpdatedAt(value) {
  if (!value) return null;
  return new Date(value).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export default function Dashboard({
  onNavigateToAI,
  onNavigateToClassification,
  onNavigateToJobs,
}) {
  const [sections, setSections] = useState(initialSections);
  const controllersRef = useRef(new Map());
  const mountedRef = useRef(false);

  const loadSection = useCallback(async (key) => {
    const previousController = controllersRef.current.get(key);
    if (previousController) previousController.abort();

    const controller = new AbortController();
    controllersRef.current.set(key, controller);
    setSections((current) => ({
      ...current,
      [key]: { ...current[key], loading: true, error: null },
    }));

    try {
      const response = await fetch(apiPath(SECTION_ENDPOINTS[key]), {
        signal: controller.signal,
      });
      if (!response.ok) {
        throw new Error(
          `HTTP ${response.status}: ${response.statusText || "Request failed"}`,
        );
      }
      const payload = await response.json();
      if (!mountedRef.current) return;
      setSections((current) => ({
        ...current,
        [key]: {
          data: payload,
          error: null,
          loading: false,
          lastUpdated: Date.now(),
        },
      }));
    } catch (error) {
      if (error?.name === "AbortError" || !mountedRef.current) return;
      setSections((current) => ({
        ...current,
        [key]: {
          ...current[key],
          error: error?.message || "Request failed",
          loading: false,
        },
      }));
    } finally {
      if (controllersRef.current.get(key) === controller) {
        controllersRef.current.delete(key);
      }
    }
  }, []);

  const refreshAll = useCallback(
    () =>
      Promise.allSettled(
        Object.keys(SECTION_ENDPOINTS).map((key) => loadSection(key)),
      ),
    [loadSection],
  );

  useEffect(() => {
    const controllers = controllersRef.current;
    mountedRef.current = true;
    refreshAll();
    return () => {
      mountedRef.current = false;
      controllers.forEach((controller) => controller.abort());
      controllers.clear();
    };
  }, [refreshAll]);

  const isRefreshing = Object.values(sections).some(
    (section) => section.loading,
  );
  const hasSectionError = Object.values(sections).some(
    (section) => section.error,
  );
  const latestSuccessfulUpdate = useMemo(() => {
    const values = Object.values(sections)
      .map((section) => section.lastUpdated)
      .filter(Boolean);
    return values.length > 0 ? Math.max(...values) : null;
  }, [sections]);

  const statsSection = sections.overview;
  const aiSection = sections.aiOverview;
  const stats = statsSection.data;
  const aiOverview = aiSection.data || {};
  const failedJobsValue =
    aiOverview?.failed_jobs == null
      ? aiOverview?.failed_items == null
        ? null
        : Number(aiOverview.failed_items || 0)
      : Number(aiOverview.failed_jobs || 0);
  const totalJobs = Number(stats?.total_jobs || 0);
  const eligibleEnrichedJobs = Number(
    stats?.eligible_enriched_jobs ?? stats?.enriched_jobs ?? 0,
  );
  const pendingEnrichment = Number(stats?.pending_enrichment || 0);
  const aiEligibleJobs = Number(
    stats?.ai_eligible_jobs || eligibleEnrichedJobs + pendingEnrichment,
  );
  const ineligibleJobs = Number(
    stats?.ineligible_jobs || Math.max(totalJobs - aiEligibleJobs, 0),
  );
  const activeRunsCount = Number(
    aiOverview?.active_runs ?? aiOverview?.running_runs ?? 0,
  );
  const hasAiEligibleCohort = aiEligibleJobs > 0;
  const enrichmentCoverage = hasAiEligibleCohort
    ? Math.round((eligibleEnrichedJobs / aiEligibleJobs) * 100)
    : null;
  const queuePressure = hasAiEligibleCohort
    ? Math.round((pendingEnrichment / aiEligibleJobs) * 100)
    : null;

  return (
    <div className="dashboard-container" aria-busy={isRefreshing}>
      <header className="dashboard-header">
        <div className="dashboard-header-copy">
          <h2>Command Center</h2>
          <p className="subtitle">
            Review collected jobs, enrichment progress, and Skills that need attention.
          </p>
          <p className="dashboard-refresh-status" role="status">
            {isRefreshing
              ? "Refreshing Dashboard…"
              : hasSectionError
                ? "Refresh completed with stale sections."
                : latestSuccessfulUpdate
                  ? `Last refreshed at ${formatUpdatedAt(latestSuccessfulUpdate)}`
                  : "Dashboard has not loaded yet."}
          </p>
        </div>
        <div className="dashboard-header-actions">
          <button
            type="button"
            className="dashboard-refresh-button"
            onClick={refreshAll}
            disabled={isRefreshing}
          >
            <RefreshCw size={16} aria-hidden="true" />
            Refresh
          </button>
          <button
            type="button"
            className="dashboard-link-button"
            onClick={onNavigateToAI}
          >
            Open AI Enrichment
          </button>
        </div>
      </header>

      {statsSection.loading && !stats ? (
        <div className="dashboard-section-status glass-panel" role="status">
          <Activity className="spinner" size={28} />
          <p>Loading operational overview…</p>
        </div>
      ) : null}

      {statsSection.error ? (
        <div className="dashboard-section-error glass-panel" role="alert">
          <strong>
            {stats
              ? "Operational overview is stale."
              : "Operational overview is unavailable."}
          </strong>
          <span>{statsSection.error}</span>
          {stats && statsSection.lastUpdated ? (
            <span>
              Last successful update:{" "}
              {formatUpdatedAt(statsSection.lastUpdated)}
            </span>
          ) : null}
          <button
            type="button"
            className="dashboard-inline-button"
            onClick={() => loadSection("overview")}
          >
            Retry overview
          </button>
        </div>
      ) : null}

      {stats ? (
        <>
          <section
            className="dashboard-command-grid"
            aria-label="Operations snapshot"
          >
            <article className="dashboard-hero-panel glass-panel">
              <div className="dashboard-hero-copy">
                <p className="dashboard-panel-eyebrow">Operations Snapshot</p>
                <h3>Current operating posture</h3>
                <p>
                  Captured Jobs, enrichment backlog, and failure pressure for
                  the retained corpus.
                </p>
              </div>

              <div className="dashboard-signal-grid">
                <div className="dashboard-signal-item">
                  <span>AI coverage</span>
                  <strong>
                    {enrichmentCoverage == null
                      ? "N/A"
                      : `${enrichmentCoverage}%`}
                  </strong>
                  <small>
                    {hasAiEligibleCohort
                      ? `${eligibleEnrichedJobs.toLocaleString()} of ${aiEligibleJobs.toLocaleString()} AI-eligible Jobs enriched`
                      : "No AI-eligible Jobs are in the current corpus."}
                  </small>
                </div>
                <div className="dashboard-signal-item">
                  <span>Queue pressure</span>
                  <strong>
                    {queuePressure == null ? "N/A" : `${queuePressure}%`}
                  </strong>
                  <small>
                    {hasAiEligibleCohort
                      ? `${pendingEnrichment.toLocaleString()} AI-eligible Jobs still waiting for AI`
                      : "Queue pressure is unavailable until AI-eligible Jobs appear."}
                  </small>
                </div>
                <div className="dashboard-signal-item">
                  <span>Failure watch</span>
                  <strong>
                    {failedJobsValue == null
                      ? "N/A"
                      : failedJobsValue === 0
                        ? "Clear"
                        : failedJobsValue.toLocaleString()}
                  </strong>
                  <small>
                    {failedJobsValue == null
                      ? "AI failure telemetry is unavailable"
                      : failedJobsValue === 0
                        ? "No failed Jobs currently open"
                        : "Queue attention required"}
                  </small>
                </div>
              </div>
            </article>

            <article className="dashboard-action-panel glass-panel">
              <p className="dashboard-panel-eyebrow">Next Action</p>
              <h3>Enrichment queue</h3>
              {aiSection.error ? (
                <div className="dashboard-compact-error" role="alert">
                  AI run telemetry{" "}
                  {aiSection.data ? "is stale" : "failed to load"}:{" "}
                  {aiSection.error}
                  <button
                    type="button"
                    className="dashboard-inline-button"
                    onClick={() => loadSection("aiOverview")}
                  >
                    Retry AI telemetry
                  </button>
                </div>
              ) : null}
              <p className="dashboard-action-copy">
                {pendingEnrichment > 0
                  ? `${pendingEnrichment.toLocaleString()} AI-eligible Jobs are staged for AI processing.`
                  : "The AI-eligible enrichment backlog is clear."}
              </p>
              {ineligibleJobs > 0 ? (
                <p className="dashboard-action-copy">
                  {ineligibleJobs.toLocaleString()} acquired Jobs are not in the
                  AI queue yet.
                </p>
              ) : null}

              <div className="dashboard-action-meta">
                <div>
                  <span>Last completed run</span>
                  <strong>
                    {aiOverview.last_completed_run?.id ||
                      "No completed run yet"}
                  </strong>
                </div>
                <div>
                  <span>Active runs</span>
                  <strong>{activeRunsCount.toLocaleString()}</strong>
                </div>
              </div>
            </article>
          </section>

          <div className="stats-grid">
            <div className="stat-card glass-panel">
              <div className="stat-icon-wrapper blue-glow">
                <Database size={24} className="stat-icon" />
              </div>
              <div className="stat-info">
                <div className="stat-value">{totalJobs.toLocaleString()}</div>
                <div className="stat-label">Total Jobs Acquired</div>
              </div>
            </div>
            <div className="stat-card glass-panel">
              <div className="stat-icon-wrapper purple-glow">
                <BrainCircuit size={24} className="stat-icon" />
              </div>
              <div className="stat-info">
                <div className="stat-value">
                  {eligibleEnrichedJobs.toLocaleString()}
                </div>
                <div className="stat-label">AI-Eligible Jobs Enriched</div>
              </div>
            </div>
            <div className="stat-card glass-panel">
              <div className="stat-icon-wrapper green-glow">
                <Clock3 size={24} className="stat-icon" />
              </div>
              <div className="stat-info">
                <div className="stat-value">
                  {pendingEnrichment.toLocaleString()}
                </div>
                <div className="stat-label">Pending AI-Eligible Jobs</div>
              </div>
            </div>
            <div className="stat-card glass-panel">
              <div className="stat-icon-wrapper green-glow">
                <AlertTriangle size={24} className="stat-icon" />
              </div>
              <div className="stat-info">
                <div className="stat-value">
                  {failedJobsValue == null
                    ? "N/A"
                    : failedJobsValue.toLocaleString()}
                </div>
                <div className="stat-label">
                  {failedJobsValue == null
                    ? "Failed Jobs Unavailable"
                    : "Failed Jobs"}
                </div>
              </div>
            </div>
          </div>
        </>
      ) : null}

      <div className="charts-grid">
        <div className="chart-wrapper glass-panel dashboard-chart-panel">
          <SkillChart
            {...sections.skills}
            onRetry={() => loadSection("skills")}
            onOpenClassification={() =>
              onNavigateToClassification?.("skill")
            }
            onSelectSkill={(skill) =>
              onNavigateToJobs?.({ skillIds: [skill.code] })
            }
          />
        </div>
      </div>
    </div>
  );
}
