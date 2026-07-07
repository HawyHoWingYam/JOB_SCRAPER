import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../charts/SkillChart", () => ({
  default: () => <div>Skill Chart Stub</div>,
}));

vi.mock("../charts/CategoryChart", () => ({
  default: () => <div>Category Chart Stub</div>,
}));

import App from "../../App";
import AISettingsPage from "./AISettingsPage";

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
function buildProvidersByKey(providers) {
  return Object.fromEntries(
    providers.map((provider) => [provider.key, provider]),
  );
}
function getProviderPicker(profileLabel) {
  return screen.getByRole("group", {
    name: new RegExp(`${profileLabel} provider`, "i"),
  });
}

function getProviderCard(profileLabel, providerLabel) {
  return within(getProviderPicker(profileLabel)).getByRole("button", {
    name: new RegExp(`^${providerLabel}\\b`, "i"),
  });
}

function getProviderSettingsGroup(profileLabel, providerLabel) {
  return screen.getByRole("group", {
    name: new RegExp(`${profileLabel} ${providerLabel} settings`, "i"),
  });
}

function getSecretInput(profileLabel, providerLabel) {
  return within(getProviderSettingsGroup(profileLabel, providerLabel))
    .getAllByLabelText(new RegExp(`${profileLabel} api key`, "i"))
    .find((element) => element.tagName === "INPUT");
}

function getSecretToggle(profileLabel, providerLabel) {
  return within(
    getProviderSettingsGroup(profileLabel, providerLabel),
  ).getByRole("button", {
    name: /show|hide/i,
  });
}

function getApiFormatField(profileLabel, providerLabel = "Custom") {
  return within(
    getProviderSettingsGroup(profileLabel, providerLabel),
  ).getByLabelText(new RegExp(`${profileLabel} api format`, "i"));
}

const defaultProviderCatalogProviders = [
  {
    key: "anthropic",
    label: "Anthropic",
    description: "Claude-compatible runtime",
    fields: [
      { key: "model", label: "Model", request_key: "anthropic_model" },
      { key: "base_url", label: "Base URL", request_key: "anthropic_base_url" },
    ],
    secret_request_key: "anthropic_api_key",
  },
  {
    key: "gemini",
    label: "Gemini",
    description: "Fast general-purpose model",
    fields: [{ key: "model", label: "Model", request_key: "gemini_model" }],
    secret_request_key: "gemini_api_key",
  },
  {
    key: "custom",
    label: "Custom",
    description: "Custom OpenAI or Anthropic endpoint",
    fields: [
      { key: "model", label: "Model", request_key: "custom_model" },
      { key: "base_url", label: "Base URL", request_key: "custom_base_url" },
      {
        key: "api_format",
        label: "API Format",
        request_key: "custom_api_format",
      },
    ],
    secret_request_key: "custom_api_key",
  },
  {
    key: "zhipu",
    label: "Zhipu",
    description: "Credential-only setup",
    fields: [],
    secret_request_key: "zhipu_api_key",
  },
  {
    key: "mock",
    label: "Mock",
    description: "Built-in fallback for testing",
    fields: [],
    secret_request_key: null,
  },
];
const defaultProviderCatalog = {
  providers: defaultProviderCatalogProviders,
  providers_by_key: buildProvidersByKey(defaultProviderCatalogProviders),
  custom_api_format_options: [
    { value: "anthropic", label: "Anthropic" },
    { value: "openai_responses", label: "OpenAI Responses" },
  ],
};
const aiSettingsPayload = {
  provider_catalog: defaultProviderCatalog,
  persisted_config: {
    llm_provider: "gemini",
    company_llm_provider: "anthropic",
    ai_enrichment_run_concurrency: 8,
    company_ai_enrichment_run_concurrency: 3,
    anthropic: {
      model: null,
      base_url: null,
      has_api_key: false,
      api_key_preview: null,
    },
    company_anthropic: {
      has_api_key: true,
      api_key_preview: "comp...9999",
      model: "claude-sonnet-4-5",
      base_url: "https://api.anthropic.com",
    },
    gemini: {
      model: "gemini-2.5-flash",
      has_api_key: true,
      api_key_preview: "gem-...3456",
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
    llm_provider: "gemini",
    company_llm_provider: "anthropic",
    ai_enrichment_run_concurrency: 8,
    company_ai_enrichment_run_concurrency: 3,
    anthropic: {
      model: "claude-sonnet-4-5",
      base_url: "https://api.anthropic.com",
      has_api_key: false,
    },
    company_anthropic: {
      has_api_key: true,
      model: "claude-sonnet-4-5",
      base_url: "https://api.anthropic.com",
    },
    gemini: {
      model: "gemini-2.5-flash",
      has_api_key: true,
    },
    company_gemini: {
      has_api_key: false,
      model: "gemini-2.5-flash",
    },
    custom: {
      model: "gpt-4.1-mini",
      base_url: "https://api.example.com/v1",
      api_format: "openai",
      has_api_key: false,
    },
    company_custom: {
      has_api_key: false,
      model: "gpt-4.1-mini",
      base_url: "https://api.example.com/v1",
      api_format: "openai",
    },
    zhipu: {
      has_api_key: false,
    },
    company_zhipu: {
      has_api_key: false,
    },
  },
  runtime_status: {
    configured_provider: "gemini",
    active_provider: null,
    provider: "gemini",
    model: "gemini-2.5-flash",
    is_degraded: true,
    degradation_reason: "AI Enrichment profile must be tested before running",
    requires_test: true,
    is_ready: false,
    last_test_status: "untested",
  },
  company_runtime_status: {
    configured_provider: "anthropic",
    active_provider: null,
    provider: "anthropic",
    model: "claude-sonnet-4-5",
    is_degraded: true,
    degradation_reason: "Companies profile must be tested before running",
    requires_test: true,
    is_ready: false,
    last_test_status: "untested",
  },
};

describe("AISettingsPage", () => {
  let currentSettingsPayload;
  let putSettingsResponse;
  let testProfileResponse;

  beforeEach(() => {
    currentSettingsPayload = clonePayload(aiSettingsPayload);
    putSettingsResponse = vi.fn(async (_url, init) => {
      const nextPayload = clonePayload(currentSettingsPayload);
      const body = JSON.parse(init.body);

      nextPayload.persisted_config.llm_provider =
        body.llm_provider ?? nextPayload.persisted_config.llm_provider;
      nextPayload.persisted_config.ai_enrichment_run_concurrency =
        body.ai_enrichment_run_concurrency ??
        nextPayload.persisted_config.ai_enrichment_run_concurrency;
      nextPayload.persisted_config.company_ai_enrichment_run_concurrency =
        body.company_ai_enrichment_run_concurrency ??
        nextPayload.persisted_config.company_ai_enrichment_run_concurrency;
      nextPayload.effective_config.llm_provider =
        body.llm_provider ?? nextPayload.effective_config.llm_provider;
      nextPayload.effective_config.ai_enrichment_run_concurrency =
        body.ai_enrichment_run_concurrency ??
        nextPayload.effective_config.ai_enrichment_run_concurrency;
      nextPayload.effective_config.company_ai_enrichment_run_concurrency =
        body.company_ai_enrichment_run_concurrency ??
        nextPayload.effective_config.company_ai_enrichment_run_concurrency;
      nextPayload.runtime_status.configured_provider =
        body.llm_provider ?? nextPayload.runtime_status.configured_provider;
      nextPayload.runtime_status.active_provider =
        body.llm_provider ?? nextPayload.runtime_status.active_provider;
      nextPayload.runtime_status.provider =
        body.llm_provider ?? nextPayload.runtime_status.provider;

      if (body.gemini_model !== undefined) {
        nextPayload.persisted_config.gemini.model = body.gemini_model;
        nextPayload.effective_config.gemini.model = body.gemini_model;
        nextPayload.runtime_status.model = body.gemini_model;
      }

      currentSettingsPayload = nextPayload;
      return mockJsonResponse(nextPayload);
    });
    testProfileResponse = vi.fn(async () =>
      mockJsonResponse({
        ok: true,
        scope: "jobs",
        configured_provider: "gemini",
        active_provider: "gemini",
        model: "gemini-2.5-flash",
        latency_ms: 111,
        config_fingerprint: "jobs:test-fingerprint",
      }),
    );

    globalThis.fetch = vi.fn((input, init = {}) => {
      const url = String(input);
      const method = init.method || "GET";

      if (url.includes("/api/v1/stats/overview")) {
        return mockJsonResponse({
          total_jobs: 400,
          enriched_jobs: 4,
          pending_enrichment: 396,
        });
      }

      if (url.includes("/api/v1/ai/overview")) {
        return mockJsonResponse({
          failed_items: 7,
          last_completed_run: null,
          running_runs: 0,
        });
      }

      if (url.includes("/api/v1/settings/ai")) {
        if (url.includes("/api/v1/settings/ai/test")) {
          return testProfileResponse(url, init);
        }

        if (method === "PUT") {
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

  it("loads ai runtime settings on mount and renders the shell with masked provider details", async () => {
    render(<AISettingsPage />);

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith("/api/v1/settings/ai");
    });

    expect(
      await screen.findByRole("heading", { level: 1, name: /ai runtime/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        level: 2,
        name: /ai enrichment throughput/i,
      }),
    ).toBeInTheDocument();
    expect(getProviderCard("AI Enrichment", "Gemini")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(getProviderCard("Companies", "Anthropic")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByLabelText(/ai enrichment concurrency/i)).toHaveValue(8);
    expect(screen.getByLabelText(/companies concurrency/i)).toHaveValue(3);
    expect(screen.getByText(/gem-\.{3}3456/i)).toBeInTheDocument();
    expect(screen.queryByText(/gem-secret-123456/i)).not.toBeInTheDocument();
    expect(getSecretInput("AI Enrichment", "Gemini")).toHaveValue("");

    const providerGroup = getProviderSettingsGroup("AI Enrichment", "Gemini");
    expect(
      within(providerGroup).getByLabelText(/ai enrichment model/i),
    ).toHaveValue("gemini-2.5-flash");
    expect(
      within(providerGroup).getAllByText(/^api key saved$/i).length,
    ).toBeGreaterThan(0);
    expect(
      within(providerGroup).getByText(
        /saved only for the ai enrichment profile/i,
      ),
    ).toBeInTheDocument();
    expect(
      getProviderSettingsGroup("Companies", "Anthropic"),
    ).toBeInTheDocument();
    expect(screen.getByText(/comp\.\.\.9999/i)).toBeInTheDocument();
    expect(screen.queryByText(/configured provider/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/degraded state/i)).not.toBeInTheDocument();
  });

  it("renders provider cards, field labels, and custom api format options from the provider catalog payload", async () => {
    const user = userEvent.setup();
    const catalogProviders = [
      {
        key: "anthropic",
        label: "Anthropic Live",
        description: "Anthropic production runtime",
        fields: [
          { key: "model", label: "Model ID", request_key: "anthropic_model" },
          {
            key: "base_url",
            label: "Endpoint URL",
            request_key: "anthropic_base_url",
          },
        ],
        secret_request_key: "anthropic_api_key",
      },
      {
        key: "custom",
        label: "Custom Live",
        description: "Custom endpoint runtime",
        fields: [
          { key: "model", label: "Model ID", request_key: "custom_model" },
          {
            key: "base_url",
            label: "Endpoint URL",
            request_key: "custom_base_url",
          },
          {
            key: "api_format",
            label: "Runtime API Format",
            request_key: "custom_api_format",
          },
        ],
        secret_request_key: "custom_api_key",
      },
      {
        key: "mock",
        label: "Mock Live",
        description: "Built-in fallback",
        fields: [],
        secret_request_key: null,
      },
    ];
    const basePayload = clonePayload(aiSettingsPayload);
    currentSettingsPayload = {
      ...basePayload,
      provider_catalog: {
        providers: catalogProviders,
        providers_by_key: {},
        custom_api_format_options: [
          { value: "anthropic", label: "Anthropic" },
          { value: "openai_responses", label: "OpenAI Responses" },
        ],
      },
      persisted_config: {
        ...basePayload.persisted_config,
        llm_provider: "anthropic",
        company_llm_provider: "mock",
        anthropic: {
          model: "claude-sonnet-4-5",
          base_url: "https://api.anthropic.com",
          has_api_key: false,
          api_key_preview: null,
        },
      },
      effective_config: {
        ...basePayload.effective_config,
        llm_provider: "anthropic",
        company_llm_provider: "mock",
        anthropic: {
          model: "claude-sonnet-4-5",
          base_url: "https://api.anthropic.com",
          has_api_key: false,
        },
      },
      runtime_status: {
        ...basePayload.runtime_status,
        configured_provider: "anthropic",
        provider: "anthropic",
        model: "claude-sonnet-4-5",
      },
      company_runtime_status: {
        ...basePayload.company_runtime_status,
        configured_provider: "mock",
        provider: "mock",
        model: null,
      },
    };
    render(<AISettingsPage />);
    await screen.findByRole("heading", { level: 1, name: /ai runtime/i });
    const providerPicker = getProviderPicker("AI Enrichment");
    expect(
      within(providerPicker).getByRole("button", {
        name: /^Anthropic Live\b/i,
      }),
    ).toBeInTheDocument();
    expect(
      within(providerPicker).getByRole("button", { name: /^Custom Live\b/i }),
    ).toBeInTheDocument();
    expect(
      within(providerPicker).getByRole("button", { name: /^Mock Live\b/i }),
    ).toBeInTheDocument();
    expect(
      within(providerPicker).queryByRole("button", { name: /^Gemini\b/i }),
    ).not.toBeInTheDocument();
    const anthropicGroup = getProviderSettingsGroup(
      "AI Enrichment",
      "Anthropic Live",
    );
    expect(
      within(anthropicGroup).getByText(/anthropic production runtime/i),
    ).toBeInTheDocument();
    expect(
      within(anthropicGroup).getByLabelText(/ai enrichment model id/i),
    ).toHaveValue("claude-sonnet-4-5");
    expect(
      within(anthropicGroup).getByLabelText(/ai enrichment endpoint url/i),
    ).toHaveValue("https://api.anthropic.com");
    expect(
      within(anthropicGroup).queryByLabelText(/ai enrichment base url/i),
    ).not.toBeInTheDocument();
    await user.click(getProviderCard("AI Enrichment", "Custom Live"));
    const apiFormatField = within(
      getProviderSettingsGroup("AI Enrichment", "Custom Live"),
    ).getByLabelText(/ai enrichment runtime api format/i);
    expect(
      within(apiFormatField).getByRole("option", { name: /anthropic/i }),
    ).toBeInTheDocument();
    expect(
      within(apiFormatField).getByRole("option", { name: /openai responses/i }),
    ).toBeInTheDocument();
    expect(
      within(apiFormatField).queryByRole("option", { name: /^openai$/i }),
    ).not.toBeInTheDocument();
    expect(getSecretInput("AI Enrichment", "Custom Live")).toBeInstanceOf(
      HTMLInputElement,
    );
  });

  it("uses provider catalog providers metadata for save and test payloads when providers_by_key is stale", async () => {
    const user = userEvent.setup();
    const catalogProviders = [
      {
        key: "anthropic",
        label: "Anthropic Live",
        description: "Anthropic production runtime",
        fields: [
          { key: "model", label: "Model", request_key: "anthropic_model" },
          {
            key: "base_url",
            label: "Base URL",
            request_key: "anthropic_base_url",
          },
        ],
        secret_request_key: "anthropic_api_key",
      },
      {
        key: "custom",
        label: "Custom Live",
        description: "Custom endpoint runtime",
        fields: [
          { key: "model", label: "Model", request_key: "custom_model" },
          {
            key: "base_url",
            label: "Base URL",
            request_key: "custom_base_url",
          },
          {
            key: "api_format",
            label: "API Format",
            request_key: "custom_api_format",
          },
        ],
        secret_request_key: "custom_api_key",
      },
      {
        key: "mock",
        label: "Mock Live",
        description: "Built-in fallback",
        fields: [],
        secret_request_key: null,
      },
    ];
    const basePayload = clonePayload(aiSettingsPayload);

    currentSettingsPayload = {
      ...basePayload,
      provider_catalog: {
        providers: catalogProviders,
        providers_by_key: {
          custom: {
            key: "custom",
            label: "Custom Stale",
            description: "Stale keyed metadata",
            fields: [
              {
                key: "model",
                label: "Wrong Model",
                request_key: "anthropic_model",
              },
              {
                key: "base_url",
                label: "Wrong Base URL",
                request_key: "anthropic_base_url",
              },
              {
                key: "api_format",
                label: "Wrong API Format",
                request_key: "gemini_model",
              },
            ],
            secret_request_key: "anthropic_api_key",
          },
        },
        custom_api_format_options: [
          { value: "anthropic", label: "Anthropic" },
          { value: "openai_responses", label: "OpenAI Responses" },
        ],
      },
      persisted_config: {
        ...basePayload.persisted_config,
        llm_provider: "custom",
        custom: {
          model: "gpt-4.1-mini",
          base_url: "https://api.example.com/v1",
          api_format: "openai",
          has_api_key: false,
          api_key_preview: null,
        },
      },
      effective_config: {
        ...basePayload.effective_config,
        llm_provider: "custom",
        custom: {
          model: "gpt-4.1-mini",
          base_url: "https://api.example.com/v1",
          api_format: "openai",
          has_api_key: false,
        },
      },
      runtime_status: {
        ...basePayload.runtime_status,
        configured_provider: "custom",
        provider: "custom",
        model: "gpt-4.1-mini",
      },
    };

    testProfileResponse.mockImplementationOnce(async (_url, init) => {
      const body = JSON.parse(init.body);

      expect(body).toEqual({
        scope: "jobs",
        profile: {
          llm_provider: "custom",
          custom_api_key: "",
          custom_model: "gpt-4.1-mini",
          custom_base_url: "https://api.example.com/v1",
          custom_api_format: "openai_responses",
        },
      });
      expect(body.profile).not.toHaveProperty("anthropic_api_key");
      expect(body.profile).not.toHaveProperty("anthropic_model");
      expect(body.profile).not.toHaveProperty("anthropic_base_url");
      expect(body.profile).not.toHaveProperty("gemini_model");

      return mockJsonResponse({
        ok: true,
        scope: "jobs",
        configured_provider: "custom",
        active_provider: "custom",
        model: "gpt-4.1-mini",
        latency_ms: 111,
        config_fingerprint: "jobs:test-fingerprint",
      });
    });

    putSettingsResponse.mockImplementationOnce(async (_url, init) => {
      const body = JSON.parse(init.body);

      expect(body).toEqual({
        llm_provider: "custom",
        company_llm_provider: "anthropic",
        ai_enrichment_run_concurrency: 8,
        company_ai_enrichment_run_concurrency: 3,
        custom_api_key: "",
        custom_model: "gpt-4.1-mini",
        custom_base_url: "https://api.example.com/v1",
        custom_api_format: "openai_responses",
        company_anthropic_api_key: "",
        company_anthropic_model: "claude-sonnet-4-5",
        company_anthropic_base_url: "https://api.anthropic.com",
      });
      expect(body).not.toHaveProperty("anthropic_api_key");
      expect(body).not.toHaveProperty("anthropic_model");
      expect(body).not.toHaveProperty("anthropic_base_url");
      expect(body).not.toHaveProperty("gemini_model");

      currentSettingsPayload = {
        ...currentSettingsPayload,
        runtime_status: {
          ...currentSettingsPayload.runtime_status,
          configured_provider: "custom",
          active_provider: "custom",
          provider: "custom",
          model: "gpt-4.1-mini",
        },
      };

      return mockJsonResponse(currentSettingsPayload);
    });

    render(<AISettingsPage />);

    await screen.findByRole("heading", { level: 1, name: /ai runtime/i });

    expect(getProviderCard("AI Enrichment", "Custom Live")).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    await user.click(
      screen.getByRole("button", { name: /test ai enrichment configuration/i }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /configuration test passed/i,
    );

    await user.click(screen.getByRole("button", { name: /save settings/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /ai runtime settings saved/i,
    );
  }, 10000);

  it("adds the settings view to app navigation and opens the settings shell from the sidebar footer", async () => {
    const user = userEvent.setup();

    render(<App />);

    await user.click(
      await screen.findByRole("button", { name: /^settings$/i }),
    );

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith("/api/v1/settings/ai");
    });

    expect(
      await screen.findByRole("heading", { level: 1, name: /ai runtime/i }),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("heading", {
        level: 2,
        name: /ai enrichment throughput/i,
      }),
    ).toBeInTheDocument();
  });

  it("saves edited settings and refreshes the runtime summary from the PUT response", async () => {
    const user = userEvent.setup();
    putSettingsResponse.mockImplementationOnce(async (_url, init) => {
      const body = JSON.parse(init.body);

      expect(body).toEqual({
        llm_provider: "gemini",
        company_llm_provider: "anthropic",
        ai_enrichment_run_concurrency: 12,
        company_ai_enrichment_run_concurrency: 4,
        gemini_api_key: "",
        gemini_model: "gemini-2.5-pro",
        company_anthropic_api_key: "",
        company_anthropic_model: "claude-sonnet-4-5",
        company_anthropic_base_url: "https://api.anthropic.com",
      });

      currentSettingsPayload = {
        ...currentSettingsPayload,
        persisted_config: {
          ...currentSettingsPayload.persisted_config,
          llm_provider: "gemini",
          ai_enrichment_run_concurrency: 12,
          company_ai_enrichment_run_concurrency: 4,
          gemini: {
            model: "gemini-2.5-pro",
            has_api_key: true,
            api_key_preview: "gem-...3456",
          },
        },
        effective_config: {
          ...currentSettingsPayload.effective_config,
          llm_provider: "gemini",
          ai_enrichment_run_concurrency: 12,
          company_ai_enrichment_run_concurrency: 4,
          gemini: {
            model: "gemini-2.5-pro",
            has_api_key: true,
          },
        },
        runtime_status: {
          configured_provider: "gemini",
          active_provider: "gemini",
          provider: "gemini",
          model: "gemini-2.5-pro",
          is_degraded: false,
          degradation_reason: null,
        },
        company_runtime_status: currentSettingsPayload.company_runtime_status,
      };

      return mockJsonResponse(currentSettingsPayload);
    });

    render(<AISettingsPage />);

    await screen.findByRole("heading", { level: 1, name: /ai runtime/i });

    await user.clear(screen.getByLabelText(/ai enrichment concurrency/i));
    await user.type(screen.getByLabelText(/ai enrichment concurrency/i), "12");
    await user.clear(screen.getByLabelText(/companies concurrency/i));
    await user.type(screen.getByLabelText(/companies concurrency/i), "4");
    await user.clear(screen.getByLabelText(/ai enrichment model/i));
    await user.type(
      screen.getByLabelText(/ai enrichment model/i),
      "gemini-2.5-pro",
    );
    await user.click(screen.getByRole("button", { name: /save settings/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /ai runtime settings saved/i,
    );
    expect(screen.getByLabelText(/ai enrichment concurrency/i)).toHaveValue(12);
    expect(screen.getByLabelText(/companies concurrency/i)).toHaveValue(4);
    expect(screen.getByLabelText(/ai enrichment model/i)).toHaveValue(
      "gemini-2.5-pro",
    );
    expect(screen.getAllByText(/^Needs test$/i).length).toBeGreaterThan(0);
  });

  it("switches providers and submits only the selected provider fields", async () => {
    const user = userEvent.setup();
    putSettingsResponse.mockImplementationOnce(async (_url, init) => {
      const body = JSON.parse(init.body);

      expect(body).toEqual({
        llm_provider: "anthropic",
        company_llm_provider: "anthropic",
        ai_enrichment_run_concurrency: 9,
        company_ai_enrichment_run_concurrency: 3,
        anthropic_api_key: "anthropic-secret-987654",
        anthropic_model: "claude-sonnet-4-5",
        anthropic_base_url: "https://api.anthropic.com/v1",
        company_anthropic_api_key: "",
        company_anthropic_model: "claude-sonnet-4-5",
        company_anthropic_base_url: "https://api.anthropic.com",
      });

      currentSettingsPayload = {
        ...currentSettingsPayload,
        persisted_config: {
          ...currentSettingsPayload.persisted_config,
          llm_provider: "anthropic",
          ai_enrichment_run_concurrency: 9,
          company_ai_enrichment_run_concurrency: 3,
          anthropic: {
            model: "claude-sonnet-4-5",
            base_url: "https://api.anthropic.com/v1",
            has_api_key: true,
            api_key_preview: "anth...7654",
          },
        },
        effective_config: {
          ...currentSettingsPayload.effective_config,
          llm_provider: "anthropic",
          ai_enrichment_run_concurrency: 9,
          company_ai_enrichment_run_concurrency: 3,
          anthropic: {
            model: "claude-sonnet-4-5",
            base_url: "https://api.anthropic.com/v1",
            has_api_key: true,
          },
        },
        runtime_status: {
          configured_provider: "anthropic",
          active_provider: "anthropic",
          provider: "anthropic",
          model: "claude-sonnet-4-5",
          is_degraded: false,
          degradation_reason: null,
        },
        company_runtime_status: currentSettingsPayload.company_runtime_status,
      };

      return mockJsonResponse(currentSettingsPayload);
    });

    render(<AISettingsPage />);

    await screen.findByRole("heading", { level: 1, name: /ai runtime/i });

    await user.click(getProviderCard("AI Enrichment", "Anthropic"));
    expect(
      getProviderSettingsGroup("AI Enrichment", "Anthropic"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("group", { name: /ai enrichment gemini settings/i }),
    ).not.toBeInTheDocument();

    await user.clear(screen.getByLabelText(/ai enrichment concurrency/i));
    await user.type(screen.getByLabelText(/ai enrichment concurrency/i), "9");
    await user.clear(screen.getByLabelText(/ai enrichment model/i));
    await user.type(
      screen.getByLabelText(/ai enrichment model/i),
      "claude-sonnet-4-5",
    );
    await user.clear(screen.getByLabelText(/ai enrichment base url/i));
    await user.type(
      screen.getByLabelText(/ai enrichment base url/i),
      "https://api.anthropic.com/v1",
    );
    await user.type(
      getSecretInput("AI Enrichment", "Anthropic"),
      "anthropic-secret-987654",
    );
    await user.click(screen.getByRole("button", { name: /save settings/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /ai runtime settings saved/i,
    );
    expect(
      getProviderSettingsGroup("AI Enrichment", "Anthropic"),
    ).toBeInTheDocument();
    expect(getProviderCard("AI Enrichment", "Anthropic")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByLabelText(/ai enrichment model/i)).toHaveValue(
      "claude-sonnet-4-5",
    );
    expect(screen.getByLabelText(/ai enrichment base url/i)).toHaveValue(
      "https://api.anthropic.com/v1",
    );
    expect(screen.getAllByText(/^Needs test$/i).length).toBeGreaterThan(0);
  }, 10000);

  it("shows unconfigured runtime summary cards as not configured instead of leaking the mock picker default", async () => {
    currentSettingsPayload = {
      ...currentSettingsPayload,
      persisted_config: {
        ...currentSettingsPayload.persisted_config,
        llm_provider: null,
        company_llm_provider: null,
      },
      effective_config: {
        ...currentSettingsPayload.effective_config,
        llm_provider: null,
        company_llm_provider: null,
      },
      runtime_status: {
        configured_provider: null,
        active_provider: null,
        provider: null,
        model: null,
        is_degraded: true,
        degradation_reason: "Profile is not configured",
        requires_test: false,
        is_ready: false,
        last_test_status: "untested",
      },
      company_runtime_status: {
        configured_provider: null,
        active_provider: null,
        provider: null,
        model: null,
        is_degraded: true,
        degradation_reason: "Profile is not configured",
        requires_test: false,
        is_ready: false,
        last_test_status: "untested",
      },
    };

    render(<AISettingsPage />);

    await screen.findByRole("heading", { level: 1, name: /ai runtime/i });

    const enrichmentCard = screen.getByText("AI Enrichment").closest("article");
    const companiesCard = screen.getByText("Companies").closest("article");

    expect(enrichmentCard).not.toBeNull();
    expect(companiesCard).not.toBeNull();
    expect(
      within(enrichmentCard).getByText("Not configured"),
    ).toBeInTheDocument();
    expect(
      within(companiesCard).getByText("Not configured"),
    ).toBeInTheDocument();
    expect(
      within(enrichmentCard).queryByText(/^Mock$/i),
    ).not.toBeInTheDocument();
    expect(
      within(companiesCard).queryByText(/^Mock$/i),
    ).not.toBeInTheDocument();
    expect(screen.getAllByText(/^Blocked$/i).length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText(/^Needs test$/i)).not.toBeInTheDocument();
  });

  it("tests the current draft profile before save and shows probe feedback", async () => {
    const user = userEvent.setup();
    const fetchSpy = globalThis.fetch;

    render(<AISettingsPage />);

    await screen.findByRole("heading", { level: 1, name: /ai runtime/i });

    await user.click(getProviderCard("AI Enrichment", "Custom"));
    await user.clear(screen.getByLabelText(/ai enrichment model/i));
    await user.type(screen.getByLabelText(/ai enrichment model/i), "gpt-5.2");
    await user.clear(screen.getByLabelText(/ai enrichment base url/i));
    await user.type(
      screen.getByLabelText(/ai enrichment base url/i),
      "https://api.example.com/v1",
    );
    await user.selectOptions(
      getApiFormatField("AI Enrichment"),
      "openai_responses",
    );
    await user.type(getSecretInput("AI Enrichment", "Custom"), "test-secret");

    await user.click(
      screen.getByRole("button", { name: /test ai enrichment configuration/i }),
    );

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/v1/settings/ai/test",
        expect.objectContaining({
          method: "POST",
        }),
      );
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /configuration test passed/i,
    );
    expect(screen.getByText(/111 ms/i)).toBeInTheDocument();
  });

  it("shows a companies web search warning when the model passes but web search is unsupported", async () => {
    const user = userEvent.setup();
    testProfileResponse.mockImplementation(async (_url, init) => {
      const body = JSON.parse(init.body);
      if (body.scope === "companies") {
        return mockJsonResponse({
          ok: true,
          scope: "companies",
          configured_provider: "anthropic",
          active_provider: "anthropic",
          model: "claude-sonnet-4-5",
          latency_ms: 97,
          config_fingerprint: "companies:test-fingerprint",
          model_check: {
            ok: true,
            latency_ms: 97,
          },
          web_search_check: {
            attempted: false,
            supported: false,
            ok: false,
            latency_ms: null,
            error_message: "This provider does not support web search.",
          },
        });
      }

      return mockJsonResponse({
        ok: true,
        scope: "jobs",
        configured_provider: "gemini",
        active_provider: "gemini",
        model: "gemini-2.5-flash",
        latency_ms: 111,
        config_fingerprint: "jobs:test-fingerprint",
      });
    });

    render(<AISettingsPage />);

    await screen.findByRole("heading", { level: 1, name: /ai runtime/i });

    await user.click(
      screen.getByRole("button", { name: /test companies configuration/i }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /configuration test passed/i,
    );
    expect(screen.getByText(/model check passed/i)).toBeInTheDocument();
    expect(
      screen.getByText(
        /web search unavailable: this provider does not support web search\./i,
      ),
    ).toBeInTheDocument();
  });

  it("shows a companies web search success detail when the probe passes", async () => {
    const user = userEvent.setup();
    testProfileResponse.mockImplementation(async (_url, init) => {
      const body = JSON.parse(init.body);
      if (body.scope === "companies") {
        return mockJsonResponse({
          ok: true,
          scope: "companies",
          configured_provider: "custom",
          active_provider: "custom",
          model: "gpt-5.2",
          latency_ms: 88,
          config_fingerprint: "companies:test-fingerprint",
          model_check: {
            ok: true,
            latency_ms: 88,
          },
          web_search_check: {
            attempted: true,
            supported: true,
            ok: true,
            latency_ms: 54,
            error_message: null,
          },
        });
      }

      return mockJsonResponse({
        ok: true,
        scope: "jobs",
        configured_provider: "gemini",
        active_provider: "gemini",
        model: "gemini-2.5-flash",
        latency_ms: 111,
        config_fingerprint: "jobs:test-fingerprint",
      });
    });

    render(<AISettingsPage />);

    await screen.findByRole("heading", { level: 1, name: /ai runtime/i });

    await user.click(
      screen.getByRole("button", { name: /test companies configuration/i }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /configuration test passed/i,
    );
    expect(screen.getByText(/model check passed/i)).toBeInTheDocument();
    expect(
      screen.getByText(/web search check passed \(\s*54 ms\s*\)/i),
    ).toBeInTheDocument();
  });

  it("toggles api key visibility without exposing saved secrets by default", async () => {
    const user = userEvent.setup();

    render(<AISettingsPage />);

    await screen.findByRole("heading", { level: 1, name: /ai runtime/i });

    const apiKeyInput = getSecretInput("AI Enrichment", "Gemini");
    expect(apiKeyInput).toHaveAttribute("type", "password");

    await user.type(apiKeyInput, "temporary-secret");
    await user.click(getSecretToggle("AI Enrichment", "Gemini"));
    expect(apiKeyInput).toHaveAttribute("type", "text");
    expect(apiKeyInput).toHaveValue("temporary-secret");
    expect(screen.queryByText(/temporary-secret/i)).not.toBeInTheDocument();

    await user.click(getSecretToggle("AI Enrichment", "Gemini"));
    expect(apiKeyInput).toHaveAttribute("type", "password");
  });

  it("limits custom api format to supported options and normalizes legacy values", async () => {
    const user = userEvent.setup();

    render(<AISettingsPage />);

    await screen.findByRole("heading", { level: 1, name: /ai runtime/i });

    await user.click(getProviderCard("AI Enrichment", "Custom"));

    const apiFormatField = getApiFormatField("AI Enrichment");
    expect(apiFormatField.tagName).toBe("SELECT");
    expect(apiFormatField).toHaveValue("openai_responses");
    expect(
      within(apiFormatField).getByRole("option", { name: /anthropic/i }),
    ).toBeInTheDocument();
    expect(
      within(apiFormatField).getByRole("option", { name: /openai responses/i }),
    ).toBeInTheDocument();
    expect(
      within(apiFormatField).queryByRole("option", { name: /^openai$/i }),
    ).not.toBeInTheDocument();
    expect(getSecretInput("AI Enrichment", "Custom")).toBeInstanceOf(
      HTMLInputElement,
    );
  });

  it("preserves the existing stored secret when the secret input is left blank", async () => {
    const user = userEvent.setup();
    putSettingsResponse.mockImplementationOnce(async (_url, init) => {
      const body = JSON.parse(init.body);

      expect(body.gemini_api_key).toBe("");
      expect(body.gemini_model).toBe("gemini-2.5-flash-lite");

      currentSettingsPayload = {
        ...currentSettingsPayload,
        persisted_config: {
          ...currentSettingsPayload.persisted_config,
          gemini: {
            model: "gemini-2.5-flash-lite",
            has_api_key: true,
            api_key_preview: "gem-...3456",
          },
        },
        effective_config: {
          ...currentSettingsPayload.effective_config,
          gemini: {
            model: "gemini-2.5-flash-lite",
            has_api_key: true,
          },
        },
        runtime_status: {
          ...currentSettingsPayload.runtime_status,
          model: "gemini-2.5-flash-lite",
        },
      };

      return mockJsonResponse(currentSettingsPayload);
    });

    render(<AISettingsPage />);

    await screen.findByRole("heading", { level: 1, name: /ai runtime/i });

    expect(getSecretInput("AI Enrichment", "Gemini")).toHaveValue("");
    await user.clear(screen.getByLabelText(/ai enrichment model/i));
    await user.type(
      screen.getByLabelText(/ai enrichment model/i),
      "gemini-2.5-flash-lite",
    );
    await user.click(screen.getByRole("button", { name: /save settings/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /ai runtime settings saved/i,
    );
    const providerGroup = getProviderSettingsGroup("AI Enrichment", "Gemini");
    expect(
      within(providerGroup).getAllByText(/^api key saved$/i).length,
    ).toBeGreaterThan(0);
    expect(screen.getByText(/gem-\.{3}3456/i)).toBeInTheDocument();
  });

  it("renders backend validation errors from a 422 response", async () => {
    const user = userEvent.setup();
    putSettingsResponse.mockImplementationOnce(async () =>
      mockJsonResponse(
        {
          detail: [
            {
              loc: ["body", "ai_enrichment_run_concurrency"],
              msg: "Input should be greater than or equal to 1",
            },
            {
              loc: ["body", "company_ai_enrichment_run_concurrency"],
              msg: "Input should be greater than or equal to 1",
            },
            {
              loc: ["body", "gemini_model"],
              msg: "Input should be a valid string",
            },
          ],
        },
        { ok: false, status: 422 },
      ),
    );

    render(<AISettingsPage />);

    await screen.findByRole("heading", { level: 1, name: /ai runtime/i });

    await user.clear(screen.getByLabelText(/ai enrichment concurrency/i));
    await user.type(screen.getByLabelText(/ai enrichment concurrency/i), "0");
    await user.click(screen.getByRole("button", { name: /save settings/i }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      /ai_enrichment_run_concurrency: input should be greater than or equal to 1/i,
    );
    expect(alert).toHaveTextContent(
      /company_ai_enrichment_run_concurrency: input should be greater than or equal to 1/i,
    );
    expect(alert).toHaveTextContent(
      /gemini_model: input should be a valid string/i,
    );
  });

  it("renders degraded runtime feedback from the save response", async () => {
    const user = userEvent.setup();
    putSettingsResponse.mockImplementationOnce(async () => {
      currentSettingsPayload = {
        ...currentSettingsPayload,
        runtime_status: {
          configured_provider: "gemini",
          active_provider: null,
          provider: "gemini",
          model: "gemini-2.5-flash",
          is_degraded: true,
          degradation_reason: "Failed to initialize provider 'gemini'",
          requires_test: true,
          is_ready: false,
          last_test_status: "failed",
        },
      };

      return mockJsonResponse(currentSettingsPayload);
    });

    render(<AISettingsPage />);

    await screen.findByRole("heading", { level: 1, name: /ai runtime/i });
    await user.click(screen.getByRole("button", { name: /save settings/i }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      /needs a successful configuration test before it can run/i,
    );
    expect(alert).toHaveTextContent(/failed to initialize provider 'gemini'/i);
    expect(screen.getAllByText(/^Needs test$/i).length).toBeGreaterThan(0);
  });

  it("lets jobs and companies use separate providers and submits both profiles in one save", async () => {
    const user = userEvent.setup();
    putSettingsResponse.mockImplementationOnce(async (_url, init) => {
      const body = JSON.parse(init.body);

      expect(body).toEqual({
        llm_provider: "custom",
        company_llm_provider: "anthropic",
        ai_enrichment_run_concurrency: 8,
        company_ai_enrichment_run_concurrency: 2,
        custom_api_key: "deepseek-secret",
        custom_model: "deepseek-v4-flash",
        custom_base_url: "https://api.deepseek.com",
        custom_api_format: "anthropic",
        company_anthropic_api_key: "anthropic-secret-123456",
        company_anthropic_model: "claude-sonnet-4-5",
        company_anthropic_base_url: "https://api.anthropic.com/v1",
      });

      currentSettingsPayload = {
        ...currentSettingsPayload,
        persisted_config: {
          ...currentSettingsPayload.persisted_config,
          llm_provider: "custom",
          company_llm_provider: "anthropic",
          custom: {
            model: "deepseek-v4-flash",
            base_url: "https://api.deepseek.com",
            api_format: "anthropic",
            has_api_key: true,
            api_key_preview: "deep...cret",
          },
          company_anthropic: {
            has_api_key: true,
            api_key_preview: "anth...3456",
            model: "claude-sonnet-4-5",
            base_url: "https://api.anthropic.com/v1",
          },
          anthropic: {
            ...currentSettingsPayload.persisted_config.anthropic,
            has_api_key: false,
            api_key_preview: null,
          },
        },
        effective_config: {
          ...currentSettingsPayload.effective_config,
          llm_provider: "custom",
          company_llm_provider: "anthropic",
          custom: {
            model: "deepseek-v4-flash",
            base_url: "https://api.deepseek.com",
            api_format: "anthropic",
            has_api_key: true,
          },
          company_anthropic: {
            model: "claude-sonnet-4-5",
            base_url: "https://api.anthropic.com/v1",
          },
        },
        runtime_status: {
          configured_provider: "custom",
          active_provider: "custom",
          provider: "custom",
          model: "deepseek-v4-flash",
          is_degraded: false,
          degradation_reason: null,
        },
        company_runtime_status: {
          configured_provider: "anthropic",
          active_provider: "anthropic",
          provider: "anthropic",
          model: "claude-sonnet-4-5",
          is_degraded: false,
          degradation_reason: null,
        },
      };

      return mockJsonResponse(currentSettingsPayload);
    });

    render(<AISettingsPage />);

    await screen.findByRole("heading", { level: 1, name: /ai runtime/i });

    await user.click(getProviderCard("AI Enrichment", "Custom"));
    await user.clear(screen.getByLabelText(/ai enrichment model/i));
    await user.type(
      screen.getByLabelText(/ai enrichment model/i),
      "deepseek-v4-flash",
    );
    await user.clear(screen.getByLabelText(/ai enrichment base url/i));
    await user.type(
      screen.getByLabelText(/ai enrichment base url/i),
      "https://api.deepseek.com",
    );
    await user.selectOptions(getApiFormatField("AI Enrichment"), "anthropic");
    await user.type(
      getSecretInput("AI Enrichment", "Custom"),
      "deepseek-secret",
    );

    await user.click(getProviderCard("Companies", "Anthropic"));
    await user.clear(screen.getByLabelText(/companies concurrency/i));
    await user.type(screen.getByLabelText(/companies concurrency/i), "2");
    await user.clear(screen.getByLabelText(/companies model/i));
    await user.type(
      screen.getByLabelText(/companies model/i),
      "claude-sonnet-4-5",
    );
    await user.clear(screen.getByLabelText(/companies base url/i));
    await user.type(
      screen.getByLabelText(/companies base url/i),
      "https://api.anthropic.com/v1",
    );
    await user.type(
      getSecretInput("Companies", "Anthropic"),
      "anthropic-secret-123456",
    );

    await user.click(screen.getByRole("button", { name: /save settings/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /ai runtime settings saved/i,
    );
    expect(getProviderCard("AI Enrichment", "Custom")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(getProviderCard("Companies", "Anthropic")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });
});
