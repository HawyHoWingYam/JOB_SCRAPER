import React, { useEffect, useRef, useState } from 'react';
import { formatApiErrorDetail } from '../../api/errors';
import GovernedTargetPicker from './GovernedTargetPicker';

export default function DecisionDialog({
  action,
  affectedLabel,
  evidenceSummary,
  options = [],
  submitting,
  error,
  loadTargetChildren,
  targetBrowseLabel,
  onCancel,
  onConfirm,
}) {
  const dialogRef = useRef(null);
  const cancelRef = useRef(null);
  const onCancelRef = useRef(onCancel);
  const submittingRef = useRef(submitting);
  const [targetId, setTargetId] = useState(options[0]?.value || '');
  const [createTarget, setCreateTarget] = useState({
    categoryCode: '',
    technologyCode: '',
    stableCode: '',
    name: '',
    aliases: '',
  });
  const [genericTag, setGenericTag] = useState('');
  const [rejectionReason, setRejectionReason] = useState('');

  useEffect(() => {
    onCancelRef.current = onCancel;
    submittingRef.current = submitting;
  }, [onCancel, submitting]);

  useEffect(() => {
    setTargetId((current) => (
      options.some((option) => option.value === current)
        ? current
        : options[0]?.value || ''
    ));
  }, [options]);

  useEffect(() => {
    cancelRef.current?.focus();
    const handleKeyDown = (event) => {
      if (event.key === 'Escape' && !submittingRef.current) {
        event.preventDefault();
        event.stopPropagation();
        onCancelRef.current();
        return;
      }
      if (event.key !== 'Tab') return;
      const focusable = Array.from(dialogRef.current?.querySelectorAll(
        'a[href], button:not(:disabled), select:not(:disabled), input:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])',
      ) || []);
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const focusIsOutsideDialog = !dialogRef.current?.contains(document.activeElement);
      if (event.shiftKey && (document.activeElement === first || focusIsOutsideDialog)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (document.activeElement === last || focusIsOutsideDialog)) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, []);

  const targetRequired = action.requiresTarget;
  const createSkillRequired = action.inputKind === 'create-skill';
  const genericTagRequired = action.inputKind === 'generic-tag';
  const rejectionReasonRequired = action.inputKind === 'rejection-reason';
  const createTargetValid = [
    createTarget.categoryCode,
    createTarget.technologyCode,
    createTarget.stableCode,
    createTarget.name,
  ].every((value) => value.trim());
  const inputValid =
    (!targetRequired || targetId) &&
    (!createSkillRequired || createTargetValid) &&
    (!genericTagRequired || genericTag.trim()) &&
    (!rejectionReasonRequired || rejectionReason.trim());

  const confirm = () => {
    onConfirm({
      ...(targetRequired && targetId ? { targetId } : {}),
      ...(createSkillRequired
        ? {
            createTarget: {
              category_code: createTarget.categoryCode.trim(),
              technology_code: createTarget.technologyCode.trim(),
              stable_code: createTarget.stableCode.trim(),
              name: createTarget.name.trim(),
              aliases: createTarget.aliases
                .split(',')
                .map((alias) => alias.trim())
                .filter(Boolean),
            },
          }
        : {}),
      ...(genericTagRequired ? { genericTag: genericTag.trim() } : {}),
      ...(rejectionReasonRequired
        ? { rejectionReason: rejectionReason.trim() }
        : {}),
    });
  };

  return (
    <div className="decision-overlay" role="presentation">
      <section
        ref={dialogRef}
        className="decision-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="decision-dialog-title"
        aria-describedby="decision-dialog-summary"
      >
        <h2 id="decision-dialog-title">Confirm governance decision</h2>
        <dl id="decision-dialog-summary">
          <div><dt>Action</dt><dd>{action.label}</dd></div>
          <div><dt>Affected</dt><dd>{affectedLabel}</dd></div>
          <div><dt>Evidence</dt><dd>{evidenceSummary || 'Unknown'}</dd></div>
          <div><dt>Consequence</dt><dd>{action.consequence}</dd></div>
        </dl>
        {targetRequired && (
          <GovernedTargetPicker
            options={options}
            value={targetId}
            onChange={setTargetId}
            loadChildren={loadTargetChildren}
            browseLabel={targetBrowseLabel}
            disabled={submitting}
          />
        )}
        {createSkillRequired && (
          <div className="decision-inputs">
            <label>
              Skill Category code
              <input
                value={createTarget.categoryCode}
                onChange={(event) =>
                  setCreateTarget((current) => ({
                    ...current,
                    categoryCode: event.target.value,
                  }))
                }
              />
            </label>
            <label>
              Technology code
              <input
                value={createTarget.technologyCode}
                onChange={(event) =>
                  setCreateTarget((current) => ({
                    ...current,
                    technologyCode: event.target.value,
                  }))
                }
              />
            </label>
            <label>
              Stable Skill code
              <input
                value={createTarget.stableCode}
                onChange={(event) =>
                  setCreateTarget((current) => ({
                    ...current,
                    stableCode: event.target.value,
                  }))
                }
              />
            </label>
            <label>
              Skill name
              <input
                value={createTarget.name}
                onChange={(event) =>
                  setCreateTarget((current) => ({
                    ...current,
                    name: event.target.value,
                  }))
                }
              />
            </label>
            <label>
              Aliases
              <input
                value={createTarget.aliases}
                onChange={(event) =>
                  setCreateTarget((current) => ({
                    ...current,
                    aliases: event.target.value,
                  }))
                }
              />
            </label>
          </div>
        )}
        {genericTagRequired && (
          <label>
            Generic tag
            <input
              value={genericTag}
              onChange={(event) => setGenericTag(event.target.value)}
            />
          </label>
        )}
        {rejectionReasonRequired && (
          <label>
            Rejection reason
            <textarea
              value={rejectionReason}
              onChange={(event) => setRejectionReason(event.target.value)}
            />
          </label>
        )}
        {error && (
          <p className="decision-error" role="alert">
            {formatApiErrorDetail(error, 'The decision could not be recorded.')}
          </p>
        )}
        <div className="decision-actions">
          <button ref={cancelRef} type="button" onClick={onCancel} disabled={submitting}>
            Cancel
          </button>
          <button
            type="button"
            className="decision-confirm"
            disabled={submitting || !inputValid}
            onClick={confirm}
          >
            {submitting ? 'Recording…' : 'Confirm decision'}
          </button>
        </div>
      </section>
    </div>
  );
}
