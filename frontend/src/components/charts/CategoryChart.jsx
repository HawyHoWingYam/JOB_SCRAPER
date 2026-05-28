import { useEffect, useState } from 'react';
import { API_BASE_URL } from '../../api/base';

const API_URL = API_BASE_URL;

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

function formatFallbackInsight(bucket) {
  if (!bucket?.source_breakdown?.length) {
    return 'Fallback bucket includes jobs that could not be classified into a more specific governed path.';
  }

  const primary = bucket.source_breakdown[0];
  const primaryShare = formatShare(primary.count, bucket.count);

  if (primary.source_site === 'ctgoodjobs' && primary.source_subclassification_name == null) {
    return `${primaryShare} of this fallback bucket comes from CTGoodJobs rows without a source subcategory.`;
  }

  if (primary.source_subclassification_name) {
    return `${primaryShare} of this fallback bucket comes from ${primary.source_site || 'unknown source'} / ${primary.source_subclassification_name}.`;
  }

  return `${primaryShare} of this fallback bucket comes from ${primary.source_site || 'unknown source'} rows without a source subcategory.`;
}

function formatSourceBreakdownItem(item, total) {
  const share = formatShare(item.count, total);
  if (item.source_subclassification_name) {
    return `${item.source_site || 'Unknown'} / ${item.source_subclassification_name}: ${item.count.toLocaleString()} (${share})`;
  }
  return `${item.source_site || 'Unknown'} / no source subcategory: ${item.count.toLocaleString()} (${share})`;
}

export default function CategoryChart({ totalJobs = 0 }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetch(`${API_URL}/api/v1/stats/categories/dashboard`)
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
            <h3>Jobs by AI Category</h3>
            <p>Specific categories are separated from fallback taxonomy buckets.</p>
          </div>
        </div>
        <div className="error-message">Failed to load categories: {error}</div>
      </div>
    );
  }

  const categorizedTotal = Number(data?.categorized_total || 0);
  const specificTotal = Number(data?.specific_total || 0);
  const fallbackTotal = Number(data?.fallback_total || 0);
  const topSpecificCategories = data?.top_specific_categories || [];
  const otherSpecificCategories = data?.other_specific_categories || {
    count: 0,
    bucket_count: 0,
    share_of_specific: 0,
  };
  const fallbackBuckets = data?.fallback_buckets || [];
  const primaryFallbackBucket = fallbackBuckets[0] || null;

  return (
    <div className="chart-container dashboard-category-chart">
      <div className="dashboard-chart-heading">
        <div>
          <h3>Jobs by AI Category</h3>
          <p>Specific categories are ranked separately so fallback taxonomy buckets do not distort the comparison view.</p>
        </div>
        <div className="dashboard-chart-badge">
          {categorizedTotal.toLocaleString()} categorized
        </div>
      </div>

      {topSpecificCategories.length === 0 && fallbackBuckets.length === 0 ? (
        <p className="chart-empty-state">No categorized jobs yet.</p>
      ) : (
        <div className="category-chart-stack">
          <div className="category-chart-summary-grid">
            <div className="category-chart-summary-card">
              <span>Specific categories</span>
              <strong>{specificTotal.toLocaleString()}</strong>
              <small>{formatShare(specificTotal, categorizedTotal)} of categorized jobs</small>
            </div>
            <div className="category-chart-summary-card category-chart-summary-card-alert">
              <span>Fallback buckets</span>
              <strong>{fallbackTotal.toLocaleString()}</strong>
              <small>{formatShare(fallbackTotal, categorizedTotal)} of categorized jobs</small>
            </div>
          </div>

          <div className="category-chart-main-panel">
            <div className="category-chart-section-header">
              <h4>Specific category mix</h4>
              <p>Primary comparison view for governed non-fallback categories.</p>
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
                      <small>{share}% of specific categories</small>
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
                      {Number(otherSpecificCategories.bucket_count || 0)} categories
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

          {primaryFallbackBucket && (
            <div className="category-fallback-panel">
              {(() => {
                const fallbackShare = resolveSharePercentage(
                  primaryFallbackBucket.share_of_categorized,
                  primaryFallbackBucket.count,
                  categorizedTotal,
                );

                return (
                  <>
              <div className="category-chart-section-header">
                <h4>Fallback diagnostic</h4>
                <p>Fallback buckets are real taxonomy outputs, but they are tracked separately from the specific category ranking.</p>
              </div>

              <div className="category-fallback-highlight">
                <div>
                  <span className="category-fallback-label">{primaryFallbackBucket.label}</span>
                  <strong>{Number(primaryFallbackBucket.count || 0).toLocaleString()}</strong>
                  <small>{fallbackShare}% of categorized jobs</small>
                </div>
                <p>{formatFallbackInsight(primaryFallbackBucket)}</p>
              </div>

              <div className="category-fallback-breakdown">
                {primaryFallbackBucket.source_breakdown.map((item) => (
                  <div
                    key={`${item.source_site || 'unknown'}-${item.source_subclassification_name || 'none'}`}
                    className="category-fallback-breakdown-row"
                  >
                    <span>{formatSourceBreakdownItem(item, primaryFallbackBucket.count)}</span>
                  </div>
                ))}
              </div>
                  </>
                );
              })()}
            </div>
          )}

          {totalJobs > 0 && (
            <p className="category-chart-footnote">
              {categorizedTotal.toLocaleString()} of {Number(totalJobs || 0).toLocaleString()} total jobs currently have a governed category path.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
