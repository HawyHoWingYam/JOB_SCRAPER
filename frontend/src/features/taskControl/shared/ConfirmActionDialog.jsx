import React, { useEffect, useRef } from 'react';

export default function ConfirmActionDialog({ title, summary, confirmLabel, pending, error, onCancel, onConfirm, restoreFocusRef }) {
  const dialogRef = useRef(null);
  const cancelRef = useRef(null);
  const cancelCallback = useRef(onCancel);
  const pendingRef = useRef(pending);

  useEffect(() => {
    cancelCallback.current = onCancel;
    pendingRef.current = pending;
  }, [onCancel, pending]);

  useEffect(() => {
    const returnFocus = restoreFocusRef?.current;
    cancelRef.current?.focus();
    const onKeyDown = (event) => {
      if (event.key === 'Escape' && !pendingRef.current) {
        event.preventDefault();
        cancelCallback.current();
        return;
      }
      if (event.key !== 'Tab') return;
      const controls = Array.from(dialogRef.current?.querySelectorAll('button:not(:disabled), [href], [tabindex]:not([tabindex="-1"])') || []);
      if (!controls.length) return;
      const first = controls[0];
      const last = controls[controls.length - 1];
      const outside = !dialogRef.current?.contains(document.activeElement);
      if (event.shiftKey && (document.activeElement === first || outside)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (document.activeElement === last || outside)) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      returnFocus?.focus();
    };
  }, [restoreFocusRef]);

  return (
    <div className="control-dialog-overlay" role="presentation">
      <section ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="control-dialog-title" aria-describedby="control-dialog-summary" className="control-dialog">
        <h2 id="control-dialog-title">{title}</h2>
        <p id="control-dialog-summary">{summary}</p>
        {error && <p role="alert" className="control-error">{error.message}</p>}
        <div className="control-dialog-actions">
          <button ref={cancelRef} type="button" disabled={pending} onClick={onCancel}>Cancel</button>
          <button type="button" className="control-danger" disabled={pending} onClick={onConfirm}>{pending ? 'Working…' : confirmLabel}</button>
        </div>
      </section>
    </div>
  );
}
