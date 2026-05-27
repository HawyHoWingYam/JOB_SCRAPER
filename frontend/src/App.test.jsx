import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

vi.mock('./components/charts/SkillChart', () => ({
  default: () => <div>Skill Chart Stub</div>,
}));

vi.mock('./components/charts/CategoryChart', () => ({
  default: () => <div>Category Chart Stub</div>,
}));

import App from './App';

describe('App lazy views', () => {
  it('loads the settings view when navigated from the sidebar', async () => {
    globalThis.fetch = vi.fn((input) => {
      const url = String(input);

      if (url.includes('/api/v1/settings/ai')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            persisted_config: {
              llm_provider: null,
              company_llm_provider: null,
              ai_enrichment_run_concurrency: 8,
              anthropic: { model: null, base_url: null, has_api_key: false, api_key_preview: null },
              gemini: { model: null, has_api_key: false, api_key_preview: null },
              custom: { model: null, base_url: null, api_format: null, has_api_key: false, api_key_preview: null },
              zhipu: { has_api_key: false, api_key_preview: null },
              company_anthropic: { has_api_key: false, api_key_preview: null, model: null, base_url: null },
              company_gemini: { has_api_key: false, api_key_preview: null, model: null },
              company_custom: { has_api_key: false, api_key_preview: null, model: null, base_url: null, api_format: null },
              company_zhipu: { has_api_key: false, api_key_preview: null },
            },
            effective_config: {
              llm_provider: null,
              company_llm_provider: null,
              ai_enrichment_run_concurrency: 8,
              anthropic: { model: null, base_url: null, has_api_key: false },
              gemini: { model: null, has_api_key: false },
              custom: { model: null, base_url: null, api_format: null, has_api_key: false },
              zhipu: { has_api_key: false },
              company_anthropic: { has_api_key: false, api_key_preview: null, model: null, base_url: null },
              company_gemini: { has_api_key: false, api_key_preview: null, model: null },
              company_custom: { has_api_key: false, api_key_preview: null, model: null, base_url: null, api_format: null },
              company_zhipu: { has_api_key: false, api_key_preview: null },
            },
            runtime_status: {
              configured_provider: null,
              active_provider: null,
              provider: null,
              model: null,
              is_degraded: true,
              degradation_reason: 'Profile is not configured',
              requires_test: false,
              is_ready: false,
              last_test_status: 'untested',
            },
            company_runtime_status: {
              configured_provider: null,
              active_provider: null,
              provider: null,
              model: null,
              is_degraded: true,
              degradation_reason: 'Profile is not configured',
              requires_test: false,
              is_ready: false,
              last_test_status: 'untested',
            },
          }),
        });
      }

      return Promise.reject(new Error(`Unhandled fetch: ${url}`));
    });

    render(<App />);

    await userEvent.click(screen.getByRole('button', { name: /^settings$/i }));

    expect(await screen.findByRole('heading', { level: 1, name: /ai runtime/i })).toBeInTheDocument();
  });

  it('loads the scheduler view when navigated from the sidebar', async () => {
    globalThis.fetch = vi.fn((input) => {
      const url = String(input);

      if (url === '/api/v1/stats/overview') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            total_jobs: 0,
            enriched_jobs: 0,
            pending_enrichment: 0,
          }),
        });
      }

      if (url === '/api/v1/ai/overview') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            failed_jobs: 0,
            running_runs: 0,
            last_completed_run: null,
          }),
        });
      }

      if (url === '/api/v1/schedules') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ schedules: [] }),
        });
      }

      if (url === '/api/categories?source_site=jobsdb') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ categories: [] }),
        });
      }

      if (url === '/api/v1/capabilities') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            scheduler: {
              available: true,
              manual_run_available: true,
              owner: 'scheduler-worker',
              worker_name: 'scheduler-worker',
              heartbeat_status: 'fresh',
              last_heartbeat_at: null,
              last_reconcile_at: null,
              reason: null,
            },
          }),
        });
      }

      if (url === '/api/v1/scrape/progress') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ active: {}, all: {}, has_active: false }),
        });
      }

      return Promise.reject(new Error(`Unhandled fetch: ${url}`));
    });

    render(<App />);

    await userEvent.click(screen.getByRole('button', { name: /scheduler/i }));

    expect(await screen.findByText(/task control board/i, {}, { timeout: 5000 })).toBeInTheDocument();
  });
});
