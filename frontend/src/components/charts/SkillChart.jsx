import { useEffect, useState } from 'react';
import { apiPath } from '../../api/base';


const SKILL_BUCKET_ORDER = [
  'Backend',
  'Database',
  'Frontend',
  'Data',
  'Platform & Cloud',
  'Systems & Network',
  'Security & Identity',
  'Support',
  'Infrastructure',
];

const VISIBLE_SKILLS_PER_BUCKET = 4;

function mapSkillBucket(skill) {
  const dashboardBucket = String(skill?.dashboard_bucket || '').trim();
  if (dashboardBucket) {
    return dashboardBucket;
  }

  const category = String(skill?.category || '');
  const name = String(skill?.name || '').toLowerCase();

  if (category === 'Backend') {
    return 'Backend';
  }
  if (category === 'Database') {
    return 'Database';
  }
  if (category === 'Frontend') {
    return 'Frontend';
  }
  if (category === 'Data') {
    return 'Data';
  }
  if (category === 'Support & Operations') {
    return 'Support';
  }
  if (category === 'DevOps') {
    if (/(azure|aws|kubernetes|docker|ci\/cd|microsoft 365)/i.test(name)) {
      return 'Platform & Cloud';
    }
    if (/(linux|windows server|windows|network|vpn|active directory)/i.test(name)) {
      return 'Systems & Network';
    }
    if (/(firewall|cybersecurity|security|identity)/i.test(name)) {
      return 'Security & Identity';
    }
    return 'Infrastructure';
  }

  return null;
}

function groupSkills(skills) {
  const grouped = new Map(SKILL_BUCKET_ORDER.map((bucket) => [bucket, []]));

  for (const skill of skills || []) {
    const bucket = mapSkillBucket(skill);
    if (!bucket) {
      continue;
    }
    if (!grouped.has(bucket)) {
      grouped.set(bucket, []);
    }
    grouped.get(bucket).push(skill);
  }

  return Array.from(grouped, ([bucket, bucketSkills]) => ({
      bucket,
      skills: bucketSkills.sort((left, right) => Number(right.count || 0) - Number(left.count || 0)),
    }))
    .filter((entry) => entry.skills.length > 0);
}

export default function SkillChart() {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetch(apiPath('/stats/skills?limit=30'))
      .then((res) => {
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }
        return res.json();
      })
      .then((payload) => {
        setData(payload.skills || []);
      })
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
        Loading skills telemetry...
      </div>
    );
  }

  if (error) {
    return (
      <div className="chart-container">
        <h3
          style={{
            marginBottom: '1.5rem',
            color: 'var(--color-text-primary)',
            fontWeight: 600,
          }}
        >
          Top Requested Skills
        </h3>
        <div className="error-message">Failed to load skills: {error}</div>
      </div>
    );
  }

  const groups = groupSkills(data);
  const visibleGroupedSkillCount = groups.reduce((count, entry) => count + entry.skills.length, 0);

  return (
    <div className="chart-container dashboard-skill-chart">
      <div className="dashboard-chart-heading">
        <div>
          <h3>Top Requested Skills</h3>
          <p>Skills are grouped into narrower operating buckets so you can scan more demand without losing context.</p>
        </div>
        <div className="dashboard-chart-badge">
          {visibleGroupedSkillCount} skills shown
        </div>
      </div>

      {groups.length === 0 ? (
        <p className="chart-empty-state">No governed skills yet.</p>
      ) : (
        <div className="skill-chart-grid">
          {groups.map(({ bucket, skills }) => {
            const visibleSkills = skills.slice(0, VISIBLE_SKILLS_PER_BUCKET);
            const hiddenCount = Math.max(skills.length - VISIBLE_SKILLS_PER_BUCKET, 0);

            return (
              <section key={bucket} className="skill-chart-card">
                <div className="skill-chart-card-header">
                  <h4>{bucket}</h4>
                  <span>{skills.length}</span>
                </div>

                <div className="skill-chart-list">
                  {visibleSkills.map((skill) => (
                    <div key={`${bucket}-${skill.name}`} className="skill-chart-row">
                      <span>{skill.name}</span>
                      <strong>{Number(skill.count || 0).toLocaleString()}</strong>
                    </div>
                  ))}
                </div>

                {hiddenCount > 0 && (
                  <div className="skill-chart-overflow">+{hiddenCount} more</div>
                )}
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}
