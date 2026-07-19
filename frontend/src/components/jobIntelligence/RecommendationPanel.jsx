import React from 'react';

function recommendationLabel(item) {
  return (
    item.label ||
    item.skill_name ||
    item.name ||
    item.code ||
    'Advisory recommendation'
  );
}
export default function RecommendationPanel({ recommendations = [] }) {
  return (
    <section className="governance-panel">
      <h2>Recommendations</h2>
      {recommendations.length === 0 ? (
        <p className="governance-muted">No advisory recommendations.</p>
      ) : (
        <ul className="recommendation-list">
          {recommendations.map((item, index) => (
            <li key={item.id || item.skill_id || `${recommendationLabel(item)}-${index}`}>
              <strong>{recommendationLabel(item)}</strong>
              {item.reason && <span>{item.reason}</span>}
              {item.score !== undefined && <span>Score {item.score}</span>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
