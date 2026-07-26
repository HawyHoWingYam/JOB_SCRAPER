import { describe, expect, it } from 'vitest';
import { createWizardDraft } from './wizardDraft';
import { createWizardState, wizardReducer } from './wizardReducer';

const route = { flow: 'automation', mode: 'create', automationId: null, sourceSite: 'jobsdb' };

describe('wizard reducer invariants', () => {
  it('source and editable changes invalidate review/plan authority', () => {
    const base = createWizardState(createWizardDraft(route));
    const reviewed = {
      ...base,
      review: { status: 'success', value: { inputFingerprint: 'x' }, draftFingerprint: 'draft', error: null },
      plan: { status: 'success', value: { planId: 'plan' }, draftFingerprint: 'draft', error: null },
    };
    const changed = wizardReducer(reviewed, { type: 'sourceChanged', sourceSite: 'offertoday' });
    expect(changed.draft.scope).toBeNull();
    expect(changed.review.status).toBe('idle');
    expect(changed.plan.status).toBe('idle');
  });

  it('intent change clears phase-incompatible state', () => {
    const base = createWizardState({ ...createWizardDraft(route), scope: { mode: 'all', classification_ids: [] } });
    const changed = wizardReducer(base, { type: 'intentChanged', intent: 'detail' });
    expect(changed.draft.scope).toBeNull();
    expect(changed.draft.execution.backlog_kind).toBe('crawl_scope');
  });

  it('preserves same-source classifications during hydration and resets for a source change', () => {
    const base = createWizardState(createWizardDraft(route));
    const loaded = wizardReducer(base, {
      type: 'classificationsStarted',
      version: 1,
    });
    const classifications = { sourceSite: 'jobsdb', classifications: [] };
    const withClassifications = wizardReducer(loaded, {
      type: 'classificationsSucceeded',
      version: 1,
      value: classifications,
    });

    const rehydrated = wizardReducer(withClassifications, {
      type: 'hydrate',
      draft: { ...base.draft, step: 'scope' },
      notice: null,
    });
    expect(rehydrated.classifications).toEqual(withClassifications.classifications);

    const changed = wizardReducer(rehydrated, {
      type: 'hydrate',
      draft: { ...base.draft, source_site: 'offertoday', step: 'scope' },
      notice: null,
    });
    expect(changed.classifications.value).toBeNull();
    expect(changed.classifications.status).toBe('idle');
    expect(changed.classifications.requestVersion).toBe(2);
  });
});
