import { useEffect, useState } from 'react';
import { apiPath } from '../../api/base';


const CATEGORY_COLORS = [
  '#6aa5ff',
  '#4fbf8b',
  '#e9b949',
  '#c084fc',
  '#f16f6f',
  '#5cc8be',
  '#a7afbc',
];

function formatShare(value, total) {
  if (!total) {
    return '0%';
  }
  return `${Math.round((value / total) * 100)}%`;
}

function resolveSharePercentage(explicitShare, value, total) {
  const numericShare = Number(explicitShare);
  if (Number.isFinite(numericShare) && numericShare >= 0) {
    return numericShare;
  }

  if (!total) {
    return 0;
  }

  return Math.round((Number(value || 0) / total) * 100);
}

export default function CategoryChart({ totalJobs = 0 }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetch(apiPath('/stats/categories/dashboard'))
      .then((res) => {
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }
        return res.json();
      })
      .then(setData)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div
        style={{
          height: '300px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: 'var(--color-primary)',
        }}
      >
        Loading categorization...
      </div>
    );
  }

  if (error) {
    return (
      <div className="chart-container dashboard-category-chart">
        <div className="dashboard-chart-heading">
          <div>
            <h3>Jobs by Canonical Job Taxonomy</h3>
            <p>Only current accepted assignments from the active governed revision are included.</p>
          </div>
        </div>
        <div className="error-message">Failed to load categories: {error}</div>
      </div>
    );
  }

  const categorizedTotal = Number(data?.categorized_total || 0);
  const specificTotal = Number(data?.specific_total || 0);
  const topSpecificCategories = data?.top_specific_categories || [];
  const otherSpecificCategories = data?.other_specific_categories || {
    count: 0,
    bucket_count: 0,
    share_of_specific: 0,
  };

  return (
    <div className="chart-container dashboard-category-chart">
      <div className="dashboard-chart-heading">
        <div>
          <h3>Jobs by Canonical Job Taxonomy</h3>
          <p>Only current accepted assignments from the active governed revision are included.</p>
        </div>
        <div className="dashboard-chart-badge">
          {categorizedTotal.toLocaleString()} accepted
        </div>
      </div>

      {topSpecificCategories.length === 0 ? (
        <p className="chart-empty-state">
          No accepted Canonical Job Taxonomy assignments yet.
        </p>
      ) : (
        <div className="category-chart-stack">
          <div className="category-chart-summary-grid">
            <div className="category-chart-summary-card">
              <span>Accepted assignments</span>
              <strong>{specificTotal.toLocaleString()}</strong>
              <small>{formatShare(specificTotal, categorizedTotal)} of the accepted assignment set</small>
            </div>
          </div>

          <div className="category-chart-main-panel">
            <div className="category-chart-section-header">
              <h4>Accepted Job Subcategory mix</h4>
              <p>Unassigned, Unknown, raw, and fallback evidence is excluded from this ranking.</p>
            </div>

            <div className="category-chart-list">
              {topSpecificCategories.map((item, index) => {
                const color = CATEGORY_COLORS[index % CATEGORY_COLORS.length];
                const share = resolveSharePercentage(item.share_of_specific, item.count, specificTotal);

                return (
                  <div key={item.path} className="category-chart-row">
                    <span
                      className="category-chart-swatch"
                      style={{ backgroundColor: color }}
                      aria-hidden="true"
                    />

                    <div className="category-chart-copy">
                      <strong title={item.path}>{item.label}</strong>
                      <div className="category-chart-bar">
                        <span style={{ width: `${share}%`, backgroundColor: color }} />
                      </div>
                      <small>{share}% of accepted assignments</small>
                    </div>

                    <span className="category-chart-value">{Number(item.count || 0).toLocaleString()}</span>
                  </div>
                );
              })}

              {Number(otherSpecificCategories.count || 0) > 0 && (
                <div className="category-chart-row category-chart-row-muted">
                  {(() => {
                    const otherSpecificShare = resolveSharePercentage(
                      otherSpecificCategories.share_of_specific,
                      otherSpecificCategories.count,
                      specificTotal,
                    );

                    return (
                      <>
                  <span className="category-chart-swatch category-chart-swatch-muted" aria-hidden="true" />
                  <div className="category-chart-copy">
                    <strong>Other specific categories</strong>
                    <div className="category-chart-bar">
                      <span
                        style={{
                          width: `${otherSpecificShare}%`,
                          backgroundColor: 'rgba(148, 163, 184, 0.9)',
                        }}
                      />
                    </div>
                    <small>
                      {otherSpecificShare}% across{' '}
                      {Number(otherSpecificCategories.bucket_count || 0)} Job Subcategories
                    </small>
                  </div>
                  <span className="category-chart-value">
                    {Number(otherSpecificCategories.count || 0).toLocaleString()}
                  </span>
                      </>
                    );
                  })()}
                </div>
              )}
            </div>
          </div>

          {totalJobs > 0 && (
            <p className="category-chart-footnote">
              {categorizedTotal.toLocaleString()} of {Number(totalJobs || 0).toLocaleString()} total jobs currently have a current accepted Canonical Job Taxonomy assignment.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
