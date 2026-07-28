import { useMemo, useState } from "react";

const SKILL_BUCKET_ORDER = [
  "Backend",
  "Database",
  "Frontend",
  "Data",
  "Platform & Cloud",
  "Systems & Network",
  "Security & Identity",
  "Support",
  "Infrastructure",
];

const VISIBLE_SKILLS_PER_BUCKET = 4;

function groupSkills(skills) {
  const grouped = new Map(SKILL_BUCKET_ORDER.map((bucket) => [bucket, []]));

  for (const skill of skills || []) {
    const bucket = String(skill?.dashboard_bucket || "").trim();
    if (!bucket) continue;
    if (!grouped.has(bucket)) grouped.set(bucket, []);
    grouped.get(bucket).push(skill);
  }

  return Array.from(grouped, ([bucket, bucketSkills]) => ({
    bucket,
    skills: bucketSkills,
  })).filter((entry) => entry.skills.length > 0);
}

function formatUpdatedAt(value) {
  if (!value) return null;
  return new Date(value).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function ChartError({ error, hasData, lastUpdated, onRetry }) {
  return (
    <div className="dashboard-chart-error" role="alert">
      <strong>
        {hasData ? "Skills data is stale." : "Skills data is unavailable."}
      </strong>
      <span>{error}</span>
      {hasData && lastUpdated ? (
        <span>Last successful update: {formatUpdatedAt(lastUpdated)}</span>
      ) : null}
      <button
        type="button"
        className="dashboard-inline-button"
        onClick={onRetry}
      >
        Retry skills
      </button>
    </div>
  );
}

export default function SkillChart({
  data = null,
  loading = false,
  error = null,
  lastUpdated = null,
  onRetry,
  onOpenClassification,
  onSelectSkill,
}) {
  const [expandedBuckets, setExpandedBuckets] = useState(() => new Set());
  const groups = useMemo(() => groupSkills(data?.skills), [data]);
  const returnedCount = groups.reduce(
    (count, entry) => count + entry.skills.length,
    0,
  );
  const visibleCount = groups.reduce(
    (count, entry) =>
      count +
      (expandedBuckets.has(entry.bucket)
        ? entry.skills.length
        : Math.min(entry.skills.length, VISIBLE_SKILLS_PER_BUCKET)),
    0,
  );
  const backlog = data?.candidate_backlog || {};

  function toggleBucket(bucket) {
    setExpandedBuckets((current) => {
      const next = new Set(current);
      if (next.has(bucket)) next.delete(bucket);
      else next.add(bucket);
      return next;
    });
  }

  return (
    <section
      className="chart-container dashboard-skill-chart"
      aria-labelledby="skill-chart-title"
    >
      <div className="dashboard-chart-heading">
        <div>
          <h3 id="skill-chart-title">Top Matched Canonical Skills</h3>
          <p>
            Current canonical matches in successfully enriched corpus Jobs.
            Unresolved, generic, and rejected mentions are outside this ranking.
          </p>
        </div>
        {data ? (
          <div className="dashboard-chart-badge">
            {visibleCount === returnedCount
              ? `${returnedCount} returned`
              : `${visibleCount} of ${returnedCount} visible`}
          </div>
        ) : null}
      </div>

      {loading && !data ? (
        <p className="dashboard-chart-status" role="status">
          Loading matched canonical Skills…
        </p>
      ) : null}
      {loading && data ? (
        <p className="dashboard-chart-status" role="status">
          Refreshing matched canonical Skills…
        </p>
      ) : null}
      {error ? (
        <ChartError
          error={error}
          hasData={Boolean(data)}
          lastUpdated={lastUpdated}
          onRetry={onRetry}
        />
      ) : null}

      {data ? (
        <>
          <div className="category-chart-summary-grid skill-chart-summary-grid">
            <div className="category-chart-summary-card">
              <span>Canonical Skill Match Coverage</span>
              <strong>{Number(data.match_coverage || 0)}%</strong>
              <small>
                {Number(data.matched_job_total || 0).toLocaleString()} of{" "}
                {Number(data.processed_total || 0).toLocaleString()}{" "}
                successfully enriched Jobs have at least one match.
              </small>
            </div>
            <div className="category-chart-summary-card category-chart-summary-card-alert">
              <span>Unresolved Skill Candidates</span>
              <strong>
                {Number(
                  backlog.unresolved_candidate_total || 0,
                ).toLocaleString()}
              </strong>
              <small>
                Across{" "}
                {Number(backlog.affected_job_total || 0).toLocaleString()}{" "}
                distinct Jobs;{" "}
                {Number(backlog.ready_candidate_total || 0).toLocaleString()}{" "}
                meet the current{" "}
                {Number(backlog.ready_threshold || 0).toLocaleString()}-Job
                Classification threshold.
              </small>
              {Number(backlog.ready_candidate_total || 0) > 0 ? (
                <button
                  type="button"
                  className="dashboard-inline-button"
                  aria-label={`Open Skill Classification for ${Number(
                    backlog.ready_candidate_total || 0,
                  ).toLocaleString()} ready Candidates`}
                  onClick={onOpenClassification}
                >
                  Classify ready Candidates
                </button>
              ) : null}
            </div>
          </div>

          {groups.length === 0 ? (
            <p className="chart-empty-state">
              No matched canonical Skills yet.
            </p>
          ) : (
            <div className="skill-chart-grid">
              {groups.map(({ bucket, skills }, bucketIndex) => {
                const expanded = expandedBuckets.has(bucket);
                const visibleSkills = expanded
                  ? skills
                  : skills.slice(0, VISIBLE_SKILLS_PER_BUCKET);
                const hiddenCount = Math.max(
                  skills.length - VISIBLE_SKILLS_PER_BUCKET,
                  0,
                );

                return (
                  <section
                    key={bucket}
                    className="skill-chart-card"
                    aria-labelledby={`skill-bucket-${bucketIndex}`}
                  >
                    <div className="skill-chart-card-header">
                      <h4 id={`skill-bucket-${bucketIndex}`}>{bucket}</h4>
                      <span
                        aria-label={`${skills.length} returned Skills in ${bucket}`}
                      >
                        {skills.length}
                      </span>
                    </div>

                    <ul className="skill-chart-list">
                      {visibleSkills.map((skill) => (
                        <li key={skill.code}>
                          <button
                            type="button"
                            className="skill-chart-row skill-chart-row-action"
                            aria-label={`View ${Number(
                              skill.count || 0,
                            ).toLocaleString()} Jobs matched to ${skill.name}`}
                            onClick={() => onSelectSkill?.(skill)}
                          >
                            <span>{skill.name}</span>
                            <strong>
                              {Number(skill.count || 0).toLocaleString()} Jobs ·{" "}
                              {Number(skill.prevalence || 0)}%
                            </strong>
                          </button>
                        </li>
                      ))}
                    </ul>

                    {hiddenCount > 0 ? (
                      <button
                        type="button"
                        className="skill-chart-overflow"
                        aria-expanded={expanded}
                        onClick={() => toggleBucket(bucket)}
                      >
                        {expanded ? "Show less" : `Show ${hiddenCount} more`}
                      </button>
                    ) : null}
                  </section>
                );
              })}
            </div>
          )}

          <p className="category-chart-footnote">
            Skill prevalence uses successfully enriched, non-deleted Jobs as its
            denominator. Jobs may have multiple Skills, so percentages do not
            sum to 100%.
          </p>
        </>
      ) : null}
    </section>
  );
}
