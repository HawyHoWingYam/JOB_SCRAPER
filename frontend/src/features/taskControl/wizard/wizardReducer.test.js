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

  it('preserves a same-source catalog during hydration and resets it for a source change', () => {
    const base = createWizardState(createWizardDraft(route));
    const loaded = wizardReducer(base, {
      type: 'catalogStarted',
      version: 1,
    });
    const catalog = { revision: { id: 'catalog-r7' }, catalog: { nodes: [] } };
    const withCatalog = wizardReducer(loaded, {
      type: 'catalogSucceeded',
      version: 1,
      value: catalog,
    });

    const rehydrated = wizardReducer(withCatalog, {
      type: 'hydrate',
      draft: { ...base.draft, step: 'scope' },
      notice: null,
    });
    expect(rehydrated.catalog).toEqual(withCatalog.catalog);

    const changed = wizardReducer(rehydrated, {
      type: 'hydrate',
      draft: { ...base.draft, source_site: 'offertoday', step: 'scope' },
      notice: null,
    });
    expect(changed.catalog.value).toBeNull();
    expect(changed.catalog.status).toBe('idle');
    expect(changed.catalog.requestVersion).toBe(2);
  });
});
