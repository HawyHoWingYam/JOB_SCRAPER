import { useState, useEffect } from 'react';
import { Activity, Database, BrainCircuit, AlertTriangle, Clock3 } from 'lucide-react';
import SkillChart from './charts/SkillChart';
import CategoryChart from './charts/CategoryChart';
import { apiPath } from '../api/base';
import { fetchGovernanceSummary } from '../api/jobIntelligence';
import './Dashboard.css';

function humanizeGovernanceReason(value) {
  const words = String(value || 'unknown')
    .replaceAll('_', ' ')
    .trim();
  return words ? `${words.charAt(0).toUpperCase()}${words.slice(1)}` : 'Unknown';
}

function appHashForDeepLink(deepLink) {
  const normalized = String(deepLink || '').trim();
  if (!normalized) return '#job-intelligence/job-taxonomy';
  if (normalized.startsWith('#')) return normalized;
  return `#${normalized.replace(/^\/+/, '')}`;
}

export default function Dashboard({ onNavigateToAI }) {
  const [stats, setStats] = useState(null);
  const [aiOverview, setAiOverview] = useState(null);
  const [governanceSummary, setGovernanceSummary] = useState(null);
  const [governanceError, setGovernanceError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    Promise.allSettled([
      fetch(apiPath('/stats/overview')),
      fetch(apiPath('/ai/overview')),
      fetchGovernanceSummary(),
    ])
      .then(async ([statsResult, aiOverviewResult, governanceResult]) => {
        if (statsResult.status !== 'fulfilled') {
          throw statsResult.reason;
        }

        const statsResponse = statsResult.value;
        if (!statsResponse.ok) {
          throw new Error(`HTTP ${statsResponse.status}: ${statsResponse.statusText}`);
        }

        const statsPayload = await statsResponse.json();
        let aiOverviewPayload = { failed_jobs: null, failed_items: null };

        if (aiOverviewResult.status === 'fulfilled') {
          const aiOverviewResponse = aiOverviewResult.value;
          if (aiOverviewResponse.ok) {
            aiOverviewPayload = await aiOverviewResponse.json();
          }
        }

        if (governanceResult.status === 'fulfilled') {
          setGovernanceSummary(governanceResult.value);
          setGovernanceError(null);
        } else {
          setGovernanceSummary(null);
          setGovernanceError(
            governanceResult.reason?.message || 'Governance summary unavailable',
          );
        }

        setStats(statsPayload);
        setAiOverview(aiOverviewPayload);
      })
      .catch(err => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="dashboard-container">
        <header className="dashboard-header">
          <h2>Command Center</h2>
        </header>
        <div className="loading-state">
          <Activity className="spinner" size={32} />
          <p>Initializing Systems...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="dashboard-container">
        <header className="dashboard-header">
          <h2>Command Center</h2>
        </header>
        <div className="error-message glass-panel">
          System Error: Failed to load data streams ({error})
        </div>
      </div>
    );
  }

  const failedJobsValue = aiOverview?.failed_jobs == null
    ? (aiOverview?.failed_items == null ? null : Number(aiOverview.failed_items || 0))
    : Number(aiOverview.failed_jobs || 0);
  const totalJobs = Number(stats?.total_jobs || 0);
  const eligibleEnrichedJobs = Number(stats?.eligible_enriched_jobs ?? stats?.enriched_jobs ?? 0);
  const pendingEnrichment = Number(stats?.pending_enrichment || 0);
  const aiEligibleJobs = Number(stats?.ai_eligible_jobs || (eligibleEnrichedJobs + pendingEnrichment));
  const ineligibleJobs = Number(stats?.ineligible_jobs || Math.max(totalJobs - aiEligibleJobs, 0));
  const activeRunsCount = Number(aiOverview?.active_runs ?? aiOverview?.running_runs ?? 0);
  const hasAiEligibleCohort = aiEligibleJobs > 0;
  const enrichmentCoverage = hasAiEligibleCohort ? Math.round((eligibleEnrichedJobs / aiEligibleJobs) * 100) : null;
  const queuePressure = hasAiEligibleCohort ? Math.round((pendingEnrichment / aiEligibleJobs) * 100) : null;
  const governanceCoverage = governanceSummary?.coverage || null;
  const governanceReasons = Object.entries(
    governanceCoverage?.canonical_unassigned_reasons || {},
  );

  return (
    <div className="dashboard-container">
      <header className="dashboard-header">
        <div className="dashboard-header-copy">
          <h2>Command Center</h2>
          <p className="subtitle">Scrape volume, enrichment coverage, and queue posture.</p>
        </div>
        <button type="button" className="dashboard-link-button" onClick={onNavigateToAI}>
          Open AI Enrichment
        </button>
      </header>

      {stats && aiOverview && (
        <>
          <section className="dashboard-command-grid">
            <article className="dashboard-hero-panel glass-panel">
              <div className="dashboard-hero-copy">
                <p className="dashboard-panel-eyebrow">Operations Snapshot</p>
                <h3>Current operating posture</h3>
                <p>
                  Captured jobs, enrichment backlog, and failure pressure for the current dataset.
                </p>
              </div>

              <div className="dashboard-signal-grid">
                <div className="dashboard-signal-item">
                  <span>AI coverage</span>
                  <strong>{enrichmentCoverage == null ? 'N/A' : `${enrichmentCoverage}%`}</strong>
                  <small>
                    {hasAiEligibleCohort
                      ? `${eligibleEnrichedJobs.toLocaleString()} of ${aiEligibleJobs.toLocaleString()} AI-eligible jobs enriched`
                      : 'No AI-eligible jobs are in the current dataset.'}
                  </small>
                </div>
                <div className="dashboard-signal-item">
                  <span>Queue pressure</span>
                  <strong>{queuePressure == null ? 'N/A' : `${queuePressure}%`}</strong>
                  <small>
                    {hasAiEligibleCohort
                      ? `${pendingEnrichment.toLocaleString()} AI-eligible jobs still waiting for AI`
                      : 'Queue pressure is unavailable until AI-eligible jobs appear.'}
                  </small>
                </div>
                <div className="dashboard-signal-item">
                  <span>Failure watch</span>
                  <strong>
                    {failedJobsValue == null
                      ? 'N/A'
                      : failedJobsValue === 0
                        ? 'Clear'
                        : failedJobsValue.toLocaleString()}
                  </strong>
                  <small>
                    {failedJobsValue == null
                      ? 'AI failure telemetry is temporarily unavailable'
                      : failedJobsValue === 0
                        ? 'No failed jobs currently open'
                        : 'Queue attention required'}
                  </small>
                </div>
              </div>
            </article>

            <article className="dashboard-action-panel glass-panel">
              <p className="dashboard-panel-eyebrow">Next Action</p>
              <h3>Enrichment queue</h3>
              <p className="dashboard-action-copy">
                {pendingEnrichment > 0
                  ? `${pendingEnrichment.toLocaleString()} AI-eligible jobs are staged for AI processing. Use the enrichment console for batch runs and retry launches.`
                  : 'The AI-eligible enrichment backlog is clear. Use the console to verify recent runs and keep the queue healthy.'}
              </p>
              {ineligibleJobs > 0 && (
                <p className="dashboard-action-copy">
                  {ineligibleJobs.toLocaleString()} acquired jobs are not in the AI queue yet.
                </p>
              )}

              <div className="dashboard-action-meta">
                <div>
                  <span>Last completed run</span>
                  <strong>{aiOverview.last_completed_run?.id || 'No completed run yet'}</strong>
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
                <div className="stat-value">{stats.total_jobs.toLocaleString()}</div>
                <div className="stat-label">Total Jobs Acquired</div>
              </div>
            </div>

            <div className="stat-card glass-panel">
              <div className="stat-icon-wrapper purple-glow">
                <BrainCircuit size={24} className="stat-icon" />
              </div>
              <div className="stat-info">
                <div className="stat-value">{eligibleEnrichedJobs.toLocaleString()}</div>
                <div className="stat-label">AI-Eligible Jobs Enriched</div>
              </div>
            </div>

            <div className="stat-card glass-panel">
              <div className="stat-icon-wrapper green-glow">
                <Clock3 size={24} className="stat-icon" />
              </div>
              <div className="stat-info">
                <div className="stat-value">{stats.pending_enrichment.toLocaleString()}</div>
                <div className="stat-label">Pending AI-Eligible Jobs</div>
              </div>
            </div>

            <div className="stat-card glass-panel">
              <div className="stat-icon-wrapper green-glow">
                <AlertTriangle size={24} className="stat-icon" />
              </div>
              <div className="stat-info">
                <div className="stat-value">
                  {failedJobsValue == null ? 'N/A' : failedJobsValue.toLocaleString()}
                </div>
                <div className="stat-label">
                  {failedJobsValue == null ? 'Failed Jobs Unavailable' : 'Failed Jobs'}
                </div>
              </div>
            </div>
          </div>
        </>
      )}

      <section
        className="dashboard-governance-panel glass-panel"
        aria-label="Job Intelligence Governance"
      >
        <div className="dashboard-governance-header">
          <div>
            <p className="dashboard-panel-eyebrow">Governed Coverage</p>
            <h3>Job Intelligence Governance</h3>
            <p>
              Accepted knowledge, explicit Unassigned states, Unknown gaps, and review backlogs.
            </p>
          </div>
          {governanceSummary && (
            <span className="dashboard-governance-total">
              {Number(governanceSummary.total_pending || 0).toLocaleString()} pending
            </span>
          )}
        </div>

        {governanceError ? (
          <div className="dashboard-governance-degraded" role="status">
            Governance coverage is temporarily unavailable. Operational metrics remain current.
          </div>
        ) : governanceCoverage ? (
          <>
            <div className="dashboard-governance-metrics">
              <div aria-label="Canonical assignments">
                <span>Canonical assignments</span>
                <strong>
                  {Number(governanceCoverage.jobs_with_canonical_assignment || 0).toLocaleString()}
                  {' of '}
                  {Number(governanceCoverage.total_jobs || 0).toLocaleString()}
                </strong>
                <small>Accepted Canonical Job Taxonomy assignments</small>
              </div>
              <div aria-label="Unassigned jobs">
                <span>Unassigned</span>
                <strong>
                  {Number(governanceCoverage.jobs_with_unassigned_canonical_state || 0).toLocaleString()}
                </strong>
                <small>Jobs with explicit review evidence and no accepted assignment</small>
              </div>
              <div aria-label="Unknown jobs">
                <span>Unknown</span>
                <strong>
                  {Number(governanceCoverage.jobs_with_unknown_canonical_state || 0).toLocaleString()}
                </strong>
                <small>Jobs with neither an accepted assignment nor an active review state</small>
              </div>
              <div>
                <span>Governed Skills</span>
                <strong>
                  {Number(governanceCoverage.jobs_with_governed_skills || 0).toLocaleString()}
                  {' of '}
                  {Number(governanceCoverage.total_jobs || 0).toLocaleString()}
                </strong>
                <small>Jobs with at least one governed Skill</small>
              </div>
              <div>
                <span>Company Industries</span>
                <strong>
                  {Number(governanceCoverage.companies_with_governed_industries || 0).toLocaleString()}
                  {' of '}
                  {Number(governanceCoverage.total_companies || 0).toLocaleString()}
                </strong>
                <small>Companies with governed Industry assignments</small>
              </div>
            </div>

            <div className="dashboard-governance-detail-grid">
              <div>
                <h4>Unassigned reasons</h4>
                {governanceReasons.length > 0 ? (
                  <ul className="dashboard-governance-reasons">
                    {governanceReasons.map(([reason, count]) => (
                      <li key={reason}>
                        <span>{humanizeGovernanceReason(reason)}</span>
                        <strong>{Number(count || 0).toLocaleString()} evidence flags</strong>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p>No active Unassigned reasons.</p>
                )}
              </div>

              <nav aria-label="Governance review backlogs">
                <h4>Review backlogs</h4>
                <div className="dashboard-governance-links">
                  {(governanceSummary.areas || []).map((area) => (
                    <a key={area.key} href={appHashForDeepLink(area.deep_link)}>
                      <span>{area.label}</span>
                      <strong>
                        {area.available
                          ? `${Number(area.pending_count || 0).toLocaleString()} pending`
                          : 'Unavailable'}
                      </strong>
                    </a>
                  ))}
                </div>
              </nav>
            </div>
          </>
        ) : (
          <div className="dashboard-governance-degraded" role="status">
            Loading governed coverage…
          </div>
        )}
      </section>

      <div className="charts-grid">
        <div className="chart-wrapper glass-panel dashboard-chart-panel">
          <SkillChart />
        </div>
        <div className="chart-wrapper glass-panel dashboard-chart-panel">
          <CategoryChart totalJobs={stats?.total_jobs || 0} />
        </div>
      </div>
    </div>
  );
}
