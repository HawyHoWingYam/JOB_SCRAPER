import { useState, useEffect } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Cell
} from 'recharts';

const API_URL = import.meta.env.VITE_API_URL || '';

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
        <p style={{ margin: 0, fontWeight: 600 }}>{`${payload[0].payload.skill}`}</p>
        <p style={{ margin: '4px 0 0', color: '#00f2fe' }}>
          {`Count: ${payload[0].value}`}
        </p>
      </div>
    );
  }
  return null;
};

export default function SkillChart() {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetch(`${API_URL}/api/v1/stats/skills?limit=15`)
      .then(res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then(data => {
        // Transform new API format {skills: [{name, category, count}]} to chart format
        const chartData = data.skills?.map(s => ({ skill: s.name, count: s.count })) || [];
        setData(chartData);
      })
      .catch(err => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return (
    <div style={{ height: '300px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--color-primary)' }}>
      Loading skills telemetry...
    </div>
  );

  if (error) {
    return (
      <div className="chart-container">
        <h3 style={{ marginBottom: '1.5rem', color: 'var(--color-text-primary)', fontWeight: 600 }}>Top Skills</h3>
        <div className="error-message">Failed to load skills: {error}</div>
      </div>
    );
  }

  return (
    <div className="chart-container" style={{ width: '100%', height: '100%' }}>
      <h3 style={{ marginBottom: '1.5rem', color: 'var(--color-text-primary)', fontWeight: 600, fontSize: '1.125rem' }}>
        Top Requested Skills
      </h3>
      <ResponsiveContainer width="100%" height={320}>
        <BarChart data={data} layout="vertical" margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" horizontal={false} />
          <XAxis
            type="number"
            stroke="var(--color-text-muted)"
            tick={{ fill: 'var(--color-text-secondary)', fontSize: 12 }}
          />
          <YAxis
            dataKey="skill"
            type="category"
            width={100}
            stroke="var(--color-text-muted)"
            tick={{ fill: 'var(--color-text-primary)', fontSize: 12 }}
          />
          <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(255,255,255,0.02)' }} />
          <Bar dataKey="count" radius={[0, 4, 4, 0]}>
            {data.map((entry, index) => (
              <Cell key={`cell-${index}`} fill={'#00f2fe'} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
