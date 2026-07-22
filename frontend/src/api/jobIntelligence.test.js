import { beforeEach, describe, expect, it, vi } from 'vitest';
import productFixture from '../fixtures/job_intelligence_product_surfaces.json';
import {
  decideCanonicalReviewItem,
  createCanonicalTaxonomyRecoveryRun,
  fetchCanonicalReviewItems,
  fetchGovernanceSummary,
  previewCanonicalTaxonomyRecovery,
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

  it('serializes Canonical Review filters as a JSON query without changing domain values', async () => {
    globalThis.fetch.mockResolvedValue(
      responseJson({ items: [], next_cursor: null, total: 0 }),
    );

    await fetchCanonicalReviewItems({
      status: ['active', 'insufficient_evidence'],
      reason: ['classifier_provenance_missing'],
      limit: 25,
    });
    await fetchSkillCandidates({ status: ['pending'], search: 'rust', limit: 10 });

    const [canonicalUrl, canonicalInit] = globalThis.fetch.mock.calls[0];
    expect(canonicalUrl).toBe(
      '/api/v1/job-intelligence/governance/job-taxonomy/review-items/query',
    );
    expect(canonicalInit.method).toBe('POST');
    expect(JSON.parse(canonicalInit.body)).toEqual({
      status: ['active', 'insufficient_evidence'],
      reason: ['classifier_provenance_missing'],
      job_ids: [],
      source_site: [],
      source_classification_id: [],
      source_subclassification_id: [],
      posted_date_from: null,
      posted_date_to: null,
      pending_limit: null,
      cursor: null,
      page: null,
      limit: 25,
    });
    expect(globalThis.fetch.mock.calls[1][0]).toBe(
      '/api/v1/job-intelligence/governance/skills/candidates?status=pending&search=rust&limit=10',
    );
  });

  it('preserves every bounded review Job ID in the JSON body', async () => {
    globalThis.fetch.mockResolvedValue(
      responseJson({ items: [], next_cursor: null, total: 0 }),
    );
    const jobIds = Array.from({ length: 500 }, (_, index) => `job-${index}`);

    await fetchCanonicalReviewItems({
      status: ['active'],
      reason: ['source_catalog_provenance_missing'],
      sourceSites: ['offertoday'],
      sourceClassificationIds: ['offertoday:118000'],
      pendingLimit: 5000,
      jobIds,
      limit: 10,
    });

    expect(globalThis.fetch.mock.calls[0][0]).toBe(
      '/api/v1/job-intelligence/governance/job-taxonomy/review-items/query',
    );
    expect(JSON.parse(globalThis.fetch.mock.calls[0][1].body)).toEqual({
      status: ['active'],
      reason: ['source_catalog_provenance_missing'],
      job_ids: jobIds,
      source_site: ['offertoday'],
      source_classification_id: ['offertoday:118000'],
      source_subclassification_id: [],
      posted_date_from: null,
      posted_date_to: null,
      pending_limit: 5000,
      cursor: null,
      page: null,
      limit: 10,
    });
    expect(globalThis.fetch.mock.calls[0][1].headers.get('Content-Type'))
      .toBe('application/json');
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

  it('serializes scoped page-mode taxonomy queue filters in the JSON body', async () => {
    globalThis.fetch.mockResolvedValue(
      responseJson({ items: [], next_cursor: null, total: 0, page: 1, limit: 10, offset: 0, page_count: 0 }),
    );

    await fetchCanonicalReviewItems({
      status: ['active'],
      reason: ['source_catalog_provenance_missing'],
      jobIds: ['job-1'],
      sourceSites: ['offertoday'],
      sourceClassificationIds: ['offertoday:121000'],
      sourceSubclassificationIds: ['offertoday:121015'],
      postedDateFrom: '2026-07-01',
      postedDateTo: '2026-07-22',
      pendingLimit: 50,
      page: 2,
      limit: 10,
    });

    const [url, init] = globalThis.fetch.mock.calls[0];
    expect(url).toBe(
      '/api/v1/job-intelligence/governance/job-taxonomy/review-items/query',
    );
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({
      status: ['active'],
      reason: ['source_catalog_provenance_missing'],
      job_ids: ['job-1'],
      source_site: ['offertoday'],
      source_classification_id: ['offertoday:121000'],
      source_subclassification_id: ['offertoday:121015'],
      posted_date_from: '2026-07-01',
      posted_date_to: '2026-07-22',
      pending_limit: 50,
      cursor: null,
      page: 2,
      limit: 10,
    });
  });

  it('pins the recovery scope and active revisions at the confirm boundary', async () => {
    globalThis.fetch.mockResolvedValue(responseJson({ id: 'run-1', status: 'pending' }));
    const scope = {
      sourceSites: ['offertoday'],
      sourceClassificationIds: ['offertoday:121000'],
      jobIds: ['job-1'],
      reason: 'classifier_provenance_missing',
      pendingLimit: 5000,
    };

    await previewCanonicalTaxonomyRecovery(scope);
    await createCanonicalTaxonomyRecoveryRun(scope, {
      expectedScopeFingerprint: 'scope-hash',
      taxonomyRevisionId: 'taxonomy-1',
      mappingRevisionId: 'mapping-1',
    });

    expect(globalThis.fetch.mock.calls[0][0]).toBe(
      '/api/v1/job-intelligence/governance/job-taxonomy/recovery/preview',
    );
    expect(JSON.parse(globalThis.fetch.mock.calls[0][1].body)).toEqual({
      scope: expect.objectContaining({
        source_sites: ['offertoday'],
        source_classification_ids: ['offertoday:121000'],
        job_ids: ['job-1'],
        reason_codes: ['classifier_provenance_missing'],
        pending_limit: 5000,
      }),
    });
    expect(JSON.parse(globalThis.fetch.mock.calls[1][1].body)).toMatchObject({
      expected_scope_fingerprint: 'scope-hash',
      taxonomy_revision_id: 'taxonomy-1',
      mapping_revision_id: 'mapping-1',
      confirmed: true,
    });
  });
});
