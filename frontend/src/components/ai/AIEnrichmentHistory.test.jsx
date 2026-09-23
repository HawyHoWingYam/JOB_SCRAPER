import { render, screen, waitFor, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { apiFetchJson } from '../../api/client';
import AIEnrichmentHistory from './AIEnrichmentHistory';

vi.mock('../../api/client', () => ({ apiFetchJson: vi.fn() }));
const failed = { id: 'older-run', status: 'completed_with_failures', total_items: 3, failed_items: 2, completed_items: 1, created_at: '2026-09-23T08:00:00Z' };
const props = { revision: 0, busy: false, hasActiveRun: false, onRetry: vi.fn(), onResume: vi.fn(), onStop: vi.fn() };
beforeEach(() => {
  window.history.replaceState(null, '', '#ai?run=older-run');
  apiFetchJson.mockImplementation(async url => {
    if (url.includes('?limit=')) return { runs: [failed] };
    if (url.includes('/items')) return { items: [{ id: 'item-1', job_id: 'job-1', status: 'failed', attempt_count: 2, error_message: 'Provider timed out' }] };
    return failed;
  });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); window.history.replaceState(null, '', '#ai'); });

it('inspects an exact older run and retries only its failures', async () => {
  render(<AIEnrichmentHistory {...props} />);
  expect(await screen.findByText('Provider timed out')).toBeInTheDocument();
  expect(screen.getByText('failed · 2 attempts')).toBeInTheDocument();
  expect(screen.getByRole('heading', { name: 'Run details: older-run' })).toHaveFocus();
  await userEvent.click(screen.getByRole('button', { name: 'Retry this run’s failed jobs (2)' }));
  expect(props.onRetry).toHaveBeenCalledWith(failed);
});

it('keeps retry disabled while another run is active and filters excluded evidence separately', async () => {
  render(<AIEnrichmentHistory {...props} hasActiveRun />);
  expect(await screen.findByRole('button', { name: 'Retry this run’s failed jobs (2)' })).toBeDisabled();
  await userEvent.selectOptions(screen.getByLabelText('Item outcome'), 'excluded');
  await waitFor(() => expect(apiFetchJson).toHaveBeenCalledWith('/api/ai/runs/older-run/items?status=excluded', expect.anything()));
  expect(screen.getByText(/Excluded jobs were not attempted/)).toBeInTheDocument();
});

it('recovers an unknown run error via a task-scoped retry', async () => {
  let unavailable = true;
  apiFetchJson.mockImplementation(async url => {
    if (url.includes('?limit=')) return { runs: [] };
    if (unavailable) throw new Error('Run not found');
    return url.includes('/items') ? { items: [] } : failed;
  });
  render(<AIEnrichmentHistory {...props} />);
  const retry = await screen.findByRole('button', { name: 'Retry run details' });
  unavailable = false;
  await userEvent.click(retry);
  expect(await screen.findByText('No items match this outcome.')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Retry this run’s failed jobs (2)' })).toBeEnabled();
});

it('links waiting runs to their exact crawl and preserves exclusion-only authority', async () => {
  const waiting = { ...failed, status: 'waiting', failed_items: 0, trigger_crawl_job_id: 'crawl/specific', pending_gate_crawl_job_status: 'running' };
  apiFetchJson.mockImplementation(async url => url.includes('?limit=') ? { runs: [waiting] } : url.includes('/items') ? { items: [] } : waiting);
  render(<AIEnrichmentHistory {...props} />);
  expect(await screen.findByRole('link', { name: 'Open linked crawl task' })).toHaveAttribute('href', '#crawl-tasks?task=crawl%2Fspecific');
  expect(screen.queryByRole('button', { name: /Retry this run/ })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Stop this run' })).toBeEnabled();
});
