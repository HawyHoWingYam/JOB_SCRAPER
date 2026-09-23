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
  getSourceClassifications: vi.fn(),
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

const classifications = {
  sourceSite: 'jobsdb',
  classifications: [],
};

const offertodayClassifications = {
  sourceSite: 'offertoday',
  classifications: [{
    id: 'offertoday:118000',
    label: 'Information Technology',
    nativeId: '118000',
    active: true,
  }, {
    id: 'offertoday:119000',
    label: 'Sales',
    nativeId: '119000',
    active: true,
  }],
};

function draft({ flow = 'automation', sourceSite = 'jobsdb', step = 'review' } = {}) {
  return {
    updated_at: '2026-07-21T00:00:00Z',
    flow,
    mode: 'create',
    automation_id: null,
    source_site: sourceSite,
    step,
    intent: 'listing',
    scope: { mode: 'all', classification_ids: [] },
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
    authoredScope: { mode: 'all' },
    resolvedScope: { query_target_count: 3 },
    listingWorkload: {
      query_target_count: 3,
      page_depth: 2,
      estimated_max_pages: 6,
      run_page_cap: 20,
      system_run_page_cap: 5000,
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
    lifecycleState: 'paused',
    sourceSite: 'jobsdb',
    configuration: {
      name: 'Saved Automation',
      description: null,
      cron_expression: '0 4 * * *',
      timezone: 'Asia/Hong_Kong',
      scope: {
        source_site: 'jobsdb',
        mode: 'all',
        classification_ids: [],
      },
      listing_settings: { crawl_mode: 'headless', page_depth: 2, run_page_cap: 20 },
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
    api.getSourceClassifications.mockResolvedValue(classifications);
  });

  it('saves an Automation only with the exact current server review fingerprint', async () => {
    storeDraft('automation-draft', draft());
    api.reviewAutomation.mockResolvedValue(review('server-review-fingerprint'));
    api.createAutomation.mockResolvedValue({ id: 'automation-1' });
    api.getAutomation.mockResolvedValue(automation());
    const user = userEvent.setup();

    render(<TaskControlWizard hash="#scheduler/automation/new?draft=automation-draft&source=jobsdb" />);

    const save = await screen.findByRole('button', { name: 'Save reviewed Automation' });
    await waitFor(() => expect(save).toBeEnabled());
    await user.click(save);
    await waitFor(() => expect(api.createAutomation).toHaveBeenCalledTimes(1));
    expect(api.getAutomation).toHaveBeenCalledWith('automation-1');
    expect(api.createAutomation.mock.calls[0][0]).toMatchObject({
      review_fingerprint: 'server-review-fingerprint',
      initial_state: 'paused',
      configuration: {
        name: 'Morning listings',
        scope: { source_site: 'jobsdb', mode: 'all', classification_ids: [] },
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
    expect(await screen.findByText('Run request accepted.')).toBeInTheDocument();
  });

  it('allows an explicit headless execution mode for CTgoodjobs', async () => {
    const ctClassifications = {
      sourceSite: 'ctgoodjobs',
      classifications: [],
    };
    api.getSourceClassifications.mockResolvedValue(ctClassifications);
    storeDraft('ct-draft', draft({ sourceSite: 'ctgoodjobs', step: 'execution' }));

    render(<TaskControlWizard hash="#scheduler/automation/new?draft=ct-draft&source=ctgoodjobs" />);

    const mode = await screen.findByLabelText('Crawl mode');
    expect(mode).toHaveValue('headless');
    fireEvent.change(mode, { target: { value: 'headed' } });
    expect(mode).toHaveValue('headed');
    fireEvent.change(mode, { target: { value: 'headless' } });
    expect(mode).toHaveValue('headless');
    expect(screen.getByText(/Headless is supported for automatic runs/)).toBeInTheDocument();
  });

  it('loads OfferToday major categories after the draft URL becomes stable', async () => {
    let resolveClassifications;
    api.getSourceClassifications.mockImplementation(() => new Promise((resolve) => {
      resolveClassifications = resolve;
    }));
    const { rerender } = render(<TaskControlWizard hash="#scheduler/one-off/new?source=offertoday&step=scope" />);

    rerender(<TaskControlWizard hash="#scheduler/one-off/new?source=offertoday&draft=offertoday-draft&step=scope" />);

    await waitFor(() => expect(api.getSourceClassifications).toHaveBeenCalledTimes(1));
    expect(screen.getByText('Loading major categories…')).toBeInTheDocument();
    resolveClassifications(offertodayClassifications);

    expect(screen.queryByRole('button', { name: 'All major categories' })).not.toBeInTheDocument();
    await userEvent.click(await screen.findByRole('button', { name: 'Choose one major category' }));
    const informationTechnology = screen.getByRole('radio', { name: 'Information Technology' });
    const sales = screen.getByRole('radio', { name: 'Sales' });
    await userEvent.click(informationTechnology);
    expect(informationTechnology).toBeChecked();
    await userEvent.click(sales);
    expect(sales).toBeChecked();
    expect(informationTechnology).not.toBeChecked();
  });

  it('keeps the scope step actionable when the category request fails', async () => {
    api.getSourceClassifications
      .mockRejectedValueOnce(new Error('Categories unavailable'))
      .mockResolvedValueOnce(offertodayClassifications);
    storeDraft('offertoday-error-draft', draft({ flow: 'one_off', sourceSite: 'offertoday', step: 'scope' }));
    const user = userEvent.setup();

    render(<TaskControlWizard hash="#scheduler/one-off/new?source=offertoday&draft=offertoday-error-draft&step=scope" />);

    expect(await screen.findByRole('alert')).toHaveTextContent('Categories unavailable');
    await user.click(screen.getByRole('button', { name: 'Retry loading categories' }));
    expect(await screen.findByRole('button', { name: 'Choose one major category' })).toBeInTheDocument();
  });

  it('shows editable OfferToday limits and delegates adaptive workload to review', async () => {
    const offerDraft = {
      ...draft({ flow: 'one_off', sourceSite: 'offertoday', step: 'execution' }),
      scope: { mode: 'selected', classification_ids: ['offertoday:118000'] },
      execution: { page_depth: 100, run_page_cap: 3600, crawl_mode: 'headless' },
    };
    storeDraft('offertoday-execution', offerDraft);
    api.getSourceClassifications.mockResolvedValue(offertodayClassifications);

    render(<TaskControlWizard hash="#scheduler/one-off/new?source=offertoday&draft=offertoday-execution&step=execution" />);

    const depth = await screen.findByLabelText('Page Depth per Query Target');
    expect(depth).toHaveValue(100);
    expect(depth).not.toHaveAttribute('max');
    expect(screen.getByText(/Server review resolves the current root/)).toBeInTheDocument();
    fireEvent.change(depth, { target: { value: '101' } });
    expect(screen.getByRole('button', { name: 'Continue' })).toBeEnabled();
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
    expect(await screen.findByText(/Frozen detail snapshot: 10 jobs/)).toBeInTheDocument();
  });
  it('edits existing configuration directly, preserves changes on refresh, and reports saved lifecycle', async () => {
    api.getAutomation.mockResolvedValue(automation());
    api.reviewAutomation.mockResolvedValue(review('updated-review'));
    api.updateAutomation.mockResolvedValue({ id: 'automation-1' });
    const user = userEvent.setup();
    const hash = '#scheduler/automation/automation-1/edit?draft=edit-draft&source=jobsdb&step=execution';
    const view = render(<TaskControlWizard hash={hash} />);
    await waitFor(() => expect(screen.getByLabelText('Name')).toHaveValue('Saved Automation'));
    expect(screen.queryByLabelText('Initial state')).not.toBeInTheDocument();
    await user.clear(screen.getByLabelText('Name'));
    await user.type(screen.getByLabelText('Name'), 'Changed schedule');
    view.unmount();
    render(<TaskControlWizard hash={hash} />);
    await waitFor(() => expect(screen.getByLabelText('Name')).toBeEnabled());
    expect(screen.getByLabelText('Name')).toHaveValue('Changed schedule');
    await user.click(screen.getByRole('button', { name: 'Continue' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save reviewed Automation' })).toBeEnabled());
    await user.click(screen.getByRole('button', { name: 'Save reviewed Automation' }));
    expect(api.updateAutomation).toHaveBeenCalledWith('automation-1', expect.objectContaining({ configuration: expect.objectContaining({ name: 'Changed schedule' }), review_fingerprint: 'updated-review' }));
    expect(api.updateAutomation.mock.calls[0][1]).not.toHaveProperty('initial_state');
    expect(await screen.findByText(/Paused — no scheduled runs/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Save reviewed Automation' })).not.toBeInTheDocument();
  });

  it('returns from review to configuration and uses fresh authority for the revised settings', async () => {
    storeDraft('correction', draft({ flow: 'one_off' }));
    api.prepareDispatchPlan.mockResolvedValueOnce(plan()).mockResolvedValue({ ...plan(), planId: 'plan-2', confirmationToken: 'token-2', planFingerprint: 'fingerprint-2' });
    api.dispatchPlan.mockResolvedValue({ crawlJobId: 'correct-task' });
    const user = userEvent.setup();
    render(<TaskControlWizard hash="#scheduler/one-off/new?draft=correction&source=jobsdb&step=review" />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Confirm and start' })).toBeEnabled());
    await user.click(screen.getByRole('button', { name: 'Edit configuration' }));
    fireEvent.change(screen.getByLabelText('Run Page Cap'), { target: { value: '30' } });
    await user.click(screen.getByRole('button', { name: 'Continue' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Confirm and start' })).toBeEnabled());
    expect(api.prepareDispatchPlan).toHaveBeenLastCalledWith(expect.objectContaining({ listing_settings: expect.objectContaining({ run_page_cap: 30 }) }));
    await user.click(screen.getByRole('button', { name: 'Confirm and start' }));
    expect(api.dispatchPlan).toHaveBeenCalledWith('plan-2', 'token-2', 'fingerprint-2');
    expect(await screen.findByRole('link', { name: 'View task' })).toHaveAttribute('href', '#crawl-tasks?task=correct-task');
  });

  it('blocks restored detail scope conflicts before review and keeps a correction available', async () => {
    storeDraft('invalid-detail', { ...draft({ flow: 'one_off', step: 'execution' }), intent: 'detail', scope: { mode: 'selected', classification_ids: ['jobsdb:1'] }, execution: { backlog_kind: 'source_backlog', limit_kind: 'stop_after', detail_run_cap: 10 } });
    const user = userEvent.setup();
    render(<TaskControlWizard hash="#scheduler/one-off/new?draft=invalid-detail&source=jobsdb&step=execution" />);
    expect(screen.getByRole('alert')).toHaveTextContent('does not match your scope');
    expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Entire source backlog' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Chosen categories' }));
    expect(screen.getByRole('button', { name: 'Continue' })).toBeEnabled();
    expect(api.prepareDispatchPlan).not.toHaveBeenCalled();
  });

  it('shows expired review guidance and prevents dispatch', async () => {
    storeDraft('expired', draft({ flow: 'one_off' }));
    api.prepareDispatchPlan.mockResolvedValue({ ...plan(), expiresAt: '2000-01-01T00:00:00Z' });
    render(<TaskControlWizard hash="#scheduler/one-off/new?draft=expired&source=jobsdb&step=review" />);
    expect(await screen.findByRole('alert')).toHaveTextContent('review has expired');
    expect(screen.getByRole('button', { name: 'Confirm and start' })).toBeDisabled();
    expect(api.dispatchPlan).not.toHaveBeenCalled();
  });

  it('keeps input across step navigation when draft storage is unavailable', async () => {
    storeDraft('memory-draft', draft({ flow: 'one_off', step: 'execution' }));
    const user = userEvent.setup();
    const view = render(<TaskControlWizard hash="#scheduler/one-off/new?draft=memory-draft&source=jobsdb&step=execution" />);
    const storageRead = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('Unavailable'); });
    const storageWrite = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('Unavailable'); });
    try {
      fireEvent.change(screen.getByLabelText('Run Page Cap'), { target: { value: '37' } });
      await user.click(screen.getByRole('button', { name: 'Back', exact: true }));
      view.rerender(<TaskControlWizard hash="#scheduler/one-off/new?draft=memory-draft&source=jobsdb&step=scope" />);
      await user.click(screen.getByRole('button', { name: 'Continue' }));
      view.rerender(<TaskControlWizard hash="#scheduler/one-off/new?draft=memory-draft&source=jobsdb&step=execution" />);
      expect(screen.getByLabelText('Run Page Cap')).toHaveValue(37);
    } finally {
      storageRead.mockRestore();
      storageWrite.mockRestore();
    }
  });

  it('retries loading an Automation after a read failure', async () => {
    api.getAutomation.mockRejectedValueOnce(new Error('Settings unavailable')).mockResolvedValue(automation());
    const user = userEvent.setup();
    render(<TaskControlWizard hash="#scheduler/automation/automation-1/edit?draft=retry-edit&source=jobsdb&step=execution" />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Settings unavailable');
    await user.click(screen.getByRole('button', { name: 'Retry loading Automation' }));
    await waitFor(() => expect(screen.getByLabelText('Name')).toHaveValue('Saved Automation'));
    expect(screen.getByRole('button', { name: 'Continue' })).toBeEnabled();
  });

});
