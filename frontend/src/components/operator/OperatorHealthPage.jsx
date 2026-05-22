import { useCallback, useEffect, useState } from 'react';
import { Activity, AlertTriangle, Clock3, RefreshCcw, ShieldCheck } from 'lucide-react';
import { fetchOperatorHealth } from '../../api/operatorHealth';
import '../Dashboard.css';
import './OperatorHealthPage.css';

const UNAVAILABLE_LABEL = 'Unavailable';

function formatTimestamp(value) {
  if (!value) {
    return UNAVAILABLE_LABEL;
  }

  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) {
    return String(value);
  }

  return new Date(parsed).toLocaleString('en-US');
}

function formatBoolean(value) {
  if (value == null) {
    return UNAVAILABLE_LABEL;
  }

  return value ? 'Yes' : 'No';
}

function formatValue(value) {
  if (value == null || value === '') {
    return UNAVAILABLE_LABEL;
  }

  if (typeof value === 'number') {
    return value.toLocaleString();
  }

  return String(value);
}

function SummaryCard({ label, value, icon: Icon }) {
  return (
    <article className="stat-card glass-panel operator-health-stat-card">
      <div className="stat-icon-wrapper blue-glow">
        <Icon size={24} className="stat-icon" />
      </div>
      <div className="stat-info">
        <div className="stat-value">{formatValue(value)}</div>
        <div className="stat-label">{label}</div>
      </div>
    </article>
  );
}

function SummaryList({ items }) {
  return (
    <dl className="operator-health-summary-list">
      {items.map(({ label, value }) => (
        <div key={label} className="operator-health-summary-row">
          <dt>{label}</dt>
          <dd>{formatValue(value)}</dd>
        </div>
      ))}
    </dl>
  );
}

export default function OperatorHealthPage() {
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const loadOperatorHealth = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const payload = await fetchOperatorHealth();
      setHealth(payload);
    } catch (err) {
      setError(err?.message || 'Unknown error');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadOperatorHealth();
  }, [loadOperatorHealth]);

  const issues = Array.isArray(health?.issues) ? health.issues : [];
  const scheduler = health?.scheduler || null;
  const headedRuntime = health?.headed_runtime || null;
  const backlogs = health?.backlogs || null;
  const hasPayload = health !== null;
  const showUnavailableState = Boolean(error) && !hasPayload;

  return (
    <section className="dashboard-container operator-health-page">
      <header className="dashboard-header">
        <div>
          <h2>Operator Health</h2>
          <p className="subtitle">
            Unified runtime posture for scheduler automation, headed scraping, and backlog pressure.
          </p>
        </div>
        <button
          type="button"
          className="dashboard-link-button operator-health-refresh-button"
          onClick={loadOperatorHealth}
          disabled={loading}
        >
          <RefreshCcw size={16} className={loading ? 'operator-health-refresh-spin' : ''} />
          <span>Refresh</span>
        </button>
      </header>

      {error && (
        <div className="error-message glass-panel operator-health-error-banner">
          <AlertTriangle size={18} />
          <span>Failed to load operator health: {error}</span>
        </div>
      )}

      <div className="stats-grid">
        <SummaryCard
          label="Overall Status"
          value={health?.status || (loading ? 'Loading...' : UNAVAILABLE_LABEL)}
          icon={ShieldCheck}
        />
        <article className="stat-card glass-panel operator-health-stat-card">
          <div className="stat-icon-wrapper purple-glow">
            <Clock3 size={24} className="stat-icon" />
          </div>
          <div className="stat-info">
            <div className="stat-value operator-health-timestamp">
              <time data-testid="operator-health-last-updated" dateTime={health?.generated_at || ''}>
                {loading && !health ? 'Loading...' : formatTimestamp(health?.generated_at)}
              </time>
            </div>
            <div className="stat-label">Last Updated</div>
          </div>
        </article>
      </div>

      {loading && !health && (
        <div className="loading-state">
          <Activity className="spinner" size={32} />
          <p>Loading operator telemetry...</p>
        </div>
      )}

      {showUnavailableState && (
        <div className="glass-panel operator-health-panel operator-health-panel-wide" role="status" aria-live="polite">
          <div className="operator-health-panel-header">
            <h3>Operator Data Unavailable</h3>
          </div>
          <p className="operator-health-empty-state">
            Operator health data is currently unavailable. Refresh to try again.
          </p>
        </div>
      )}

      {hasPayload && (
        <div className="operator-health-grid">
          <section
            className="glass-panel operator-health-panel operator-health-panel-wide"
            aria-label="Issues"
            role="region"
          >
            <div className="operator-health-panel-header">
              <h3>Issues</h3>
              <span className={`operator-health-badge ${issues.length > 0 ? 'is-warning' : 'is-ok'}`}>
                {issues.length > 0 ? `${issues.length} active` : 'Clear'}
              </span>
            </div>

            {issues.length > 0 ? (
              <ul className="operator-health-issue-list">
                {issues.map((issue) => (
                  <li key={issue}>{issue}</li>
                ))}
              </ul>
            ) : (
              <p className="operator-health-empty-state">No active issues reported.</p>
            )}
          </section>

          <section className="glass-panel operator-health-panel" aria-label="Scheduler Summary" role="region">
            <div className="operator-health-panel-header">
              <h3>Scheduler Summary</h3>
            </div>
            <SummaryList
              items={[
                { label: 'Heartbeat status', value: scheduler?.heartbeat_status },
                { label: 'Automation available', value: formatBoolean(scheduler?.available) },
                { label: 'Manual run available', value: formatBoolean(scheduler?.manual_run_available) },
                { label: 'Last heartbeat', value: formatTimestamp(scheduler?.last_heartbeat_at) },
                { label: 'Last reconcile', value: formatTimestamp(scheduler?.last_reconcile_at) },
                { label: 'Active schedules', value: scheduler?.active_schedule_count },
                { label: 'Registered jobs', value: scheduler?.registered_job_count },
                { label: 'Reason', value: scheduler?.reason },
              ]}
            />
          </section>

          <section className="glass-panel operator-health-panel" aria-label="Headed Runtime Summary" role="region">
            <div className="operator-health-panel-header">
              <h3>Headed Runtime Summary</h3>
            </div>
            <SummaryList
              items={[
                { label: 'Worker status', value: headedRuntime?.worker_status },
                { label: 'Browser channel', value: headedRuntime?.browser_channel },
                { label: 'Runtime configured', value: formatBoolean(headedRuntime?.configured) },
                {
                  label: 'User data dir configured',
                  value: formatBoolean(headedRuntime?.browser_user_data_dir_configured),
                },
                {
                  label: 'User data dir exists',
                  value: formatBoolean(headedRuntime?.browser_user_data_dir_exists),
                },
                { label: 'Worker group', value: headedRuntime?.worker_group },
                { label: 'Lock port', value: headedRuntime?.lock_port },
                { label: 'Reason', value: headedRuntime?.reason },
              ]}
            />
          </section>

          <section
            className="glass-panel operator-health-panel operator-health-panel-wide"
            aria-label="Backlog Metrics"
            role="region"
          >
            <div className="operator-health-panel-header">
              <h3>Backlog Metrics</h3>
            </div>
            <SummaryList
              items={[
                { label: 'Pending detail rows', value: backlogs?.pending_detail_rows },
                { label: 'Failed detail rows', value: backlogs?.failed_detail_rows },
                { label: 'Manual action detail rows', value: backlogs?.manual_action_detail_rows },
                { label: 'Outbox pending', value: backlogs?.outbox_pending },
                { label: 'Outbox failed', value: backlogs?.outbox_failed },
                { label: 'Dead letter count', value: backlogs?.dead_letter_count },
                { label: 'Missing current embeddings', value: backlogs?.missing_current_embeddings },
                { label: 'AI backlog jobs', value: backlogs?.ai_backlog_jobs },
              ]}
            />
          </section>
        </div>
      )}
    </section>
  );
}
