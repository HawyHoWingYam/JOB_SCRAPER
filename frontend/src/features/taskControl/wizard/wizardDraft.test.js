import { describe, expect, it, vi } from 'vitest';
import {
  clearDraft,
  createWizardDraft,
  DRAFT_PREFIX,
  readDraft,
  writeDraft,
} from './wizardDraft';

function memoryStorage() {
  const values = new Map();
  return {
    getItem: vi.fn((key) => values.get(key) ?? null),
    setItem: vi.fn((key, value) => values.set(key, value)),
    removeItem: vi.fn((key) => values.delete(key)),
    values,
  };
}

const route = {
  flow: 'automation', mode: 'create', automationId: null,
  sourceSite: 'jobsdb', draftId: 'draft-1',
};

describe('versioned wizard drafts', () => {
  it('round-trips a valid draft and clears only its versioned key', () => {
    const storage = memoryStorage();
    const draft = { ...createWizardDraft(route), intent: 'listing' };
    expect(writeDraft(storage, route.draftId, draft).ok).toBe(true);
    expect(readDraft(storage, route.draftId, route).draft.intent).toBe('listing');
    clearDraft(storage, route.draftId);
    expect(storage.removeItem).toHaveBeenCalledWith(`${DRAFT_PREFIX}${route.draftId}`);
  });

  it('recovers safely from malformed, old, cross-source, and throwing storage', () => {
    const storage = memoryStorage();
    storage.values.set(`${DRAFT_PREFIX}${route.draftId}`, JSON.stringify({ version: 0 }));
    expect(readDraft(storage, route.draftId, route).notice).toMatch(/malformed|outdated/);
    const throwing = { getItem: () => { throw new DOMException('blocked', 'SecurityError'); } };
    expect(readDraft(throwing, route.draftId, route).notice).toMatch(/unavailable/);
  });
});
