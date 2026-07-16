import { formatPacingSummary, SCRAPER_PACING_SOURCES } from "../../api/scraperPacing";

export default function ScraperPacingSummary({ settings, sourceSite, loading, error, onOpenSettings }) {
  const sourceLabel =
    SCRAPER_PACING_SOURCES.find(({ value }) => value === sourceSite)?.label || sourceSite;
  const summary = formatPacingSummary(settings);

  return (
    <div className="override-summary-panel" data-testid="direct-override-pacing-summary">
      <span className="scheduler-panel-kicker">Saved Detail Pacing · {sourceLabel}</span>
      <strong className="override-summary-title">
        {loading ? "Loading saved pacing..." : error ? "Saved pacing unavailable" : "Applied when this task starts"}
      </strong>
      {summary ? (
        <div className="override-summary-metrics">
          {summary.map((metric) => <span key={metric} className="override-summary-chip">{metric}</span>)}
        </div>
      ) : null}
      <p className="form-hint">These global values are copied into a new detail task. Existing tasks do not change.</p>
      <button type="button" className="cyber-btn" onClick={onOpenSettings}>Open Scraper Pacing Settings</button>
    </div>
  );
}
