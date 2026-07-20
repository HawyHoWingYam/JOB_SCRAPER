import React, { useEffect, useRef } from 'react';

export default function CatalogActionDialog({
  kind,
  source,
  fingerprint,
  activeRevision,
  impact,
  submitting,
  error,
  onCancel,
  onConfirm,
}) {
  const dialogRef = useRef(null);
  const cancelRef = useRef(null);
  const onCancelRef = useRef(onCancel);
  const submittingRef = useRef(submitting);

  useEffect(() => {
    onCancelRef.current = onCancel;
    submittingRef.current = submitting;
  }, [onCancel, submitting]);

  useEffect(() => {
    cancelRef.current?.focus();
    const handleKeyDown = (event) => {
      if (event.key === 'Escape' && !submittingRef.current) {
        event.preventDefault();
        onCancelRef.current();
        return;
      }
      if (event.key !== 'Tab') return;
      const focusable = Array.from(
        dialogRef.current?.querySelectorAll(
          'button:not(:disabled), [href], [tabindex]:not([tabindex="-1"])',
        ) || [],
      );
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const outside = !dialogRef.current?.contains(document.activeElement);
      if (event.shiftKey && (document.activeElement === first || outside)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (document.activeElement === last || outside)) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, []);

  const rollback = kind === 'rollback';
  const reviewRequired = impact?.scope_review_required_count || 0;
  const executionChanges = impact?.will_mark_scope_review_required_count || 0;

  return (
    <div className="catalog-dialog-overlay" role="presentation">
      <section
        ref={dialogRef}
        className="catalog-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="catalog-dialog-title"
        aria-describedby="catalog-dialog-summary"
      >
        <h2 id="catalog-dialog-title">
          {rollback ? 'Confirm catalog rollback' : 'Confirm catalog publication'}
        </h2>
        <div id="catalog-dialog-summary">
          <p>
            {rollback
              ? 'This reactivates an immutable prior revision. It does not restore deleted Crawl Control Data.'
              : 'The active revision changes only after the server atomically publishes this validated candidate.'}
          </p>
          <dl className="catalog-dialog-facts">
            <div><dt>Source</dt><dd>{source}</dd></div>
            <div><dt>Target fingerprint</dt><dd><code>{fingerprint?.slice(0, 16)}</code></dd></div>
            <div><dt>Current active revision</dt><dd>{activeRevision || 'None'}</dd></div>
            <div><dt>Affected Automations</dt><dd>{impact?.versioned_automation_count ?? 0}</dd></div>
            <div><dt>Scope review required</dt><dd>{reviewRequired}</dd></div>
            <div><dt>Will be paused for review</dt><dd>{executionChanges}</dd></div>
          </dl>
        </div>
        {error && <p role="alert" className="catalog-error">{error.message}</p>}
        <div className="catalog-dialog-actions">
          <button ref={cancelRef} type="button" disabled={submitting} onClick={onCancel}>
            Cancel
          </button>
          <button
            type="button"
            className="catalog-danger-action"
            disabled={submitting}
            onClick={onConfirm}
          >
            {submitting
              ? rollback ? 'Rolling back…' : 'Publishing…'
              : rollback ? 'Confirm rollback' : 'Publish revision'}
          </button>
        </div>
      </section>
    </div>
  );
}
