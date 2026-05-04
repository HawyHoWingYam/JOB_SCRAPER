import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../charts/SkillChart', () => ({
  default: () => <div>Skill Chart Stub</div>,
}));

vi.mock('../charts/CategoryChart', () => ({
  default: () => <div>Category Chart Stub</div>,
}));

import App from '../../App';
import AISettingsPage from './AISettingsPage';

function mockJsonResponse(payload, options = {}) {
  return Promise.resolve({
    ok: options.ok ?? true,
    status: options.status ?? 200,
    json: async () => payload,
  });
}

function clonePayload(payload) {
  return JSON.parse(JSON.stringify(payload));
}

const aiSettingsPayload = {
  persisted_config: {
    llm_provider: 'gemini',
    company_llm_provider: 'anthropic',
    ai_enrichment_run_concurrency: 8,
    anthropic: {
      model: null,
      base_url: null,
      has_api_key: false,
      api_key_preview: null,
    },
    company_anthropic: {
      has_api_key: true,
      api_key_preview: 'comp...9999',
      model: 'claude-sonnet-4-5',
      base_url: 'https://api.anthropic.com',
    },
    gemini: {
      model: 'gemini-2.5-flash',
      has_api_key: true,
      api_key_preview: 'gem-...3456',
    },
    company_gemini: {
      has_api_key: false,
      api_key_preview: null,
      model: null,
    },
    custom: {
      model: null,
      base_url: null,
      api_format: null,
      has_api_key: false,
      api_key_preview: null,
    },
    company_custom: {
      has_api_key: false,
      api_key_preview: null,
      model: null,
      base_url: null,
      api_format: null,
    },
    zhipu: {
      has_api_key: false,
      api_key_preview: null,
    },
    company_zhipu: {
      has_api_key: false,
      api_key_preview: null,
    },
  },
  effective_config: {
    llm_provider: 'gemini',
    company_llm_provider: 'anthropic',
    ai_enrichment_run_concurrency: 8,
    anthropic: {
      model: 'claude-sonnet-4-5',
      base_url: 'https://api.anthropic.com',
      has_api_key: false,
    },
    company_anthropic: {
      has_api_key: true,
      model: 'claude-sonnet-4-5',
      base_url: 'https://api.anthropic.com',
    },
    gemini: {
      model: 'gemini-2.5-flash',
      has_api_key: true,
    },
    company_gemini: {
      has_api_key: false,
      model: 'gemini-2.5-flash',
    },
    custom: {
      model: 'gpt-4.1-mini',
      base_url: 'https://api.example.com/v1',
      api_format: 'openai',
      has_api_key: false,
    },
    company_custom: {
      has_api_key: false,
      model: 'gpt-4.1-mini',
      base_url: 'https://api.example.com/v1',
      api_format: 'openai',
    },
    zhipu: {
      has_api_key: false,
    },
    company_zhipu: {
      has_api_key: false,
    },
  },
  runtime_status: {
    configured_provider: 'gemini',
    active_provider: 'gemini',
    provider: 'gemini',
    model: 'gemini-2.5-flash',
    is_degraded: false,
    degradation_reason: null,
  },
  company_runtime_status: {
    configured_provider: 'anthropic',
    active_provider: 'anthropic',
    provider: 'anthropic',
    model: 'claude-sonnet-4-5',
    is_degraded: false,
    degradation_reason: null,
  },
};

describe('AISettingsPage', () => {
  let currentSettingsPayload;
  let putSettingsResponse;

  beforeEach(() => {
    currentSettingsPayload = clonePayload(aiSettingsPayload);
    putSettingsResponse = vi.fn(async (_url, init) => {
      const nextPayload = clonePayload(currentSettingsPayload);
      const body = JSON.parse(init.body);

      nextPayload.persisted_config.llm_provider = body.llm_provider ?? nextPayload.persisted_config.llm_provider;
      nextPayload.persisted_config.ai_enrichment_run_concurrency =
        body.ai_enrichment_run_concurrency ?? nextPayload.persisted_config.ai_enrichment_run_concurrency;
      nextPayload.effective_config.llm_provider = body.llm_provider ?? nextPayload.effective_config.llm_provider;
      nextPayload.effective_config.ai_enrichment_run_concurrency =
        body.ai_enrichment_run_concurrency ?? nextPayload.effective_config.ai_enrichment_run_concurrency;
      nextPayload.runtime_status.configured_provider =
        body.llm_provider ?? nextPayload.runtime_status.configured_provider;
      nextPayload.runtime_status.active_provider = body.llm_provider ?? nextPayload.runtime_status.active_provider;
      nextPayload.runtime_status.provider = body.llm_provider ?? nextPayload.runtime_status.provider;

      if (body.gemini_model !== undefined) {
        nextPayload.persisted_config.gemini.model = body.gemini_model;
        nextPayload.effective_config.gemini.model = body.gemini_model;
        nextPayload.runtime_status.model = body.gemini_model;
      }

      currentSettingsPayload = nextPayload;
      return mockJsonResponse(nextPayload);
    });

    globalThis.fetch = vi.fn((input, init = {}) => {
      const url = String(input);
      const method = init.method || 'GET';

      if (url.includes('/api/v1/stats/overview')) {
        return mockJsonResponse({
          total_jobs: 400,
          enriched_jobs: 4,
          pending_enrichment: 396,
        });
      }

      if (url.includes('/api/v1/ai/overview')) {
        return mockJsonResponse({
          failed_items: 7,
          last_completed_run: null,
          running_runs: 0,
        });
      }

      if (url.includes('/api/v1/settings/ai')) {
        if (method === 'PUT') {
          return putSettingsResponse(url, init);
        }

        return mockJsonResponse(currentSettingsPayload);
      }

      return Promise.reject(new Error(`Unhandled fetch: ${url}`));
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('loads ai runtime settings on mount and renders the shell with masked provider details', async () => {
    render(<AISettingsPage />);

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith('/api/v1/settings/ai');
    });

    expect(await screen.findByRole('heading', { level: 1, name: /ai runtime/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: /ai enrichment throughput/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/ai enrichment provider/i)).toHaveDisplayValue(/gemini/i);
    expect(screen.getByLabelText(/companies provider/i)).toHaveDisplayValue(/anthropic/i);
    expect(screen.getByLabelText(/concurrency/i)).toHaveValue(8);
    expect(screen.getByText(/gem-\.{3}3456/i)).toBeInTheDocument();
    expect(screen.queryByText(/gem-secret-123456/i)).not.toBeInTheDocument();
    expect(screen.getByLabelText(/ai enrichment api key/i)).toHaveValue('');

    const providerGroup = screen.getByRole('group', { name: /ai enrichment gemini settings/i });
    expect(within(providerGroup).getByLabelText(/ai enrichment model/i)).toHaveValue('gemini-2.5-flash');
    expect(within(providerGroup).getByText(/api key saved/i)).toBeInTheDocument();
    expect(within(providerGroup).getByText(/saved only for the ai enrichment profile/i)).toBeInTheDocument();
    expect(screen.getByRole('group', { name: /companies anthropic settings/i })).toBeInTheDocument();
    expect(screen.getByText(/comp\.\.\.9999/i)).toBeInTheDocument();
    expect(screen.getAllByText(/configured provider/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/active provider/i).length).toBeGreaterThan(0);
  });

  it('adds the settings view to app navigation and opens the settings shell from the sidebar footer', async () => {
    const user = userEvent.setup();

    render(<App />);

    await user.click(screen.getByRole('button', { name: /^settings$/i }));

    expect(await screen.findByRole('heading', { level: 1, name: /ai runtime/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: /ai enrichment throughput/i })).toBeInTheDocument();
  });

  it('saves edited settings and refreshes the runtime summary from the PUT response', async () => {
    const user = userEvent.setup();
    putSettingsResponse.mockImplementationOnce(async (_url, init) => {
      const body = JSON.parse(init.body);

      expect(body).toEqual({
        llm_provider: 'gemini',
        company_llm_provider: 'anthropic',
        ai_enrichment_run_concurrency: 12,
        gemini_api_key: '',
        gemini_model: 'gemini-2.5-pro',
        company_anthropic_api_key: '',
        company_anthropic_model: 'claude-sonnet-4-5',
        company_anthropic_base_url: 'https://api.anthropic.com',
      });

      currentSettingsPayload = {
        persisted_config: {
          ...currentSettingsPayload.persisted_config,
          llm_provider: 'gemini',
          ai_enrichment_run_concurrency: 12,
          gemini: {
            model: 'gemini-2.5-pro',
            has_api_key: true,
            api_key_preview: 'gem-...3456',
          },
        },
        effective_config: {
          ...currentSettingsPayload.effective_config,
          llm_provider: 'gemini',
          ai_enrichment_run_concurrency: 12,
          gemini: {
            model: 'gemini-2.5-pro',
            has_api_key: true,
          },
        },
        runtime_status: {
          configured_provider: 'gemini',
          active_provider: 'gemini',
          provider: 'gemini',
          model: 'gemini-2.5-pro',
          is_degraded: false,
          degradation_reason: null,
        },
        company_runtime_status: currentSettingsPayload.company_runtime_status,
      };

      return mockJsonResponse(currentSettingsPayload);
    });

    render(<AISettingsPage />);

    await screen.findByRole('heading', { level: 1, name: /ai runtime/i });

    await user.clear(screen.getByLabelText(/concurrency/i));
    await user.type(screen.getByLabelText(/concurrency/i), '12');
    await user.clear(screen.getByLabelText(/ai enrichment model/i));
    await user.type(screen.getByLabelText(/ai enrichment model/i), 'gemini-2.5-pro');
    await user.click(screen.getByRole('button', { name: /save settings/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/ai runtime settings saved/i);
    expect(screen.getByLabelText(/concurrency/i)).toHaveValue(12);
    expect(screen.getByLabelText(/ai enrichment model/i)).toHaveValue('gemini-2.5-pro');
    expect(screen.getByText(/runtime ready/i)).toBeInTheDocument();
  });

  it('switches providers and submits only the selected provider fields', async () => {
    const user = userEvent.setup();
    putSettingsResponse.mockImplementationOnce(async (_url, init) => {
      const body = JSON.parse(init.body);

      expect(body).toEqual({
        llm_provider: 'anthropic',
        company_llm_provider: 'anthropic',
        ai_enrichment_run_concurrency: 9,
        anthropic_api_key: 'anthropic-secret-987654',
        anthropic_model: 'claude-sonnet-4-5',
        anthropic_base_url: 'https://api.anthropic.com/v1',
        company_anthropic_api_key: '',
        company_anthropic_model: 'claude-sonnet-4-5',
        company_anthropic_base_url: 'https://api.anthropic.com',
      });

      currentSettingsPayload = {
        persisted_config: {
          ...currentSettingsPayload.persisted_config,
          llm_provider: 'anthropic',
          ai_enrichment_run_concurrency: 9,
          anthropic: {
            model: 'claude-sonnet-4-5',
            base_url: 'https://api.anthropic.com/v1',
            has_api_key: true,
            api_key_preview: 'anth...7654',
          },
        },
        effective_config: {
          ...currentSettingsPayload.effective_config,
          llm_provider: 'anthropic',
          ai_enrichment_run_concurrency: 9,
          anthropic: {
            model: 'claude-sonnet-4-5',
            base_url: 'https://api.anthropic.com/v1',
            has_api_key: true,
          },
        },
        runtime_status: {
          configured_provider: 'anthropic',
          active_provider: 'anthropic',
          provider: 'anthropic',
          model: 'claude-sonnet-4-5',
          is_degraded: false,
          degradation_reason: null,
        },
        company_runtime_status: currentSettingsPayload.company_runtime_status,
      };

      return mockJsonResponse(currentSettingsPayload);
    });

    render(<AISettingsPage />);

    await screen.findByRole('heading', { level: 1, name: /ai runtime/i });

    await user.selectOptions(screen.getByLabelText(/ai enrichment provider/i), 'anthropic');
    expect(screen.getByRole('group', { name: /ai enrichment anthropic settings/i })).toBeInTheDocument();
    expect(screen.queryByRole('group', { name: /ai enrichment gemini settings/i })).not.toBeInTheDocument();

    await user.clear(screen.getByLabelText(/concurrency/i));
    await user.type(screen.getByLabelText(/concurrency/i), '9');
    await user.clear(screen.getByLabelText(/ai enrichment model/i));
    await user.type(screen.getByLabelText(/ai enrichment model/i), 'claude-sonnet-4-5');
    await user.clear(screen.getByLabelText(/ai enrichment base url/i));
    await user.type(screen.getByLabelText(/ai enrichment base url/i), 'https://api.anthropic.com/v1');
    await user.type(screen.getByLabelText(/ai enrichment api key/i), 'anthropic-secret-987654');
    await user.click(screen.getByRole('button', { name: /save settings/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/ai runtime settings saved/i);
    expect(screen.getByRole('group', { name: /ai enrichment anthropic settings/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/ai enrichment provider/i)).toHaveDisplayValue(/anthropic/i);
    expect(screen.getByLabelText(/ai enrichment model/i)).toHaveValue('claude-sonnet-4-5');
    expect(screen.getByLabelText(/ai enrichment base url/i)).toHaveValue('https://api.anthropic.com/v1');
    expect(screen.getByText(/runtime ready/i)).toBeInTheDocument();
  });

  it('preserves the existing stored secret when the secret input is left blank', async () => {
    const user = userEvent.setup();
    putSettingsResponse.mockImplementationOnce(async (_url, init) => {
      const body = JSON.parse(init.body);

      expect(body.gemini_api_key).toBe('');
      expect(body.gemini_model).toBe('gemini-2.5-flash-lite');

      currentSettingsPayload = {
        ...currentSettingsPayload,
        persisted_config: {
          ...currentSettingsPayload.persisted_config,
          gemini: {
            model: 'gemini-2.5-flash-lite',
            has_api_key: true,
            api_key_preview: 'gem-...3456',
          },
        },
        effective_config: {
          ...currentSettingsPayload.effective_config,
          gemini: {
            model: 'gemini-2.5-flash-lite',
            has_api_key: true,
          },
        },
        runtime_status: {
          ...currentSettingsPayload.runtime_status,
          model: 'gemini-2.5-flash-lite',
        },
      };

      return mockJsonResponse(currentSettingsPayload);
    });

    render(<AISettingsPage />);

    await screen.findByRole('heading', { level: 1, name: /ai runtime/i });

    expect(screen.getByLabelText(/ai enrichment api key/i)).toHaveValue('');
    await user.clear(screen.getByLabelText(/ai enrichment model/i));
    await user.type(screen.getByLabelText(/ai enrichment model/i), 'gemini-2.5-flash-lite');
    await user.click(screen.getByRole('button', { name: /save settings/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/ai runtime settings saved/i);
    const providerGroup = screen.getByRole('group', { name: /ai enrichment gemini settings/i });
    expect(within(providerGroup).getByText(/^api key saved$/i)).toBeInTheDocument();
    expect(screen.getByText(/gem-\.{3}3456/i)).toBeInTheDocument();
  });

  it('renders backend validation errors from a 422 response', async () => {
    const user = userEvent.setup();
    putSettingsResponse.mockImplementationOnce(async () =>
      mockJsonResponse(
        {
          detail: [
            {
              loc: ['body', 'ai_enrichment_run_concurrency'],
              msg: 'Input should be greater than or equal to 1',
            },
            {
              loc: ['body', 'gemini_model'],
              msg: 'Input should be a valid string',
            },
          ],
        },
        { ok: false, status: 422 },
      ),
    );

    render(<AISettingsPage />);

    await screen.findByRole('heading', { level: 1, name: /ai runtime/i });

    await user.clear(screen.getByLabelText(/concurrency/i));
    await user.type(screen.getByLabelText(/concurrency/i), '0');
    await user.click(screen.getByRole('button', { name: /save settings/i }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/ai_enrichment_run_concurrency: input should be greater than or equal to 1/i);
    expect(alert).toHaveTextContent(/gemini_model: input should be a valid string/i);
  });

  it('renders degraded runtime feedback from the save response', async () => {
    const user = userEvent.setup();
    putSettingsResponse.mockImplementationOnce(async () => {
      currentSettingsPayload = {
        ...currentSettingsPayload,
        runtime_status: {
          configured_provider: 'gemini',
          active_provider: 'mock',
          provider: 'mock',
          model: 'mock',
          is_degraded: true,
          degradation_reason: "Failed to initialize provider 'gemini'",
        },
      };

      return mockJsonResponse(currentSettingsPayload);
    });

    render(<AISettingsPage />);

    await screen.findByRole('heading', { level: 1, name: /ai runtime/i });
    await user.click(screen.getByRole('button', { name: /save settings/i }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/runtime is degraded/i);
    expect(alert).toHaveTextContent(/failed to initialize provider 'gemini'/i);
    expect(screen.getByText(/degraded runtime/i)).toBeInTheDocument();
  });

  it('lets jobs and companies use separate providers and submits both profiles in one save', async () => {
    const user = userEvent.setup();
    putSettingsResponse.mockImplementationOnce(async (_url, init) => {
      const body = JSON.parse(init.body);

      expect(body).toEqual({
        llm_provider: 'custom',
        company_llm_provider: 'anthropic',
        ai_enrichment_run_concurrency: 8,
        custom_api_key: 'deepseek-secret',
        custom_model: 'deepseek-v4-flash',
        custom_base_url: 'https://api.deepseek.com',
        custom_api_format: 'anthropic',
        company_anthropic_api_key: 'anthropic-secret-123456',
        company_anthropic_model: 'claude-sonnet-4-5',
        company_anthropic_base_url: 'https://api.anthropic.com/v1',
      });

      currentSettingsPayload = {
        ...currentSettingsPayload,
        persisted_config: {
          ...currentSettingsPayload.persisted_config,
          llm_provider: 'custom',
          company_llm_provider: 'anthropic',
          custom: {
            model: 'deepseek-v4-flash',
            base_url: 'https://api.deepseek.com',
            api_format: 'anthropic',
            has_api_key: true,
            api_key_preview: 'deep...cret',
          },
          company_anthropic: {
            has_api_key: true,
            api_key_preview: 'anth...3456',
            model: 'claude-sonnet-4-5',
            base_url: 'https://api.anthropic.com/v1',
          },
          anthropic: {
            ...currentSettingsPayload.persisted_config.anthropic,
            has_api_key: false,
            api_key_preview: null,
          },
        },
        effective_config: {
          ...currentSettingsPayload.effective_config,
          llm_provider: 'custom',
          company_llm_provider: 'anthropic',
          custom: {
            model: 'deepseek-v4-flash',
            base_url: 'https://api.deepseek.com',
            api_format: 'anthropic',
            has_api_key: true,
          },
          company_anthropic: {
            model: 'claude-sonnet-4-5',
            base_url: 'https://api.anthropic.com/v1',
          },
        },
        runtime_status: {
          configured_provider: 'custom',
          active_provider: 'custom',
          provider: 'custom',
          model: 'deepseek-v4-flash',
          is_degraded: false,
          degradation_reason: null,
        },
        company_runtime_status: {
          configured_provider: 'anthropic',
          active_provider: 'anthropic',
          provider: 'anthropic',
          model: 'claude-sonnet-4-5',
          is_degraded: false,
          degradation_reason: null,
        },
      };

      return mockJsonResponse(currentSettingsPayload);
    });

    render(<AISettingsPage />);

    await screen.findByRole('heading', { level: 1, name: /ai runtime/i });

    await user.selectOptions(screen.getByLabelText(/ai enrichment provider/i), 'custom');
    await user.clear(screen.getByLabelText(/ai enrichment model/i));
    await user.type(screen.getByLabelText(/ai enrichment model/i), 'deepseek-v4-flash');
    await user.clear(screen.getByLabelText(/ai enrichment base url/i));
    await user.type(screen.getByLabelText(/ai enrichment base url/i), 'https://api.deepseek.com');
    await user.clear(screen.getByLabelText(/ai enrichment api format/i));
    await user.type(screen.getByLabelText(/ai enrichment api format/i), 'anthropic');
    await user.type(screen.getByLabelText(/ai enrichment api key/i), 'deepseek-secret');

    await user.selectOptions(screen.getByLabelText(/companies provider/i), 'anthropic');
    await user.clear(screen.getByLabelText(/companies model/i));
    await user.type(screen.getByLabelText(/companies model/i), 'claude-sonnet-4-5');
    await user.clear(screen.getByLabelText(/companies base url/i));
    await user.type(screen.getByLabelText(/companies base url/i), 'https://api.anthropic.com/v1');
    await user.type(screen.getByLabelText(/companies api key/i), 'anthropic-secret-123456');

    await user.click(screen.getByRole('button', { name: /save settings/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/ai runtime settings saved/i);
    expect(screen.getByLabelText(/ai enrichment provider/i)).toHaveDisplayValue(/custom/i);
    expect(screen.getByLabelText(/companies provider/i)).toHaveDisplayValue(/anthropic/i);
  });
});
