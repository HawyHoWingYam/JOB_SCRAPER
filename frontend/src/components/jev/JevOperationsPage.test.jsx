import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import JevOperationsPage from './JevOperationsPage';


function jsonResponse(payload, status = 200) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
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

  it('previews all selected operations for free and starts only after explicit confirmation', async () => {
    const user = userEvent.setup();
    render(<JevOperationsPage />);

    await screen.findByText('No Jev Job batches yet.');
    expect(globalThis.fetch.mock.calls.filter(([, init = {}]) => init.method === 'POST'))
      .toHaveLength(0);

    await user.click(screen.getByLabelText('Possible same vacancy'));
    await user.click(screen.getByLabelText('Related Jobs'));
    await user.type(screen.getByLabelText('Explicit Job UUIDs'), '11111111-1111-4111-8111-111111111111');
    await user.click(screen.getByRole('button', { name: 'Preview batch' }));

    expect(await screen.findByRole('status')).toHaveTextContent('1 Jobs selected');
    const previewCall = globalThis.fetch.mock.calls.find(
      ([input]) => String(input) === '/api/jev/operations/preview',
    );
    expect(JSON.parse(previewCall[1].body)).toEqual(expect.objectContaining({
      job_ids: ['11111111-1111-4111-8111-111111111111'],
      operations: ['skills', 'duplicate', 'related_jobs'],
      force_reevaluation: false,
    }));
    expect(globalThis.fetch.mock.calls.filter(([input, init = {}]) => (
      String(input) === '/api/jev/operations/batches' && init.method === 'POST'
    ))).toHaveLength(0);

    await user.click(screen.getByRole('button', { name: 'Start selected operations' }));
    await waitFor(() => expect(globalThis.fetch.mock.calls.filter(([input, init = {}]) => (
      String(input) === '/api/jev/operations/batches' && init.method === 'POST'
    ))).toHaveLength(1));
    const startCall = globalThis.fetch.mock.calls.find(([input, init = {}]) => (
      String(input) === '/api/jev/operations/batches' && init.method === 'POST'
    ));
    expect(JSON.parse(startCall[1].body)).toEqual(expect.objectContaining({
      operations: ['skills', 'duplicate', 'related_jobs'],
      preview_fingerprint: 'a'.repeat(64),
    }));
    expect(startCall[1].headers['Idempotency-Key']).toBeTruthy();
  });
});
