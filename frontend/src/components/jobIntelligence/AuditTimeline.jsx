import React from 'react';

export default function AuditTimeline({ events = [] }) {
  return (
    <section className="governance-panel">
      <h2>Audit timeline</h2>
      {events.length === 0 ? (
        <p className="governance-muted">No audit events for this item.</p>
      ) : (
        <ol className="audit-timeline">
          {events.map((event) => (
            <li key={event.id}>
              <strong>{event.action}</strong>
              <span>{event.actor}</span>
              <time dateTime={event.created_at}>
                {new Date(event.created_at).toLocaleString()}
              </time>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
