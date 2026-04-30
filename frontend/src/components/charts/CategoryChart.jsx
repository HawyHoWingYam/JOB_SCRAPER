import { useState, useEffect } from 'react';
import {
  PieChart, Pie, Cell, Tooltip, ResponsiveContainer
} from 'recharts';

const API_URL = import.meta.env.VITE_API_URL || '';
const MAX_VISIBLE_CATEGORIES = 6;

// Premium Neon Palette
const COLORS = [
  '#00f2fe', // Neon Cyan
  '#8b5cf6', // Electric Purple
  '#10b981', // Emerald Green
  '#f59e0b', // Neon Amber
  '#ef4444', // Neon Red
  '#3b82f6', // Bright Blue
  '#14b8a6', // Teal
  '#d946ef', // Fuchsia
  '#84cc16', // Lime
  '#06b6d4', // Cyan
  '#8b5cf6', // Indigo
  '#f97316'  // Orange
];

function condenseCategoryLabel(category) {
  const parts = String(category || '')
    .split('/')
    .map((part) => part.trim())
    .filter(Boolean);

  if (parts.length <= 2) {
    return parts.join(' / ') || 'Uncategorized';
  }

  return parts.slice(-2).join(' / ');
}

function normalizeCategoryData(data) {
  const sorted = [...(data || [])].sort((left, right) => right.count - left.count);
  const visible = sorted.slice(0, MAX_VISIBLE_CATEGORIES).map((item) => ({
    ...item,
    shortLabel: condenseCategoryLabel(item.category),
  }));
  const overflowCount = sorted
    .slice(MAX_VISIBLE_CATEGORIES)
    .reduce((total, item) => total + Number(item.count || 0), 0);

  if (overflowCount > 0) {
    visible.push({
      category: 'Other categories',
      shortLabel: 'Other categories',
      count: overflowCount,
    });
  }

  return visible;
}

const CustomTooltip = ({ active, payload }) => {
  if (active && payload && payload.length) {
    return (
      <div style={{
        backgroundColor: 'rgba(24, 24, 27, 0.9)',
        border: '1px solid rgba(255, 255, 255, 0.1)',
        padding: '10px',
        borderRadius: '8px',
        boxShadow: '0 4px 6px rgba(0,0,0,0.3)',
        color: '#f8fafc'
      }}>
        <p style={{ margin: 0, fontWeight: 600 }}>{`${payload[0].payload.category}`}</p>
        <p style={{ margin: '4px 0 0', color: payload[0].color }}>
          {`${payload[0].value} Jobs`}
        </p>
      </div>
    );
  }
  return null;
};

export default function CategoryChart({ totalJobs = 0 }) {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetch(`${API_URL}/api/v1/stats/categories`)
      .then(res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then(setData)
      .catch(err => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  const chartData = normalizeCategoryData(data);
  const categorizedTotal = chartData.reduce((total, item) => total + Number(item.count || 0), 0);

  if (loading) return (
    <div style={{ height: '300px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--color-primary)' }}>
      Loading categorization...
    </div>
  );

  if (error) {
    return (
      <div className="chart-container">
        <h3 style={{ marginBottom: '1.5rem', color: 'var(--color-text-primary)', fontWeight: 600 }}>Jobs by Category</h3>
        <div className="error-message">Failed to load categories: {error}</div>
      </div>
    );
  }

  return (
    <div className="chart-container dashboard-category-chart" style={{ width: '100%', height: '100%' }}>
      <div className="dashboard-chart-heading">
        <div>
          <h3>Jobs by AI Category</h3>
          <p>The long tail is grouped so the taxonomy stays readable at a glance.</p>
        </div>
        <div className="dashboard-chart-badge">
          {categorizedTotal.toLocaleString()} categorized
        </div>
      </div>

      {chartData.length === 0 ? (
        <p className="chart-empty-state">No categorized jobs yet.</p>
      ) : (
        <div className="category-chart-layout">
          <div className="category-chart-visual">
            <ResponsiveContainer width="100%" height={220}>
              <PieChart>
                <Pie
                  data={chartData}
                  dataKey="count"
                  nameKey="shortLabel"
                  cx="50%"
                  cy="50%"
                  outerRadius={82}
                  innerRadius={56}
                  paddingAngle={2}
                  stroke="none"
                >
                  {chartData.map((_, i) => (
                    <Cell key={i} fill={COLORS[i % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip content={<CustomTooltip />} />
              </PieChart>
            </ResponsiveContainer>

            <div className="category-chart-center">
              <strong>{categorizedTotal.toLocaleString()}</strong>
              <span>{totalJobs ? `${Math.round((categorizedTotal / totalJobs) * 100)}% of all jobs` : 'categorized jobs'}</span>
            </div>
          </div>

          <div className="category-chart-list">
            {chartData.map((item, index) => {
              const percentage = categorizedTotal > 0
                ? Math.round((Number(item.count || 0) / categorizedTotal) * 100)
                : 0;
              const color = COLORS[index % COLORS.length];

              return (
                <div key={`${item.category}-${index}`} className="category-chart-row">
                  <span
                    className="category-chart-swatch"
                    style={{ backgroundColor: color }}
                    aria-hidden="true"
                  />

                  <div className="category-chart-copy">
                    <strong title={item.category}>{item.shortLabel}</strong>
                    <div className="category-chart-bar">
                      <span style={{ width: `${percentage}%`, backgroundColor: color }} />
                    </div>
                    <small>{percentage}% of categorized jobs</small>
                  </div>

                  <span className="category-chart-value">{Number(item.count || 0).toLocaleString()}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
