import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  cancelCrawlJob: vi.fn(),
  createAutomation: vi.fn(),
  dispatchPlan: vi.fn(),
  getAutomation: vi.fn(),
  getCrawlJob: vi.fn(),
  getPublishedCatalog: vi.fn(),
  prepareDispatchPlan: vi.fn(),
  reviewAutomation: vi.fn(),
  updateAutomation: vi.fn(),
  controlError: vi.fn((error) => ({
    code: error.code || null,
    message: error.message || 'Request failed',
    details: null,
    requestId: null,
    stale: ['AUTOMATION_REVIEW_STALE', 'DISPATCH_PLAN_STALE'].includes(error.code),
  })),
}));

vi.mock('../shared/controlApi', () => api);

import TaskControlWizard from './TaskControlWizard';
import { DRAFT_PREFIX } from './wizardDraft';

const published = {
  revision: { id: 'catalog-r7', sourceSite: 'jobsdb' },
  catalog: {
    sourceSite: 'jobsdb',
    capabilities: { supportsAllScope: true },
    nodes: [],
  },
};

function draft({ flow = 'automation', sourceSite = 'jobsdb', step = 'review' } = {}) {
  return {
    version: 1,
    updated_at: '2026-07-21T00:00:00Z',
    flow,
    mode: 'create',
    automation_id: null,
    expected_revision: null,
    source_site: sourceSite,
    step,
    intent: 'listing',
    scope: { mode: 'all', rules: [] },
    execution: { page_depth: 2, run_page_cap: 20, crawl_mode: 'headless' },
    schedule: {
      name: 'Morning listings',
      description: '',
      cron_expression: '0 4 * * *',
      timezone: 'Asia/Hong_Kong',
      initial_state: 'paused',
    },
  };
}

function review(inputFingerprint = 'review-fingerprint') {
  return {
    inputFingerprint,
    automationId: null,
    expectedRevision: null,
    catalogRevisionId: 'catalog-r7',
    authoredScope: { mode: 'all' },
    resolvedScope: { query_target_count: 3 },
    listingWorkload: {
      query_target_count: 3,
      page_depth: 2,
      estimated_max_pages: 6,
      run_page_cap: 20,
      system_run_page_cap: 1000,
    },
    detailPreview: null,
    scheduleSummary: {
      human_summary: 'Daily at 04:00 Asia/Hong_Kong',
      next_run_at: '2026-07-22T20:00:00Z',
      timezone: 'Asia/Hong_Kong',
    },
    readiness: { status: 'ready', blockingErrors: [], capabilities: {} },
    warnings: [],
    before: null,
  };
}

function plan() {
  return {
    planId: 'plan-1',
    state: 'prepared',
    planFingerprint: 'plan-fingerprint',
    confirmationToken: 'one-time-token',
    expiresAt: '2099-07-21T00:00:00Z',
    detailTargetCount: 0,
    content: {
      resolved_scope: { query_target_count: 3 },
      listing_settings: { page_depth: 2, run_page_cap: 20 },
      detail_settings: null,
    },
    readiness: { status: 'ready', blockingErrors: [], capabilities: {} },
    targets: [],
  };
}

function automation() {
  return {
    id: 'automation-1',
    revision: 4,
    lifecycleState: 'paused',
    sourceSite: 'jobsdb',
    configuration: {
      version: 1,
      name: 'Saved Automation',
      description: null,
      cron_expression: '0 4 * * *',
      timezone: 'Asia/Hong_Kong',
      scope: {
        version: 1,
        source_site: 'jobsdb',
        reviewed_catalog_revision_id: 'catalog-r7',
        mode: 'all',
        rules: [],
      },
      listing_settings: { version: 1, crawl_mode: 'headless', page_depth: 2, run_page_cap: 20 },
      detail_settings: null,
    },
  };
}

function storeDraft(id, value) {
  globalThis.sessionStorage.setItem(`${DRAFT_PREFIX}${id}`, JSON.stringify(value));
}

describe('TaskControlWizard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    globalThis.sessionStorage.clear();
    api.getPublishedCatalog.mockResolvedValue(published);
  });

  it('saves an Automation only with the exact current server review fingerprint', async () => {
    storeDraft('automation-draft', draft());
    api.reviewAutomation.mockResolvedValue(review('server-review-fingerprint'));
    api.createAutomation.mockResolvedValue({ id: 'automation-1' });
    api.getAutomation.mockResolvedValue(automation());
    const user = userEvent.setup();

    render(<TaskControlWizard hash="#scheduler/automation/new?draft=automation-draft&source=jobsdb" />);

    await user.click(await screen.findByRole('button', { name: 'Save reviewed Automation' }));
    await waitFor(() => expect(api.createAutomation).toHaveBeenCalledTimes(1));
    expect(api.getAutomation).toHaveBeenCalledWith('automation-1');
    expect(api.createAutomation.mock.calls[0][0]).toMatchObject({
      review_fingerprint: 'server-review-fingerprint',
      initial_state: 'paused',
      configuration: {
        name: 'Morning listings',
        scope: { reviewed_catalog_revision_id: 'catalog-r7', mode: 'all' },
      },
    });
  });

  it('dispatches the exact prepared plan authority and suppresses duplicate submit', async () => {
    storeDraft('one-off-draft', draft({ flow: 'one_off' }));
    api.prepareDispatchPlan.mockResolvedValue(plan());
    let finishDispatch;
    api.dispatchPlan.mockImplementation(() => new Promise((resolve) => { finishDispatch = resolve; }));

    render(<TaskControlWizard hash="#scheduler/one-off/new?draft=one-off-draft&source=jobsdb" />);

    const confirm = await screen.findByRole('button', { name: 'Confirm and start' });
    await waitFor(() => expect(confirm).toBeEnabled());
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    expect(api.dispatchPlan).toHaveBeenCalledTimes(1);
    expect(api.dispatchPlan).toHaveBeenCalledWith('plan-1', 'one-time-token', 'plan-fingerprint');

    finishDispatch({ crawlJobId: 'crawl-job-1' });
    expect(await screen.findByText('Reviewed plan dispatched.')).toBeInTheDocument();
  });

  it('enforces headed-only execution for CTgoodjobs', async () => {
    const ctPublished = {
      revision: { id: 'catalog-ct-1', sourceSite: 'ctgoodjobs' },
      catalog: { sourceSite: 'ctgoodjobs', capabilities: { supportsAllScope: true }, nodes: [] },
    };
    api.getPublishedCatalog.mockResolvedValue(ctPublished);
    storeDraft('ct-draft', draft({ sourceSite: 'ctgoodjobs', step: 'execution' }));

    render(<TaskControlWizard hash="#scheduler/automation/new?draft=ct-draft&source=ctgoodjobs" />);

    expect(await screen.findByText('Headed only.')).toBeInTheDocument();
    expect(screen.queryByLabelText('Crawl mode')).not.toBeInTheDocument();
  });

  it('keeps the recoverable draft when the server rejects stale review authority', async () => {
    const savedDraft = draft();
    storeDraft('stale-draft', savedDraft);
    api.reviewAutomation.mockRejectedValue(Object.assign(new Error('Review is stale'), {
      code: 'AUTOMATION_REVIEW_STALE',
    }));

    render(<TaskControlWizard hash="#scheduler/automation/new?draft=stale-draft&source=jobsdb" />);

    expect(await screen.findByRole('alert')).toHaveTextContent('Review is stale');
    expect(screen.getByRole('button', { name: 'Refresh review' })).toBeInTheDocument();
    expect(JSON.parse(globalThis.sessionStorage.getItem(`${DRAFT_PREFIX}stale-draft`))).toMatchObject({
      intent: 'listing',
      scope: { mode: 'all' },
      execution: { page_depth: 2, run_page_cap: 20 },
    });
  });

  it('moves focus into a confirmation dialog and restores it on Escape', async () => {
    storeDraft('focus-draft', draft({ step: 'execution' }));
    const user = userEvent.setup();
    render(<TaskControlWizard hash="#scheduler/automation/new?draft=focus-draft&source=jobsdb&step=execution" />);

    const trigger = screen.getByRole('button', { name: 'Discard draft' });
    await user.click(trigger);
    expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus();

    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it('opens Run with changes as a separate One-off draft without mutating the Automation', async () => {
    api.getAutomation.mockResolvedValue(automation());
    api.prepareDispatchPlan.mockResolvedValue(plan());
    const user = userEvent.setup();
    render(<TaskControlWizard hash="#scheduler/run/automation-1/review?draft=run-draft&source=jobsdb&step=review" />);

    await user.click(await screen.findByRole('button', { name: /Run with changes/ }));

    const stored = Array.from({ length: globalThis.sessionStorage.length }, (_, index) => globalThis.sessionStorage.key(index))
      .filter((key) => key?.startsWith(DRAFT_PREFIX))
      .map((key) => JSON.parse(globalThis.sessionStorage.getItem(key)))
      .find((value) => value.flow === 'one_off');
    expect(stored).toMatchObject({
      flow: 'one_off',
      mode: 'create',
      automation_id: null,
      expected_revision: null,
      source_site: 'jobsdb',
      intent: 'listing',
    });
    expect(api.updateAutomation).not.toHaveBeenCalled();
  });

  it('cancels a conflicting detail run and prepares fresh authority only after cancelled acknowledgement', async () => {
    const detailDraft = {
      ...draft({ flow: 'one_off' }),
      intent: 'detail',
      execution: {
        backlog_kind: 'crawl_scope',
        limit_kind: 'stop_after',
        detail_run_cap: 10,
        crawl_mode: 'headless',
      },
    };
    storeDraft('conflict-draft', detailDraft);
    api.prepareDispatchPlan
      .mockResolvedValueOnce({
        ...plan(),
        readiness: {
          status: 'blocked',
          blockingErrors: [{
            code: 'DETAIL_RUN_CONFLICT',
            message: 'A detail run is active',
            context: { crawl_job_id: 'crawl/job 7' },
          }],
          capabilities: {},
        },
      })
      .mockResolvedValueOnce({
        ...plan(),
        content: {
          resolved_scope: { query_target_count: 0 },
          listing_settings: null,
          detail_settings: { limit: { kind: 'stop_after', detail_run_cap: 10 } },
        },
        detailTargetCount: 10,
      });
    api.cancelCrawlJob.mockResolvedValue({ status: 'cancellation_requested' });
    api.getCrawlJob.mockResolvedValue({ id: 'crawl/job 7', status: 'cancelled', progress: {} });
    const user = userEvent.setup();
    render(<TaskControlWizard hash="#scheduler/one-off/new?draft=conflict-draft&source=jobsdb&step=review" />);

    const conflictLink = await screen.findByRole('link', { name: 'crawl/job 7' });
    expect(conflictLink).toHaveAttribute('href', '#crawl-tasks?task=crawl%2Fjob%207');
    await user.click(screen.getByRole('button', { name: 'Cancel conflicting run' }));
    await user.click(screen.getByRole('button', { name: 'Request cancellation' }));

    expect(api.cancelCrawlJob).toHaveBeenCalledWith('crawl/job 7');
    expect(await screen.findByText(/is cancelling/)).toBeInTheDocument();
    await waitFor(() => expect(api.getCrawlJob).toHaveBeenCalled(), { timeout: 2500 });
    await waitFor(() => expect(api.prepareDispatchPlan).toHaveBeenCalledTimes(2));
    expect(await screen.findByText(/Frozen detail snapshot: 10 canonical targets/)).toBeInTheDocument();
  });
});
