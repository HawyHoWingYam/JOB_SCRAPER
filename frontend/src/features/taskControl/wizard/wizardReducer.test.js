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
    const base = createWizardState({ ...createWizardDraft(route), scope: { mode: 'all', rules: [] } });
    const changed = wizardReducer(base, { type: 'intentChanged', intent: 'detail' });
    expect(changed.draft.scope).toBeNull();
    expect(changed.draft.execution.backlog_kind).toBe('crawl_scope');
  });
});
