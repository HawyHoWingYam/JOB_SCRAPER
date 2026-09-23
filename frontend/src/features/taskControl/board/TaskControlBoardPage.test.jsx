import React from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  cancelCrawlJob: vi.fn(),
  dismissFailedRunAttention: vi.fn(),
  getTaskControlBoard: vi.fn(),
  permanentlyDeleteAutomation: vi.fn(),
  resetBrowserProfile: vi.fn(),
  resumeManualTask: vi.fn(),
  reviewAutomationDelete: vi.fn(),
  transitionAutomation: vi.fn(),
}));
vi.mock('./boardApi', () => api);

import TaskControlBoardPage from './TaskControlBoardPage';

const action = (name, enabled = true) => ({ action: name, enabled, reasonCode: enabled ? null : 'BLOCKED' });
const automation = {
  id: 'automation-1', lifecycleState: 'active', name: 'Morning listings',
  sourceSite: 'jobsdb', phase: 'listing', mode: 'headless',
  authoredScope: { mode: 'all', classification_ids: [] },
  schedule: { cronExpression: '0 4 * * *', timezone: 'Asia/Hong_Kong', humanSummary: 'Daily at 04:00 · Asia/Hong_Kong', nextRunAt: '2099-07-21T00:00:00Z' },
  latestOutcome: null,
  resolvedScopeSummary: { query_target_count: 25 }, currentRun: null, scopeReviewReason: null,
  actions: [action('edit'), action('run_now'), action('pause'), action('resume', false), action('archive')],
  createdAt: '2026-07-21T00:00:00Z', updatedAt: '2026-07-21T00:00:00Z', lastRunAt: null,
};
const board = {
  selectedSource: 'jobsdb',
  sourceSummaries: [
    { sourceSite: 'jobsdb', state: 'running', attentionCount: 0, activeRunCount: 1, upcomingCount: 1 },
    { sourceSite: 'ctgoodjobs', state: 'attention', attentionCount: 2, activeRunCount: 0, upcomingCount: 0 },
    { sourceSite: 'offertoday', state: 'all_clear', attentionCount: 0, activeRunCount: 0, upcomingCount: 0 },
  ],
  needsAttention: [],
  activeRuns: [{
    run: { id: 'task-1', sourceSite: 'jobsdb', phase: 'listing', mode: 'headless', status: 'running', listingWorkload: { query_target_count: 25, pages_requested: 2, run_page_cap: 25, page_depth: 1 }, detailSnapshot: null },
    issue: null, manualActionGuidance: null, actions: [action('view_task'), action('view_logs'), action('cancel')],
  }],
  upcoming: [automation], archivedAutomations: [], allClear: false, refreshedAt: '2026-07-21T00:00:00Z',
};

describe('TaskControlBoardPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getTaskControlBoard.mockResolvedValue(board);
    api.transitionAutomation.mockResolvedValue({});
    window.location.hash = '#scheduler?source=jobsdb';
  });

  it('renders backend-owned sections/source state and preserves Automation order in a semantic list', async () => {
    render(<TaskControlBoardPage hash="#scheduler?source=jobsdb" />);
    expect(await screen.findByRole('heading', { name: 'Active runs' })).toBeInTheDocument();
    expect(screen.getByRole('list', { name: 'Upcoming Automation operations' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Morning listings' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Open CTgoodjobs (2)' })).toBeInTheDocument();
    expect(api.getTaskControlBoard).toHaveBeenCalledWith('jobsdb', expect.any(Object));
  });

  it('applies lifecycle actions to the current row and refetches', async () => {
    const user = userEvent.setup();
    render(<TaskControlBoardPage hash="#scheduler?source=jobsdb" />);
    await user.click(await screen.findByRole('button', { name: 'Pause' }));
    await waitFor(() => expect(api.transitionAutomation).toHaveBeenCalledWith('automation-1', 'pause'));
    await waitFor(() => expect(api.getTaskControlBoard.mock.calls.length).toBeGreaterThan(1));
  });

  it('renders repeated action descriptors without duplicate React keys', async () => {
    api.getTaskControlBoard.mockResolvedValue({
      ...board,
      activeRuns: [{
        ...board.activeRuns[0],
        actions: [action('view_task'), action('view_task')],
      }],
    });
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});

    render(<TaskControlBoardPage hash="#scheduler?source=jobsdb" />);

    await screen.findByRole('heading', { name: 'Active runs' });
    expect(consoleError).not.toHaveBeenCalledWith(
      expect.stringContaining('Encountered two children with the same key'),
    );
    consoleError.mockRestore();
  });

  it('routes safe profile reset actions to the crawl-task recovery endpoint', async () => {
    const user = userEvent.setup();
    api.getTaskControlBoard.mockResolvedValue({
      ...board,
      activeRuns: [{
        ...board.activeRuns[0],
        actions: [action('reset_browser_profile')],
      }],
    });
    api.resetBrowserProfile.mockResolvedValue({ status: 'reset' });

    render(<TaskControlBoardPage hash="#scheduler?source=jobsdb" />);
    await user.click(await screen.findByRole('button', { name: 'Reset browser profile' }));

    await waitFor(() => expect(api.resetBrowserProfile).toHaveBeenCalledWith('task-1'));
    await waitFor(() => expect(api.getTaskControlBoard.mock.calls.length).toBeGreaterThan(1));
  });

  it('dismisses only the displayed failed event immediately and refetches', async () => {
    const user = userEvent.setup();
    api.getTaskControlBoard.mockResolvedValue({
      ...board,
      needsAttention: [{
        id: 'run:failed-task:failed_run', kind: 'failed_run', priority: 40,
        sourceSite: 'jobsdb', code: 'RUN_FAILED', title: 'Run failed', summary: 'Old failure',
        entityKind: 'run', entityId: 'failed-task', failureEventSequence: 7,
        primaryAction: action('view_task'),
        secondaryActions: [action('view_task'), action('view_logs'), action('dismiss_failed_run')],
      }],
    });
    api.dismissFailedRunAttention.mockResolvedValue({ replayed: false });

    render(<TaskControlBoardPage hash="#scheduler?source=jobsdb" />);
    await screen.findByRole('button', { name: 'Dismiss' });
    const failureCard = within(screen.getByRole('button', { name: 'Dismiss' }).closest('article'));
    expect(failureCard.getAllByRole('button', { name: 'View task', exact: true })).toHaveLength(1);
    expect(failureCard.getByRole('button', { name: 'View logs' })).toBeEnabled();
    await user.click(screen.getByRole('button', { name: 'Dismiss' }));

    await waitFor(() => expect(api.dismissFailedRunAttention).toHaveBeenCalledWith('failed-task', 7));
    await waitFor(() => expect(api.getTaskControlBoard.mock.calls.length).toBeGreaterThan(1));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('keeps a failed-run dismissal error visible', async () => {
    const user = userEvent.setup();
    api.getTaskControlBoard.mockResolvedValue({
      ...board,
      needsAttention: [{
        id: 'run:failed-task:failed_run', kind: 'failed_run', priority: 40,
        sourceSite: 'jobsdb', code: 'RUN_FAILED', title: 'Run failed', summary: 'Old failure',
        entityKind: 'run', entityId: 'failed-task', failureEventSequence: 7,
        primaryAction: action('view_task'),
        secondaryActions: [action('dismiss_failed_run')],
      }],
    });
    api.dismissFailedRunAttention.mockRejectedValue(new Error('Dismiss was stale'));

    render(<TaskControlBoardPage hash="#scheduler?source=jobsdb" />);
    await user.click(await screen.findByRole('button', { name: 'Dismiss' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Dismiss was stale');
  });
  it('opens editing at configuration and exposes disabled reasons without hover', async () => {
    const user = userEvent.setup();
    render(<TaskControlBoardPage hash="#scheduler?source=jobsdb" />);
    const resume = await screen.findByRole('button', { name: 'Resume', exact: true });
    expect(resume).toBeDisabled();
    expect(resume).toHaveAccessibleDescription(/Unavailable in the current state/);
    await user.click(screen.getByRole('button', { name: 'Edit', exact: true }));
    expect(window.location.hash).toContain('source=jobsdb');
    expect(window.location.hash).toContain('step=execution');
  });

  it('keeps prior board data visible when a post-action refresh fails and allows retry', async () => {
    api.getTaskControlBoard.mockResolvedValueOnce(board).mockRejectedValueOnce(new Error('Board offline')).mockResolvedValue(board);
    const user = userEvent.setup();
    render(<TaskControlBoardPage hash="#scheduler?source=jobsdb" />);
    await user.click(await screen.findByRole('button', { name: 'Pause' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Showing the last successful update');
    expect(screen.getByRole('heading', { name: 'Morning listings' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Retry refresh' }));
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
  });

  it('confirms cancellation and reports only the request acknowledgement', async () => {
    api.cancelCrawlJob.mockResolvedValue({ status: 'cancellation_requested' });
    const user = userEvent.setup();
    render(<TaskControlBoardPage hash="#scheduler?source=jobsdb" />);
    await user.click(await screen.findByRole('button', { name: 'Cancel', exact: true }));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(api.cancelCrawlJob).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Request cancellation' }));
    expect(api.cancelCrawlJob).toHaveBeenCalledWith('task-1');
    expect(await screen.findByText('Cancellation requested; waiting for acknowledgement.')).toBeInTheDocument();
  });

});
