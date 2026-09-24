import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import JevOperationsPage from './JevOperationsPage';


function jsonResponse(payload, status = 200) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers(),
    json: async () => payload,
  });
}


describe('JevOperationsPage', () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn((input, init = {}) => {
      const path = String(input);
      if (path === '/api/jev/operations/batches' && !init.method) {
        return jsonResponse({ batches: [] });
      }
      if (path === '/api/jev/runs' && !init.method) {
        return jsonResponse({ runs: [] });
      }
      if (path === '/api/jev/operations/preview') {
        return jsonResponse({
          preview_fingerprint: 'a'.repeat(64),
          selected_job_count: 1,
          operations: {
            skills: { eligible: 1, skipped: 0 },
            duplicate: { eligible: 1, skipped: 0 },
            related_jobs: { eligible: 1, skipped: 0 },
          },
        });
      }
      if (path === '/api/jev/operations/batches' && init.method === 'POST') {
        return jsonResponse({ id: 'batch-1', status: 'pending' }, 201);
      }
      throw new Error(`Unhandled request: ${path}`);
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('starts all selected operations only after one explicit confirmation', async () => {
    const user = userEvent.setup();
    render(<JevOperationsPage />);

    await screen.findByText('No Jev Job batches yet. Configure a scope above, then start one manually.');
    expect(globalThis.fetch.mock.calls.filter(([, init = {}]) => init.method === 'POST'))
      .toHaveLength(0);

    await user.click(screen.getByLabelText(/Possible same vacancy/));
    await user.click(screen.getByLabelText(/Related Jobs/));
    await user.type(screen.getByLabelText('Explicit Job UUIDs'), '11111111-1111-4111-8111-111111111111');
    await user.type(screen.getByLabelText('Posted from'), '2026-09-01');
    await user.type(screen.getByLabelText('Posted to'), '2026-09-30');
    await user.clear(screen.getByLabelText('Maximum matching Jobs'));
    await user.type(screen.getByLabelText('Maximum matching Jobs'), '25000');
    await user.clear(screen.getByLabelText('Jobs per execution batch'));
    await user.type(screen.getByLabelText('Jobs per execution batch'), '500');
    await user.clear(screen.getByLabelText('Start from execution batch'));
    await user.type(screen.getByLabelText('Start from execution batch'), '9');
    expect(globalThis.fetch.mock.calls.some(
      ([input]) => String(input) === '/api/jev/operations/preview',
    )).toBe(false);
    expect(globalThis.fetch.mock.calls.filter(([input, init = {}]) => (
      String(input) === '/api/jev/operations/batches' && init.method === 'POST'
    ))).toHaveLength(0);

    await user.click(screen.getByRole('button', { name: 'Start Jev batch…' }));
    expect(screen.getByRole('dialog')).toHaveTextContent('Previously successful unchanged work will remain untouched.');
    expect(screen.getByRole('dialog')).toHaveTextContent('Posted date: 2026-09-01 through 2026-09-30, inclusive.');
    expect(screen.getByRole('dialog')).toHaveTextContent('The first up to 25000 matching Jobs define the scope');
    expect(screen.getByRole('dialog')).toHaveTextContent('execution batches 9 through 50');
    expect(globalThis.fetch.mock.calls.filter(([input, init = {}]) => (
      String(input) === '/api/jev/operations/batches' && init.method === 'POST'
    ))).toHaveLength(0);
    await user.click(screen.getByRole('button', { name: 'Confirm and start' }));
    await waitFor(() => expect(globalThis.fetch.mock.calls.filter(([input, init = {}]) => (
      String(input) === '/api/jev/operations/batches' && init.method === 'POST'
    ))).toHaveLength(1));
    const startCall = globalThis.fetch.mock.calls.find(([input, init = {}]) => (
      String(input) === '/api/jev/operations/batches' && init.method === 'POST'
    ));
    expect(JSON.parse(startCall[1].body)).toEqual(expect.objectContaining({
      job_ids: ['11111111-1111-4111-8111-111111111111'],
      posted_date_from: '2026-09-01',
      posted_date_to: '2026-09-30',
      max_jobs: 25000,
      execution_batch_size: 500,
      start_execution_batch: 9,
      operations: ['skills', 'duplicate', 'related_jobs'],
      force_reevaluation: false,
    }));
    expect(JSON.parse(startCall[1].body).preview_fingerprint).toBeUndefined();
    expect(new Headers(startCall[1].headers).get('Idempotency-Key')).toBeTruthy();
    expect(startCall[1].signal).toBeUndefined();
  });

  it('reuses the same idempotency key when a batch start must be retried', async () => {
    const user = userEvent.setup();
    let startAttempts = 0;
    globalThis.fetch = vi.fn((input, init = {}) => {
      const path = String(input);
      if (path === '/api/jev/operations/batches' && !init.method) {
        return jsonResponse({ batches: [] });
      }
      if (path === '/api/jev/runs' && !init.method) {
        return jsonResponse({ runs: [] });
      }
      if (path === '/api/jev/operations/preview') {
        return jsonResponse({
          preview_fingerprint: 'b'.repeat(64),
          selected_job_count: 1,
          operations: { skills: { eligible: 1, skipped: 0 } },
        });
      }
      if (path === '/api/jev/operations/batches' && init.method === 'POST') {
        startAttempts += 1;
        return startAttempts === 1
          ? Promise.reject(new TypeError('connection interrupted'))
          : jsonResponse({ id: 'batch-1', status: 'pending' }, 201);
      }
      throw new Error(`Unhandled request: ${path}`);
    });

    render(<JevOperationsPage />);
    await screen.findByText('No Jev Job batches yet. Configure a scope above, then start one manually.');
    await user.click(screen.getByRole('button', { name: 'Start Jev batch…' }));
    await user.click(screen.getByRole('button', { name: 'Confirm and start' }));
    expect(await screen.findAllByText('connection interrupted')).toHaveLength(2);

    await user.click(screen.getByRole('button', { name: 'Confirm and start' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());

    const startCalls = globalThis.fetch.mock.calls.filter(([input, init = {}]) => (
      String(input) === '/api/jev/operations/batches' && init.method === 'POST'
    ));
    expect(startCalls).toHaveLength(2);
    const keys = startCalls.map(([, init]) => new Headers(init.headers).get('Idempotency-Key'));
    expect(keys[0]).toBeTruthy();
    expect(keys[1]).toBe(keys[0]);
    expect(startCalls.every(([, init]) => init.signal === undefined)).toBe(true);
  });

  it('keeps run history usable when the operations route is unavailable and retries locally', async () => {
    const user = userEvent.setup();
    let batchRouteAvailable = false;
    globalThis.fetch = vi.fn((input) => {
      const path = String(input);
      if (path === '/api/jev/operations/batches') {
        return batchRouteAvailable
          ? jsonResponse({ batches: [] })
          : jsonResponse({ detail: 'Not Found' }, 404);
      }
      if (path === '/api/jev/runs') {
        return jsonResponse({
          runs: [{
            id: 'run-1', purpose: 'configuration_smoke_test', status: 'completed',
            total_items: 1, completed_items: 1, failed_items: 0, cancelled_items: 0,
          }],
        });
      }
      throw new Error(`Unhandled request: ${path}`);
    });

    render(<JevOperationsPage />);

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Jev Operations is not available in the running backend. Update or restart the backend, then retry.',
    );
    expect(screen.getByLabelText('Jev run run-1')).toHaveTextContent('configuration smoke test');
    expect(screen.queryByText('No Jev Job batches yet. Configure a scope above, then start one manually.')).not.toBeInTheDocument();

    batchRouteAvailable = true;
    await user.click(screen.getByRole('button', { name: 'Retry loading' }));
    expect(await screen.findByText('No Jev Job batches yet. Configure a scope above, then start one manually.')).toBeInTheDocument();
    expect(screen.queryByText(/not available in the running backend/i)).not.toBeInTheDocument();
  });

  it('requires explicit confirmation before force correction starts', async () => {
    const user = userEvent.setup();
    render(<JevOperationsPage />);
    await screen.findByText('No Jev Job batches yet. Configure a scope above, then start one manually.');

    await user.click(screen.getByRole('checkbox', { name: /Force correction/ }));
    await user.click(screen.getByRole('button', { name: 'Start Jev batch…' }));

    expect(screen.getByRole('dialog')).toHaveTextContent(
      'successful unchanged results may be evaluated and corrected',
    );
    expect(globalThis.fetch.mock.calls.filter(([input, init = {}]) => (
      String(input) === '/api/jev/operations/batches' && init.method === 'POST'
    ))).toHaveLength(0);

    await user.click(screen.getByRole('button', { name: 'Confirm force correction and start' }));
    await waitFor(() => expect(globalThis.fetch.mock.calls.filter(([input, init = {}]) => (
      String(input) === '/api/jev/operations/batches' && init.method === 'POST'
    ))).toHaveLength(1));
    const startCall = globalThis.fetch.mock.calls.find(([input, init = {}]) => (
      String(input) === '/api/jev/operations/batches' && init.method === 'POST'
    ));
    expect(JSON.parse(startCall[1].body).force_reevaluation).toBe(true);
  });

  it('can freeze every matching Job into one manually started durable batch', async () => {
    const user = userEvent.setup();
    render(<JevOperationsPage />);
    await screen.findByText('No Jev Job batches yet. Configure a scope above, then start one manually.');

    await user.click(screen.getByLabelText(/Include all matching Jobs/));
    expect(screen.getByLabelText('Maximum matching Jobs')).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Start Jev batch…' }));
    expect(screen.getByRole('dialog')).toHaveTextContent(
      'All matching Jobs define the scope',
    );
    await user.click(screen.getByRole('button', { name: 'Confirm and start' }));
    const startCall = globalThis.fetch.mock.calls.find(([input, init = {}]) => (
      String(input) === '/api/jev/operations/batches' && init.method === 'POST'
    ));
    expect(JSON.parse(startCall[1].body)).toEqual(expect.objectContaining({
      job_offset: 0,
      max_jobs: null,
      execution_batch_size: 500,
      start_execution_batch: 1,
    }));
  });

  it('separates batch authoring, advisory tools, and provider history into workspaces', async () => {
    const user = userEvent.setup();
    render(<JevOperationsPage />);
    await screen.findByText('No Jev Job batches yet. Configure a scope above, then start one manually.');

    const batchesPanel = document.getElementById('jev-batches-panel');
    const toolsTab = screen.getByRole('tab', { name: /Advisory tools/ });
    const historyTab = screen.getByRole('tab', { name: /Run history/ });
    expect(screen.getByRole('heading', { name: 'Choose scope and operations' })).toBeVisible();
    expect(screen.getByRole('heading', { name: 'Advisory tools', hidden: true })).not.toBeVisible();

    await user.click(toolsTab);
    expect(screen.getByRole('heading', { name: 'Advisory tools' })).toBeVisible();
    expect(screen.getByRole('heading', { name: 'Choose scope and operations', hidden: true })).not.toBeVisible();

    await user.click(historyTab);
    expect(screen.getByRole('heading', { name: 'Provider run history' })).toBeVisible();
    expect(batchesPanel).not.toBeVisible();
  });

  it('polls active batch history silently once per minute', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      let batchReads = 0;
      globalThis.fetch = vi.fn((input, init = {}) => {
        const path = String(input);
        if (path === '/api/jev/operations/batches' && !init.method) {
          batchReads += 1;
          if (batchReads > 1) return new Promise(() => {});
          return jsonResponse({
            batches: [{
              id: 'active-batch', status: 'running', operations: ['skills'],
              total_items: 300, pending_items: 299, running_items: 1,
              completed_items: 0, failed_items: 0, skipped_items: 0,
              execution_batch_size: 100, current_execution_batch: 1,
              total_execution_batches: 10,
            }],
          });
        }
        if (path === '/api/jev/runs' && !init.method) return jsonResponse({ runs: [] });
        throw new Error(`Unhandled request: ${path}`);
      });

      render(<JevOperationsPage />);
      await screen.findByLabelText('Jev batch active-batch');
      expect(batchReads).toBe(1);

      await act(async () => vi.advanceTimersByTimeAsync(59_000));
      expect(batchReads).toBe(1);

      await act(async () => vi.advanceTimersByTimeAsync(1_000));
      expect(batchReads).toBe(2);
      expect(screen.queryByText('Refreshing Jev Job batches…')).not.toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Refresh history' })).toBeEnabled();
    } finally {
      vi.useRealTimers();
    }
  });

  it('does not let a frontend timer abort manually started provider work', async () => {
    vi.useFakeTimers();
    try {
      let executeSignal;
      globalThis.fetch = vi.fn((input, init = {}) => {
        const path = String(input);
        if (path === '/api/jev/operations/batches' && !init.method) {
          return jsonResponse({ batches: [] });
        }
        if (path === '/api/jev/runs' && !init.method) {
          return jsonResponse({ runs: [] });
        }
        if (path === '/api/jev/runs' && init.method === 'POST') {
          return jsonResponse({ id: 'run-1', status: 'pending' }, 201);
        }
        if (path === '/api/jev/runs/run-1/execute-next') {
          executeSignal = init.signal;
          return new Promise((_resolve, reject) => {
            init.signal?.addEventListener('abort', () => {
              reject(new DOMException('signal is aborted without reason', 'AbortError'));
            });
          });
        }
        throw new Error(`Unhandled request: ${path}`);
      });

      render(<JevOperationsPage />);
      await act(async () => Promise.resolve());
      expect(screen.getByText('No Jev Job batches yet. Configure a scope above, then start one manually.'))
        .toBeInTheDocument();
      fireEvent.click(screen.getByRole('tab', { name: /Advisory tools/ }));
      fireEvent.click(screen.getByRole('button', { name: 'Run one Jev smoke request' }));
      await act(async () => Promise.resolve());

      await act(async () => vi.advanceTimersByTimeAsync(700_000));

      expect(executeSignal).toBeUndefined();
      expect(screen.queryByText(/Jev did not respond before the request timeout/))
        .not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

});
