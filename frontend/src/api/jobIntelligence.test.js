import { beforeEach, describe, expect, it, vi } from 'vitest';
import productFixture from '../fixtures/job_intelligence_product_surfaces.json';
import {
  decideCanonicalReviewItem,
  fetchCanonicalReviewItems,
  fetchGovernanceSummary,
  fetchSkillCandidates,
} from './jobIntelligence';

function responseJson(payload, { ok = true, status = 200 } = {}) {
  return {
    ok,
    status,
    json: async () => payload,
  };
}

describe('job intelligence API', () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn();
  });

  it('returns the backend-owned governance summary contract unchanged', async () => {
    globalThis.fetch.mockResolvedValue(responseJson(productFixture.summary));

    await expect(fetchGovernanceSummary()).resolves.toEqual(productFixture.summary);
    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/v1/job-intelligence/governance/summary',
      expect.any(Object),
    );
  });

  it('serializes stable queue filters without changing domain values', async () => {
    globalThis.fetch.mockResolvedValue(
      responseJson({ items: [], next_cursor: null, total: 0 }),
    );

    await fetchCanonicalReviewItems({
      status: ['active', 'insufficient_evidence'],
      reason: ['classifier_provenance_missing'],
      limit: 25,
    });
    await fetchSkillCandidates({ status: ['pending'], search: 'rust', limit: 10 });

    expect(globalThis.fetch.mock.calls[0][0]).toBe(
      '/api/v1/job-intelligence/governance/job-taxonomy/review-items?status=active&status=insufficient_evidence&reason=classifier_provenance_missing&limit=25',
    );
    expect(globalThis.fetch.mock.calls[1][0]).toBe(
      '/api/v1/job-intelligence/governance/skills/candidates?status=pending&search=rust&limit=10',
    );
  });

  it('builds confirmed idempotent canonical decisions at the adapter boundary', async () => {
    globalThis.fetch.mockResolvedValue(
      responseJson({
        subject: { status: 'assigned' },
        resulting_projection: null,
        audit_event_id: '90000000-0000-0000-0000-000000000001',
        version: 2,
        replayed: false,
      }),
    );

    await decideCanonicalReviewItem(
      '50000000-0000-0000-0000-000000000001',
      {
        action: 'assign_existing_subcategory',
        targetId: '60000000-0000-0000-0000-000000000001',
        expectedVersion: 1,
        note: 'Evidence reviewed',
        idempotencyKey: 'decision-fixed',
      },
    );

    const [url, init] = globalThis.fetch.mock.calls[0];
    expect(url).toBe(
      '/api/v1/job-intelligence/governance/job-taxonomy/review-items/50000000-0000-0000-0000-000000000001/decision',
    );
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({
      action: 'assign_existing_subcategory',
      target_id: '60000000-0000-0000-0000-000000000001',
      expected_version: 1,
      idempotency_key: 'decision-fixed',
      confirmed: true,
      note: 'Evidence reviewed',
    });
  });
});
