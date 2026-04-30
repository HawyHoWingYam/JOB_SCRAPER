import { useState, useEffect } from 'react';
import { Activity, Database, BrainCircuit, AlertTriangle, Clock3 } from 'lucide-react';
import SkillChart from './charts/SkillChart';
import CategoryChart from './charts/CategoryChart';
import './Dashboard.css';

const API_URL = import.meta.env.VITE_API_URL || '';

export default function Dashboard({ onNavigateToAI }) {
  const [stats, setStats] = useState(null);
  const [aiOverview, setAiOverview] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    Promise.allSettled([
      fetch(`${API_URL}/api/v1/stats/overview`),
      fetch(`${API_URL}/api/v1/ai/overview`),
    ])
      .then(async ([statsResult, aiOverviewResult]) => {
        if (statsResult.status !== 'fulfilled') {
          throw statsResult.reason;
        }

        const statsResponse = statsResult.value;
        if (!statsResponse.ok) {
          throw new Error(`HTTP ${statsResponse.status}: ${statsResponse.statusText}`);
        }

        const statsPayload = await statsResponse.json();
        let aiOverviewPayload = { failed_items: null };

        if (aiOverviewResult.status === 'fulfilled') {
          const aiOverviewResponse = aiOverviewResult.value;
          if (aiOverviewResponse.ok) {
            aiOverviewPayload = await aiOverviewResponse.json();
          }
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

  const failedItemsValue = aiOverview?.failed_items == null ? null : Number(aiOverview.failed_items || 0);
  const totalJobs = Number(stats?.total_jobs || 0);
  const enrichedJobs = Number(stats?.enriched_jobs || 0);
  const pendingEnrichment = Number(stats?.pending_enrichment || 0);
  const enrichmentCoverage = totalJobs > 0 ? Math.round((enrichedJobs / totalJobs) * 100) : 0;
  const queuePressure = totalJobs > 0 ? Math.round((pendingEnrichment / totalJobs) * 100) : 0;

  return (
    <div className="dashboard-container">
      <header className="dashboard-header">
        <div className="dashboard-header-copy">
          <h2>Command Center</h2>
          <p className="subtitle">Real-time scraping and analytics overview</p>
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
                <h3>Signal over noise</h3>
                <p>
                  The dashboard now keeps the queue posture, enrichment coverage, and failure watch in one place before
                  you dive into the detailed consoles.
                </p>
              </div>

              <div className="dashboard-signal-grid">
                <div className="dashboard-signal-item">
                  <span>AI coverage</span>
                  <strong>{enrichmentCoverage}%</strong>
                  <small>{enrichedJobs.toLocaleString()} of {totalJobs.toLocaleString()} profiles enriched</small>
                </div>
                <div className="dashboard-signal-item">
                  <span>Queue pressure</span>
                  <strong>{queuePressure}%</strong>
                  <small>{pendingEnrichment.toLocaleString()} profiles still waiting for AI</small>
                </div>
                <div className="dashboard-signal-item">
                  <span>Failure watch</span>
                  <strong>
                    {failedItemsValue == null
                      ? 'N/A'
                      : failedItemsValue === 0
                        ? 'Clear'
                        : failedItemsValue.toLocaleString()}
                  </strong>
                  <small>
                    {failedItemsValue == null
                      ? 'AI failure telemetry is temporarily unavailable'
                      : failedItemsValue === 0
                        ? 'No failed items currently open'
                        : 'Queue attention required'}
                  </small>
                </div>
              </div>
            </article>

            <article className="dashboard-action-panel glass-panel">
              <p className="dashboard-panel-eyebrow">Next Action</p>
              <h3>Open the enrichment console</h3>
              <p className="dashboard-action-copy">
                {pendingEnrichment > 0
                  ? `${pendingEnrichment.toLocaleString()} profiles are staged for AI processing. Use the enrichment console for batch runs and retry launches.`
                  : 'The enrichment backlog is clear. Use the console to verify recent runs and keep the queue healthy.'}
              </p>

              <div className="dashboard-action-meta">
                <div>
                  <span>Last completed run</span>
                  <strong>{aiOverview.last_completed_run?.id || 'No completed run yet'}</strong>
                </div>
                <div>
                  <span>Running runs</span>
                  <strong>{Number(aiOverview.running_runs || 0).toLocaleString()}</strong>
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
                <div className="stat-value">{stats.enriched_jobs.toLocaleString()}</div>
                <div className="stat-label">AI Enriched Profiles</div>
              </div>
            </div>

            <div className="stat-card glass-panel">
              <div className="stat-icon-wrapper green-glow">
                <Clock3 size={24} className="stat-icon" />
              </div>
              <div className="stat-info">
                <div className="stat-value">{stats.pending_enrichment.toLocaleString()}</div>
                <div className="stat-label">Pending Enrichment</div>
              </div>
            </div>

            <div className="stat-card glass-panel">
              <div className="stat-icon-wrapper green-glow">
                <AlertTriangle size={24} className="stat-icon" />
              </div>
              <div className="stat-info">
                <div className="stat-value">
                  {failedItemsValue == null ? 'N/A' : failedItemsValue.toLocaleString()}
                </div>
                <div className="stat-label">
                  {failedItemsValue == null ? 'Failed Items Unavailable' : 'Failed Items'}
                </div>
              </div>
            </div>
          </div>
        </>
      )}

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
