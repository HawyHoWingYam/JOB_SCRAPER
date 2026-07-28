import { useState } from "react";

const CATEGORY_COLORS = [
  "#6aa5ff",
  "#4fbf8b",
  "#e9b949",
  "#c084fc",
  "#f16f6f",
  "#5cc8be",
  "#a7afbc",
];

function formatUpdatedAt(value) {
  if (!value) return null;
  return new Date(value).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function CategoryRow({ item, index, onSelect }) {
  const color = CATEGORY_COLORS[index % CATEGORY_COLORS.length];
  const share = Number(item.share_of_assigned || 0);
  const count = Number(item.count || 0);

  return (
    <li>
      <button
        type="button"
        className="category-chart-row category-chart-row-action"
        aria-label={`View ${count.toLocaleString()} Jobs in ${item.path}`}
        onClick={() => onSelect?.(item)}
      >
        <span
          className="category-chart-swatch"
          style={{ backgroundColor: color }}
          aria-hidden="true"
        />
        <span className="category-chart-copy">
          <strong>{item.label}</strong>
          <small className="category-chart-path">{item.path}</small>
          <span
            className="category-chart-bar"
            role="meter"
            aria-label={`${item.path}: ${share}% of accepted assignments`}
            aria-valuemin="0"
            aria-valuemax="100"
            aria-valuenow={share}
          >
            <span style={{ width: `${share}%`, backgroundColor: color }} />
          </span>
          <small>{share}% of accepted assignments</small>
        </span>
        <span className="category-chart-value">{count.toLocaleString()}</span>
      </button>
    </li>
  );
}

export default function CategoryChart({
  data = null,
  loading = false,
  error = null,
  lastUpdated = null,
  onRetry,
  onSelectCategory,
}) {
  const [otherExpanded, setOtherExpanded] = useState(false);
  const topCategories = data?.top_categories || [];
  const otherCategories = data?.other_categories || {
    count: 0,
    bucket_count: 0,
    share_of_assigned: 0,
    items: [],
  };

  return (
    <section
      className="chart-container dashboard-category-chart"
      aria-labelledby="category-chart-title"
    >
      <div className="dashboard-chart-heading">
        <div>
          <h3 id="category-chart-title">Jobs by Canonical Job Taxonomy</h3>
          <p>
            Current accepted assignments across the retained operational Job
            corpus.
          </p>
        </div>
        {data ? (
          <div className="dashboard-chart-badge">
            {Number(data.assignment_coverage || 0)}% assigned
          </div>
        ) : null}
      </div>

      {loading && !data ? (
        <p className="dashboard-chart-status" role="status">
          Loading canonical assignments…
        </p>
      ) : null}
      {loading && data ? (
        <p className="dashboard-chart-status" role="status">
          Refreshing canonical assignments…
        </p>
      ) : null}
      {error ? (
        <div className="dashboard-chart-error" role="alert">
          <strong>
            {data ? "Taxonomy data is stale." : "Taxonomy data is unavailable."}
          </strong>
          <span>{error}</span>
          {data && lastUpdated ? (
            <span>Last successful update: {formatUpdatedAt(lastUpdated)}</span>
          ) : null}
          <button
            type="button"
            className="dashboard-inline-button"
            onClick={onRetry}
          >
            Retry taxonomy
          </button>
        </div>
      ) : null}

      {data ? (
        <div className="category-chart-stack">
          <div className="category-chart-summary-grid">
            <div className="category-chart-summary-card">
              <span>Accepted assignments</span>
              <strong>
                {Number(data.assigned_total || 0).toLocaleString()}
              </strong>
              <small>
                {Number(data.assignment_coverage || 0)}% of{" "}
                {Number(data.population_total || 0).toLocaleString()} retained
                Jobs.
              </small>
            </div>
            <div className="category-chart-summary-card category-chart-summary-card-alert">
              <span>Unassigned Jobs</span>
              <strong>
                {Number(data.unassigned_total || 0).toLocaleString()}
              </strong>
              <small>No current accepted Canonical Taxonomy Assignment.</small>
            </div>
            <div className="category-chart-summary-card">
              <span>Classification-ready</span>
              <strong>
                {Number(
                  data.classification_ready_unassigned_total || 0,
                ).toLocaleString()}
              </strong>
              <small>
                Unassigned Jobs with the source evidence required to attempt
                classification.
              </small>
            </div>
          </div>

          <div className="category-chart-main-panel">
            <div className="category-chart-section-header">
              <h4>Accepted Job Subcategory mix</h4>
              <p>
                Distribution within accepted assignments; unassigned Jobs stay
                in the coverage summary.
              </p>
            </div>

            {topCategories.length === 0 ? (
              <p className="chart-empty-state">
                No accepted Canonical Job Taxonomy assignments yet.
              </p>
            ) : (
              <ul className="category-chart-list">
                {topCategories.map((item, index) => (
                  <CategoryRow
                    key={item.code}
                    item={item}
                    index={index}
                    onSelect={onSelectCategory}
                  />
                ))}

                {Number(otherCategories.count || 0) > 0 ? (
                  <li className="category-chart-other">
                    <button
                      type="button"
                      className="category-chart-other-button"
                      aria-expanded={otherExpanded}
                      onClick={() => setOtherExpanded((current) => !current)}
                    >
                      <span>
                        Other ·{" "}
                        {Number(otherCategories.count || 0).toLocaleString()}{" "}
                        Jobs across {Number(otherCategories.bucket_count || 0)}{" "}
                        Job Subcategories
                      </span>
                      <strong>{otherExpanded ? "Collapse" : "Expand"}</strong>
                    </button>
                    {otherExpanded ? (
                      <ul className="category-chart-other-list">
                        {(otherCategories.items || []).map((item, index) => (
                          <CategoryRow
                            key={item.code}
                            item={item}
                            index={topCategories.length + index}
                            onSelect={onSelectCategory}
                          />
                        ))}
                      </ul>
                    ) : null}
                  </li>
                ) : null}
              </ul>
            )}
          </div>

          <p className="category-chart-footnote">
            Snapshot of all non-deleted acquired Jobs. Source listings may have
            expired; “current” refers to canonical assignment state, not an
            active opening.
          </p>
        </div>
      ) : null}
    </section>
  );
}
