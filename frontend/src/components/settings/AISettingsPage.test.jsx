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

function getProviderPicker(profileLabel) {
  return screen.getByRole('group', { name: new RegExp(`${profileLabel} provider`, 'i') });
}

function getProviderCard(profileLabel, providerLabel) {
  return within(getProviderPicker(profileLabel)).getByRole('button', {
    name: new RegExp(`^${providerLabel}\\b`, 'i'),
  });
}

function getProviderSettingsGroup(profileLabel, providerLabel) {
  return screen.getByRole('group', {
    name: new RegExp(`${profileLabel} ${providerLabel} settings`, 'i'),
  });
}

function getSecretInput(profileLabel, providerLabel) {
  return within(getProviderSettingsGroup(profileLabel, providerLabel))
    .getAllByLabelText(new RegExp(`${profileLabel} api key`, 'i'))
    .find((element) => element.tagName === 'INPUT');
}

function getSecretToggle(profileLabel, providerLabel) {
  return within(getProviderSettingsGroup(profileLabel, providerLabel)).getByRole('button', {
    name: /show|hide/i,
  });
}

function getApiFormatField(profileLabel, providerLabel = 'Custom') {
  return within(getProviderSettingsGroup(profileLabel, providerLabel)).getByLabelText(
    new RegExp(`${profileLabel} api format`, 'i'),
  );
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
    active_provider: null,
    provider: 'gemini',
    model: 'gemini-2.5-flash',
    is_degraded: true,
    degradation_reason: 'AI Enrichment profile must be tested before running',
    requires_test: true,
    is_ready: false,
    last_test_status: 'untested',
  },
  company_runtime_status: {
    configured_provider: 'anthropic',
    active_provider: null,
    provider: 'anthropic',
    model: 'claude-sonnet-4-5',
    is_degraded: true,
    degradation_reason: 'Companies profile must be tested before running',
    requires_test: true,
    is_ready: false,
    last_test_status: 'untested',
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
        if (url.includes('/api/v1/settings/ai/test')) {
          return mockJsonResponse({
            ok: true,
            scope: 'jobs',
            configured_provider: 'gemini',
            active_provider: 'gemini',
            model: 'gemini-2.5-flash',
            latency_ms: 111,
            config_fingerprint: 'jobs:test-fingerprint',
          });
        }

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
    expect(getProviderCard('AI Enrichment', 'Gemini')).toHaveAttribute('aria-pressed', 'true');
    expect(getProviderCard('Companies', 'Anthropic')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByLabelText(/concurrency/i)).toHaveValue(8);
    expect(screen.getByText(/gem-\.{3}3456/i)).toBeInTheDocument();
    expect(screen.queryByText(/gem-secret-123456/i)).not.toBeInTheDocument();
    expect(getSecretInput('AI Enrichment', 'Gemini')).toHaveValue('');

    const providerGroup = getProviderSettingsGroup('AI Enrichment', 'Gemini');
    expect(within(providerGroup).getByLabelText(/ai enrichment model/i)).toHaveValue('gemini-2.5-flash');
    expect(within(providerGroup).getAllByText(/^api key saved$/i).length).toBeGreaterThan(0);
    expect(within(providerGroup).getByText(/saved only for the ai enrichment profile/i)).toBeInTheDocument();
    expect(getProviderSettingsGroup('Companies', 'Anthropic')).toBeInTheDocument();
    expect(screen.getByText(/comp\.\.\.9999/i)).toBeInTheDocument();
    expect(screen.queryByText(/configured provider/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/degraded state/i)).not.toBeInTheDocument();
  });

  it('adds the settings view to app navigation and opens the settings shell from the sidebar footer', async () => {
    const user = userEvent.setup();

    render(<App />);

    await user.click(await screen.findByRole('button', { name: /^settings$/i }));

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith('/api/v1/settings/ai');
    });

    expect(await screen.findByRole('heading', { level: 1, name: /ai runtime/i })).toBeInTheDocument();
    expect(await screen.findByRole('heading', { level: 2, name: /ai enrichment throughput/i })).toBeInTheDocument();
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
    expect(screen.getAllByText(/^Needs test$/i).length).toBeGreaterThan(0);
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

    await user.click(getProviderCard('AI Enrichment', 'Anthropic'));
    expect(getProviderSettingsGroup('AI Enrichment', 'Anthropic')).toBeInTheDocument();
    expect(screen.queryByRole('group', { name: /ai enrichment gemini settings/i })).not.toBeInTheDocument();

    await user.clear(screen.getByLabelText(/concurrency/i));
    await user.type(screen.getByLabelText(/concurrency/i), '9');
    await user.clear(screen.getByLabelText(/ai enrichment model/i));
    await user.type(screen.getByLabelText(/ai enrichment model/i), 'claude-sonnet-4-5');
    await user.clear(screen.getByLabelText(/ai enrichment base url/i));
    await user.type(screen.getByLabelText(/ai enrichment base url/i), 'https://api.anthropic.com/v1');
    await user.type(getSecretInput('AI Enrichment', 'Anthropic'), 'anthropic-secret-987654');
    await user.click(screen.getByRole('button', { name: /save settings/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/ai runtime settings saved/i);
    expect(getProviderSettingsGroup('AI Enrichment', 'Anthropic')).toBeInTheDocument();
    expect(getProviderCard('AI Enrichment', 'Anthropic')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByLabelText(/ai enrichment model/i)).toHaveValue('claude-sonnet-4-5');
    expect(screen.getByLabelText(/ai enrichment base url/i)).toHaveValue('https://api.anthropic.com/v1');
    expect(screen.getAllByText(/^Needs test$/i).length).toBeGreaterThan(0);
  });

  it('tests the current draft profile before save and shows probe feedback', async () => {
    const user = userEvent.setup();
    const fetchSpy = globalThis.fetch;

    render(<AISettingsPage />);

    await screen.findByRole('heading', { level: 1, name: /ai runtime/i });

    await user.click(getProviderCard('AI Enrichment', 'Custom'));
    await user.clear(screen.getByLabelText(/ai enrichment model/i));
    await user.type(screen.getByLabelText(/ai enrichment model/i), 'gpt-5.2');
    await user.clear(screen.getByLabelText(/ai enrichment base url/i));
    await user.type(screen.getByLabelText(/ai enrichment base url/i), 'https://api.example.com/v1');
    await user.selectOptions(getApiFormatField('AI Enrichment'), 'openai_responses');
    await user.type(getSecretInput('AI Enrichment', 'Custom'), 'test-secret');

    await user.click(screen.getByRole('button', { name: /test ai enrichment configuration/i }));

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/settings/ai/test',
        expect.objectContaining({
          method: 'POST',
        }),
      );
    });

    expect(await screen.findByRole('alert')).toHaveTextContent(/configuration test passed/i);
    expect(screen.getByText(/111 ms/i)).toBeInTheDocument();
  });

  it('toggles api key visibility without exposing saved secrets by default', async () => {
    const user = userEvent.setup();

    render(<AISettingsPage />);

    await screen.findByRole('heading', { level: 1, name: /ai runtime/i });

    const apiKeyInput = getSecretInput('AI Enrichment', 'Gemini');
    expect(apiKeyInput).toHaveAttribute('type', 'password');

    await user.type(apiKeyInput, 'temporary-secret');
    await user.click(getSecretToggle('AI Enrichment', 'Gemini'));
    expect(apiKeyInput).toHaveAttribute('type', 'text');
    expect(apiKeyInput).toHaveValue('temporary-secret');
    expect(screen.queryByText(/temporary-secret/i)).not.toBeInTheDocument();

    await user.click(getSecretToggle('AI Enrichment', 'Gemini'));
    expect(apiKeyInput).toHaveAttribute('type', 'password');
  });

  it('limits custom api format to supported options and normalizes legacy values', async () => {
    const user = userEvent.setup();

    render(<AISettingsPage />);

    await screen.findByRole('heading', { level: 1, name: /ai runtime/i });

    await user.click(getProviderCard('AI Enrichment', 'Custom'));

    const apiFormatField = getApiFormatField('AI Enrichment');
    expect(apiFormatField.tagName).toBe('SELECT');
    expect(apiFormatField).toHaveValue('openai_responses');
    expect(within(apiFormatField).getByRole('option', { name: /anthropic/i })).toBeInTheDocument();
    expect(within(apiFormatField).getByRole('option', { name: /openai responses/i })).toBeInTheDocument();
    expect(within(apiFormatField).queryByRole('option', { name: /^openai$/i })).not.toBeInTheDocument();
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

    expect(getSecretInput('AI Enrichment', 'Gemini')).toHaveValue('');
    await user.clear(screen.getByLabelText(/ai enrichment model/i));
    await user.type(screen.getByLabelText(/ai enrichment model/i), 'gemini-2.5-flash-lite');
    await user.click(screen.getByRole('button', { name: /save settings/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/ai runtime settings saved/i);
    const providerGroup = getProviderSettingsGroup('AI Enrichment', 'Gemini');
    expect(within(providerGroup).getAllByText(/^api key saved$/i).length).toBeGreaterThan(0);
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
          active_provider: null,
          provider: 'gemini',
          model: 'gemini-2.5-flash',
          is_degraded: true,
          degradation_reason: "Failed to initialize provider 'gemini'",
          requires_test: true,
          is_ready: false,
          last_test_status: 'failed',
        },
      };

      return mockJsonResponse(currentSettingsPayload);
    });

    render(<AISettingsPage />);

    await screen.findByRole('heading', { level: 1, name: /ai runtime/i });
    await user.click(screen.getByRole('button', { name: /save settings/i }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/needs a successful configuration test before it can run/i);
    expect(alert).toHaveTextContent(/failed to initialize provider 'gemini'/i);
    expect(screen.getAllByText(/^Needs test$/i).length).toBeGreaterThan(0);
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

    await user.click(getProviderCard('AI Enrichment', 'Custom'));
    await user.clear(screen.getByLabelText(/ai enrichment model/i));
    await user.type(screen.getByLabelText(/ai enrichment model/i), 'deepseek-v4-flash');
    await user.clear(screen.getByLabelText(/ai enrichment base url/i));
    await user.type(screen.getByLabelText(/ai enrichment base url/i), 'https://api.deepseek.com');
    await user.selectOptions(getApiFormatField('AI Enrichment'), 'anthropic');
    await user.type(getSecretInput('AI Enrichment', 'Custom'), 'deepseek-secret');

    await user.click(getProviderCard('Companies', 'Anthropic'));
    await user.clear(screen.getByLabelText(/companies model/i));
    await user.type(screen.getByLabelText(/companies model/i), 'claude-sonnet-4-5');
    await user.clear(screen.getByLabelText(/companies base url/i));
    await user.type(screen.getByLabelText(/companies base url/i), 'https://api.anthropic.com/v1');
    await user.type(getSecretInput('Companies', 'Anthropic'), 'anthropic-secret-123456');

    await user.click(screen.getByRole('button', { name: /save settings/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/ai runtime settings saved/i);
    expect(getProviderCard('AI Enrichment', 'Custom')).toHaveAttribute('aria-pressed', 'true');
    expect(getProviderCard('Companies', 'Anthropic')).toHaveAttribute('aria-pressed', 'true');
  });
});
