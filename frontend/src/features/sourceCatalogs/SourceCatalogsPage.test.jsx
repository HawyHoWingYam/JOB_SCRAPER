import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  getCatalogSummaries: vi.fn(),
  getPublishedCatalog: vi.fn(),
  discoverCandidate: vi.fn(),
  getCandidate: vi.fn(),
  startValidation: vi.fn(),
  getValidationRuns: vi.fn(),
  createPublicationReview: vi.fn(),
  publishCandidate: vi.fn(),
  getRevisionHistory: vi.fn(),
  createRollbackReview: vi.fn(),
  rollbackRevision: vi.fn(),
  catalogErrorState: vi.fn((error) => ({
    kind: error.code === 'CATALOG_CANDIDATE_STALE' ? 'stale-candidate' : 'api',
    message: error.message,
    requestId: error.requestId,
  })),
}));

vi.mock('./sourceCatalogsApi', () => api);

import SourceCatalogsPage from './SourceCatalogsPage';
import {
  createSourceCatalogState,
  sourceCatalogsReducer,
} from './sourceCatalogsReducer';

const revision = {
  id: 'revision-1',
  sourceSite: 'ctgoodjobs',
  sequence: 1,
  fingerprint: 'a'.repeat(64),
  predecessorRevisionId: null,
  publishedBy: 'operator',
  publishedAt: '2026-07-20T12:00:00Z',
  provenance: { method: 'headed-discovery' },
  publicationMetadata: {},
  validationSummary: { status: 'validated' },
  nodeCount: 12,
  queryTargetCount: 10,
};

const node = {
  nodeKey: 'ctgoodjobs:it',
  sourceSite: 'ctgoodjobs',
  classificationId: 'ctgoodjobs:it',
  nativeId: 'it',
  nativeLabel: 'Information Technology',
  parentNodeKey: null,
  nativePath: ['Information Technology'],
  depth: 0,
  selectable: true,
  supportsExact: true,
  supportsSubtree: true,
  queryable: true,
  aliasOfNodeKey: null,
  querySemanticsHash: 'b'.repeat(64),
  sourceMetadata: { clean_match: 'Technology' },
};

const candidate = {
  id: 'candidate-1',
  sourceSite: 'ctgoodjobs',
  baseRevisionId: revision.id,
  fingerprint: 'c'.repeat(64),
  state: 'validated',
  catalog: {
    version: 1,
    sourceSite: 'ctgoodjobs',
    nodes: [node],
    capabilities: {
      supportsAllScope: true,
      allScopeRootNodeKeys: [node.nodeKey],
      recommendedScope: { mode: 'all' },
    },
  },
  diff: {
    added: [{ node_key: node.nodeKey, classification_id: node.classificationId }],
    removed: [],
    renamed: [],
    moved: [],
    alias_changed: [],
    capabilities_changed: [],
    query_semantics_changed: [],
  },
  validationSummary: { status: 'validated', passed: 2 },
  provenance: { method: 'headed-discovery' },
  createdAt: '2026-07-21T01:00:00Z',
  validatedAt: '2026-07-21T01:10:00Z',
  publishedAt: null,
};

const summaries = [
  {
    sourceSite: 'jobsdb',
    publishedRevision: { ...revision, id: 'jobsdb-revision', sourceSite: 'jobsdb' },
    latestCandidate: null,
    affectedAutomationCount: 0,
  },
  {
    sourceSite: 'ctgoodjobs',
    publishedRevision: revision,
    latestCandidate: {
      id: candidate.id,
      fingerprint: candidate.fingerprint,
      state: candidate.state,
      createdAt: candidate.createdAt,
    },
    affectedAutomationCount: 2,
  },
  {
    sourceSite: 'offertoday',
    publishedRevision: { ...revision, id: 'offer-revision', sourceSite: 'offertoday' },
    latestCandidate: null,
    affectedAutomationCount: 1,
  },
];

function defaultResponses() {
  api.getCatalogSummaries.mockResolvedValue(summaries);
  api.getPublishedCatalog.mockResolvedValue({
    revision,
    catalog: { ...candidate.catalog, nodes: [node] },
  });
  api.getCandidate.mockResolvedValue(candidate);
  api.getValidationRuns.mockResolvedValue([
    {
      id: 'run-offline', candidateId: candidate.id, validationKind: 'offline',
      classificationId: null, targetHashPrefix: 'cataloghash1', status: 'passed',
      attempt: 1, evidence: { node_count: 12 }, error: null, manualAction: null,
      createdAt: '2026-07-21T01:02:00Z', completedAt: '2026-07-21T01:03:00Z',
    },
    {
      id: 'run-live', candidateId: candidate.id, validationKind: 'live_smoke',
      classificationId: node.classificationId, targetHashPrefix: 'targethash12',
      status: 'manual_action_required', attempt: 1,
      evidence: { status: 'manual_action_required' }, error: null,
      manualAction: { reason: 'operator_login_required' },
      createdAt: '2026-07-21T01:04:00Z', completedAt: '2026-07-21T01:05:00Z',
    },
  ]);
  api.getRevisionHistory.mockResolvedValue({
    sourceSite: 'ctgoodjobs', revisions: [revision],
    publications: [{
      id: 'publication-1', operation: 'publish', revisionId: revision.id,
      previousRevisionId: null, actor: 'operator', createdAt: revision.publishedAt,
    }],
  });
}

describe('SourceCatalogsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.location.hash = '#source-catalogs?source=ctgoodjobs';
    defaultResponses();
  });

  it('loads current state without discovering and renders server-selected validation mode', async () => {
    render(<SourceCatalogsPage />);

    expect(await screen.findByText('Information Technology')).toBeInTheDocument();
    expect(api.discoverCandidate).not.toHaveBeenCalled();
    expect(screen.getByText(/Server-selected browser mode/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Resume / retry validation' })).toBeEnabled();
    expect(screen.getByText(/Canonical clean_match: Technology/)).toBeInTheDocument();
  });

  it('changes source through the hash with keyboard tab navigation', async () => {
    render(<SourceCatalogsPage />);
    const tab = await screen.findByRole('tab', { name: /CTgoodjobs/ });
    tab.focus();
    fireEvent.keyDown(tab, { key: 'ArrowRight' });

    expect(window.location.hash).toBe('#source-catalogs?source=offertoday');
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: /OfferToday/ })).toHaveAttribute(
        'aria-selected',
        'true',
      ),
    );
  });

  it('reviews impact before opening an accessible publication confirmation', async () => {
    api.createPublicationReview.mockResolvedValue({
      reviewId: 'review-1', reviewToken: 'review-token-value',
      expiresAt: '2026-07-21T02:00:00Z',
      impact: {
        versioned_automation_count: 1,
        scope_review_required_count: 1,
        will_mark_scope_review_required_count: 1,
        automations: [{
          automation_id: 'automation-1', expected_revision: 3,
          lifecycle_state: 'active', crawl_phase: 'listing',
          status: 'scope_review_required',
          impact: {
            authored_scope: {
              mode: 'rules',
              rules: [{ kind: 'subtree', classification_id: node.classificationId }],
            },
            before: { query_target_count: 1 }, after: { query_target_count: 2 },
            before_listing_workload: { estimated_max_pages: 10, run_page_cap: 20 },
            after_listing_workload: { estimated_max_pages: 30, run_page_cap: 20 },
            reason_codes: ['SCOPE_WORKLOAD_CAP_EXCEEDED'],
          },
        }],
      },
    });
    render(<SourceCatalogsPage />);

    const publish = await screen.findByRole('button', {
      name: 'Review impact & publish',
    });
    await userEvent.click(publish);
    const dialog = await screen.findByRole('alertdialog', {
      name: 'Confirm catalog publication',
    });

    expect(within(dialog).getByRole('button', { name: 'Cancel' })).toHaveFocus();
    expect(screen.getByText('1 → 2')).toBeInTheDocument();
    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() =>
      expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument(),
    );
    await waitFor(() => expect(publish).toHaveFocus());
  });

  it('suppresses stale resource responses in the reducer', () => {
    const state = { ...createSourceCatalogState('jobsdb'), requestVersion: 4 };
    const next = sourceCatalogsReducer(state, {
      type: 'resourceSucceeded', resource: 'candidate', value: candidate, version: 3,
    });
    expect(next).toBe(state);
  });
});
