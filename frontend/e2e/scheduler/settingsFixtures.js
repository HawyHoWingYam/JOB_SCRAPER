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
  providers_by_key: Object.fromEntries(defaultProviderCatalogProviders.map(provider => [provider.key, provider])),
  custom_api_format_options: [
    { value: "anthropic", label: "Anthropic" },
    { value: "openai_responses", label: "OpenAI Responses" },
  ],
};
const defaultJevRequest = {
  enabled: false,
  endpoint: "https://www.rsiai.net/v1/systemone",
  model: "jev-latest",
  api_key: "",
  allowance_microdollars: 10_000_000,
  input_microdollars_per_million_tokens: null,
  output_microdollars_per_million_tokens: null,
  max_request_reservation_microdollars: null,
  sample_limit: 100,
  question_batch_limit: 10,
  concurrency: 2,
  retry_limit: 0,
  timeout_seconds: 30,
  evidence_threshold: "0.800",
  recommendation_threshold: "0.800",
  duplicate_enabled: false,
  duplicate_candidate_limit: 3,
  duplicate_corpus_limit: 200,
  crawl_quality_enabled: false,
  crawl_quality_batch_limit: 20,
  search_rerank_enabled: false,
  search_rerank_candidate_limit: 20,
  incident_triage_enabled: false,
  incident_triage_event_limit: 200,
  maintenance_enabled: false,
  maintenance_model: "jev-latest",
  maintenance_allowance_microdollars: 2_000_000,
  maintenance_interval_days: 30,
  maintenance_min_candidates: 50,
  maintenance_batch_size: 100,
  maintenance_threshold: "0.900",
};
export const aiSettingsPayload = {
  provider_catalog: defaultProviderCatalog,
  persisted_config: {
    llm_provider: "gemini",
    company_llm_provider: "anthropic",
    ai_enrichment_run_concurrency: 8,
    company_ai_enrichment_run_concurrency: 3,
    skill_auto_create_distinct_job_threshold: 5,
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
    skill_auto_create_distinct_job_threshold: 5,
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
  jev: {
    ...defaultJevRequest,
    has_api_key: true,
    api_key_preview: "jev-...alue",
    spent_microdollars: 0,
    reserved_microdollars: 0,
    remaining_microdollars: 10_000_000,
    maintenance_spent_microdollars: 0,
    maintenance_reserved_microdollars: 0,
    maintenance_remaining_microdollars: 2_000_000,
  },
};

export async function interceptSettings(page) {
  let payload = structuredClone(aiSettingsPayload);
  let loadFailure = true;
  let saveFailure = true;
  const requests = [];
  const pacing = ['jobsdb', 'ctgoodjobs', 'offertoday'].map(source_site => ({ source_site, interval_min_seconds: 1, interval_max_seconds: 3, burst_size: 20, burst_pause_seconds: 30 }));
  await page.route(url => url.pathname.startsWith('/api/settings/') || url.pathname.startsWith('/api/jev/'), async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();
    const body = request.postDataJSON();
    requests.push({ path, method, body });
    let result;
    if (path === '/api/jev/runs') result = { runs: [] };
    else if (path === '/api/settings/ai/test') result = { ok: true, scope: body.scope || 'jobs', configured_provider: 'gemini', active_provider: 'gemini', model: payload.persisted_config.gemini.model, latency_ms: 42, config_fingerprint: 'tested' };
    else if (path === '/api/settings/ai') {
      if (method === 'GET' && loadFailure) return route.fulfill({ status: 503, json: { detail: 'Settings temporarily unavailable' } });
      if (method === 'PUT') {
        if (saveFailure) return route.fulfill({ status: 422, json: { detail: [{ loc: ['body', 'gemini_model'], msg: 'Model not accepted' }] } });
        payload.persisted_config.gemini.model = body.gemini_model;
        payload.effective_config.gemini.model = body.gemini_model;
      }
      result = payload;
    } else if (path === '/api/settings/scraper-pacing') result = { items: pacing, active_detail_task_count: 2 };
    else if (path.startsWith('/api/settings/scraper-pacing/')) {
      const source = path.endsWith('/reset') ? path.split('/').at(-2) : path.split('/').at(-1);
      const index = pacing.findIndex(item => item.source_site === source);
      pacing[index] = method === 'PUT' ? { source_site: source, ...body } : { source_site: source, interval_min_seconds: 1, interval_max_seconds: 3, burst_size: 20, burst_pause_seconds: 30 };
      result = pacing[index];
    }
    if (!result) return route.fulfill({ status: 404, json: { detail: `Unmocked Settings API: ${path}` } });
    return route.fulfill({ json: result });
  });
  return { requests, allowLoad: () => { loadFailure = false; }, allowSave: () => { saveFailure = false; } };
}
