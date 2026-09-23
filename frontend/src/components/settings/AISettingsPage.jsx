import { createElement, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  BrainCircuit,
  Eye,
  EyeOff,
  Gauge,
  KeyRound,
  Layers3,
  Save,
  Settings2,
  ShieldCheck,
  FlaskConical,
} from "lucide-react";
import { buildSettingsRoute, parseSettingsRoute } from "./settingsRoute";
import { apiPath } from "../../api/base";
import { formatApiErrorDetail } from "../../api/errors";
import ScraperPacingSettings from "./ScraperPacingSettings";
import "./AISettingsPage.css";

const PROFILE_LABELS = {
  jobs: "AI Enrichment",
  companies: "Companies",
};

function getProviderCatalog(payload) {
  return payload?.provider_catalog || {};
}

function getProviderCatalogProvidersByKey(payload) {
  const providerCatalog = getProviderCatalog(payload);
  const providersByKey =
    providerCatalog?.providers_by_key &&
    typeof providerCatalog.providers_by_key === "object" &&
    !Array.isArray(providerCatalog.providers_by_key)
      ? providerCatalog.providers_by_key
      : {};
  const providers = Array.isArray(providerCatalog?.providers)
    ? providerCatalog.providers
    : [];

  if (providers.length === 0) {
    return providersByKey;
  }

  return Object.fromEntries(
    Object.entries(providersByKey).concat(
      providers
        .filter((provider) => provider?.key)
        .map((provider) => [provider.key, provider]),
    ),
  );
}

function getProviderCatalogProviders(payload) {
  const providerCatalog = getProviderCatalog(payload);
  if (
    Array.isArray(providerCatalog?.providers) &&
    providerCatalog.providers.length > 0
  ) {
    return providerCatalog.providers;
  }

  return Object.values(getProviderCatalogProvidersByKey(payload));
}

function getProviderMetadata(payload, provider) {
  if (!provider) {
    return null;
  }

  return getProviderCatalogProvidersByKey(payload)?.[provider] || null;
}

function toProviderLabel(payload, provider) {
  return (
    getProviderMetadata(payload, provider)?.label ||
    String(provider || "Unknown")
  );
}

function getProviderDescription(payload, provider) {
  return getProviderMetadata(payload, provider)?.description || "";
}

function getProviderFields(payload, provider) {
  const fields = getProviderMetadata(payload, provider)?.fields;
  return Array.isArray(fields) ? fields : [];
}

function getProviderSecretRequestKey(payload, provider) {
  return getProviderMetadata(payload, provider)?.secret_request_key || null;
}

function getCustomApiFormatOptions(payload) {
  const options = getProviderCatalog(payload)?.custom_api_format_options;
  return Array.isArray(options) ? options : [];
}

function getDefaultApiFormatValue(payload) {
  const options = getCustomApiFormatOptions(payload);

  if (options.some((option) => option.value === "anthropic")) {
    return "anthropic";
  }

  return options[0]?.value || "";
}

function getProviderFieldRequestKey(field) {
  return field?.request_key || field?.requestKey || null;
}

function getProviderSetupLabel(payload, provider) {
  const editableFieldCount =
    getProviderFields(payload, provider).length +
    (getProviderSecretRequestKey(payload, provider) ? 1 : 0);

  if (editableFieldCount === 0) {
    return "No credentials required";
  }

  return editableFieldCount === 1
    ? "1 setting"
    : `${editableFieldCount} settings`;
}

function getProfileProviderKey(profileKey) {
  return profileKey === "companies" ? "company_llm_provider" : "llm_provider";
}

function getScopedProviderConfigKey(profileKey, provider) {
  return profileKey === "companies" ? `company_${provider}` : provider;
}

function getSelectedProvider(payload, profileKey) {
  const providerKey = getProfileProviderKey(profileKey);
  return (
    payload?.persisted_config?.[providerKey] ||
    payload?.effective_config?.[providerKey] ||
    "mock"
  );
}

function getProviderConfig(payload, profileKey, provider) {
  const configKey = getScopedProviderConfigKey(profileKey, provider);
  return (
    payload?.persisted_config?.[configKey] ||
    payload?.effective_config?.[configKey] ||
    {}
  );
}

function getProfileSecretKey(payload, profileKey, provider) {
  const secretRequestKey = getProviderSecretRequestKey(payload, provider);
  if (!secretRequestKey) {
    return null;
  }

  return profileKey === "companies"
    ? `company_${secretRequestKey}`
    : secretRequestKey;
}

function getProviderInitialValue(payload, profileKey, provider, key) {
  const persistedValue =
    payload?.persisted_config?.[
      getScopedProviderConfigKey(profileKey, provider)
    ]?.[key];
  if (persistedValue !== null && persistedValue !== undefined) {
    return String(persistedValue);
  }

  const effectiveValue =
    payload?.effective_config?.[
      getScopedProviderConfigKey(profileKey, provider)
    ]?.[key];
  if (effectiveValue !== null && effectiveValue !== undefined) {
    return String(effectiveValue);
  }

  return "";
}

function normalizeApiFormatValue(value, payload) {
  const options = getCustomApiFormatOptions(payload);

  if (
    value === "openai" &&
    options.some((option) => option.value === "openai_responses")
  ) {
    return "openai_responses";
  }

  if (options.some((option) => option.value === value)) {
    return value;
  }

  return getDefaultApiFormatValue(payload) || value || "";
}

function getProviderFieldValue(field, value, payload) {
  if (field?.key === "api_format") {
    return normalizeApiFormatValue(value, payload);
  }

  return value ?? "";
}

function createProfileState(payload, profileKey) {
  const selectedProvider = getSelectedProvider(payload, profileKey);
  const providerKeys = [
    ...new Set(
      getProviderCatalogProviders(payload)
        .map((provider) => provider?.key)
        .concat(selectedProvider)
        .filter(Boolean),
    ),
  ];

  return {
    llm_provider: selectedProvider,
    providers: providerKeys.reduce((accumulator, provider) => {
      const providerValues = { api_key: "" };

      for (const field of getProviderFields(payload, provider)) {
        providerValues[field.key] = getProviderFieldValue(
          field,
          getProviderInitialValue(payload, profileKey, provider, field.key),
          payload,
        );
      }

      accumulator[provider] = providerValues;
      return accumulator;
    }, {}),
  };
}

function createFormState(payload) {
  const jev = payload?.jev || {};
  return {
    jobs: createProfileState(payload, "jobs"),
    companies: createProfileState(payload, "companies"),
    ai_enrichment_run_concurrency: String(
      payload?.persisted_config?.ai_enrichment_run_concurrency ??
        payload?.effective_config?.ai_enrichment_run_concurrency ??
        "",
    ),
    company_ai_enrichment_run_concurrency: String(
      payload?.persisted_config?.company_ai_enrichment_run_concurrency ??
        payload?.effective_config?.company_ai_enrichment_run_concurrency ??
        payload?.persisted_config?.ai_enrichment_run_concurrency ??
        payload?.effective_config?.ai_enrichment_run_concurrency ??
        "",
    ),
    skill_auto_create_distinct_job_threshold: String(
      payload?.persisted_config?.skill_auto_create_distinct_job_threshold ??
        payload?.effective_config?.skill_auto_create_distinct_job_threshold ??
        10,
    ),
    skill_candidate_recommendation_limit: String(
      payload?.persisted_config?.skill_candidate_recommendation_limit ??
        payload?.effective_config?.skill_candidate_recommendation_limit ?? 5,
    ),
    skill_candidate_evidence_limit: String(
      payload?.persisted_config?.skill_candidate_evidence_limit ??
        payload?.effective_config?.skill_candidate_evidence_limit ?? 5,
    ),
    jev: {
      enabled: Boolean(jev.enabled),
      endpoint: jev.endpoint || "https://www.rsiai.net/v1/systemone",
      model: jev.model || "jev-latest",
      api_key: "",
      allowance_usd: (
        Number(jev.allowance_microdollars ?? 10_000_000) / 1_000_000
      ).toFixed(2),
      input_microdollars_per_million_tokens:
        jev.input_microdollars_per_million_tokens == null
          ? ""
          : String(jev.input_microdollars_per_million_tokens),
      output_microdollars_per_million_tokens:
        jev.output_microdollars_per_million_tokens == null
          ? ""
          : String(jev.output_microdollars_per_million_tokens),
      max_request_reservation_microdollars:
        jev.max_request_reservation_microdollars == null
          ? ""
          : String(jev.max_request_reservation_microdollars),
      sample_limit: String(jev.sample_limit ?? 100),
      question_batch_limit: String(jev.question_batch_limit ?? 10),
      concurrency: String(jev.concurrency ?? 2),
      retry_limit: String(jev.retry_limit ?? 0),
      timeout_seconds: String(jev.timeout_seconds ?? 30),
      evidence_threshold: String(jev.evidence_threshold ?? "0.800"),
      recommendation_threshold: String(
        jev.recommendation_threshold ?? "0.800",
      ),
      duplicate_enabled: Boolean(jev.duplicate_enabled),
      duplicate_candidate_limit: String(jev.duplicate_candidate_limit ?? 3),
      duplicate_corpus_limit: String(jev.duplicate_corpus_limit ?? 200),
      crawl_quality_enabled: Boolean(jev.crawl_quality_enabled),
      crawl_quality_batch_limit: String(jev.crawl_quality_batch_limit ?? 20),
      search_rerank_enabled: Boolean(jev.search_rerank_enabled),
      search_rerank_candidate_limit: String(jev.search_rerank_candidate_limit ?? 20),
      incident_triage_enabled: Boolean(jev.incident_triage_enabled),
      incident_triage_event_limit: String(jev.incident_triage_event_limit ?? 200),
      maintenance_enabled: Boolean(jev.maintenance_enabled),
      maintenance_model: jev.maintenance_model || "jev-latest",
      maintenance_allowance_usd: (
        Number(jev.maintenance_allowance_microdollars ?? 2_000_000) / 1_000_000
      ).toFixed(2),
      maintenance_interval_days: String(jev.maintenance_interval_days ?? 30),
      maintenance_min_candidates: String(
        jev.maintenance_min_candidates ?? 50,
      ),
      maintenance_batch_size: String(jev.maintenance_batch_size ?? 100),
      maintenance_threshold: String(jev.maintenance_threshold ?? "0.900"),
    },
  };
}

function createSecretVisibilityState() {
  return {
    jobs: false,
    companies: false,
    jev: false,
  };
}

function formatValidationErrors(detail) {
  if (!Array.isArray(detail)) {
    return ["Failed to save AI runtime settings."];
  }

  return detail.map((item) => {
    const location = Array.isArray(item?.loc)
      ? item.loc.slice(1).join(".")
      : "settings";
    const message = item?.msg || "Invalid value";
    return `${location}: ${message}`;
  });
}

function appendSecret(body, requestKey, value) {
  const nextValue = value ?? "";
  if (!(requestKey in body) || nextValue) {
    body[requestKey] = nextValue;
  }
}

function optionalInteger(value) {
  return value === "" || value == null ? null : Number(value);
}

function getJevRunTokenUsage(run) {
  return (run?.items || []).reduce((total, item) => {
    const usage = item?.result?.usage;
    return total + Number(usage?.input_tokens || 0) + Number(usage?.output_tokens || 0);
  }, 0);
}

function formatMicrodollars(value) {
  return (Number(value || 0) / 1_000_000).toFixed(2);
}

function buildRequestBody(formState, settingsPayload) {
  const body = {
    llm_provider: formState.jobs.llm_provider,
    company_llm_provider: formState.companies.llm_provider,
    ai_enrichment_run_concurrency: Number(
      formState.ai_enrichment_run_concurrency,
    ),
    company_ai_enrichment_run_concurrency: Number(
      formState.company_ai_enrichment_run_concurrency,
    ),
    skill_auto_create_distinct_job_threshold: Number(
      formState.skill_auto_create_distinct_job_threshold,
    ),
    skill_candidate_recommendation_limit: Number(
      formState.skill_candidate_recommendation_limit,
    ),
    skill_candidate_evidence_limit: Number(
      formState.skill_candidate_evidence_limit,
    ),
    jev: {
      enabled: formState.jev.enabled,
      endpoint: formState.jev.endpoint,
      model: formState.jev.model,
      api_key: formState.jev.api_key,
      allowance_microdollars: Math.round(
        Number(formState.jev.allowance_usd) * 1_000_000,
      ),
      input_microdollars_per_million_tokens: optionalInteger(
        formState.jev.input_microdollars_per_million_tokens,
      ),
      output_microdollars_per_million_tokens: optionalInteger(
        formState.jev.output_microdollars_per_million_tokens,
      ),
      max_request_reservation_microdollars: optionalInteger(
        formState.jev.max_request_reservation_microdollars,
      ),
      sample_limit: Number(formState.jev.sample_limit),
      question_batch_limit: Number(formState.jev.question_batch_limit),
      concurrency: Number(formState.jev.concurrency),
      retry_limit: Number(formState.jev.retry_limit),
      timeout_seconds: Number(formState.jev.timeout_seconds),
      evidence_threshold: formState.jev.evidence_threshold,
      recommendation_threshold: formState.jev.recommendation_threshold,
      duplicate_enabled: formState.jev.duplicate_enabled,
      duplicate_candidate_limit: Number(formState.jev.duplicate_candidate_limit),
      duplicate_corpus_limit: Number(formState.jev.duplicate_corpus_limit),
      crawl_quality_enabled: formState.jev.crawl_quality_enabled,
      crawl_quality_batch_limit: Number(formState.jev.crawl_quality_batch_limit),
      search_rerank_enabled: formState.jev.search_rerank_enabled,
      search_rerank_candidate_limit: Number(formState.jev.search_rerank_candidate_limit),
      incident_triage_enabled: formState.jev.incident_triage_enabled,
      incident_triage_event_limit: Number(formState.jev.incident_triage_event_limit),
      maintenance_enabled: formState.jev.maintenance_enabled,
      maintenance_model: formState.jev.maintenance_model,
      maintenance_allowance_microdollars: Math.round(
        Number(formState.jev.maintenance_allowance_usd) * 1_000_000,
      ),
      maintenance_interval_days: Number(
        formState.jev.maintenance_interval_days,
      ),
      maintenance_min_candidates: Number(
        formState.jev.maintenance_min_candidates,
      ),
      maintenance_batch_size: Number(formState.jev.maintenance_batch_size),
      maintenance_threshold: formState.jev.maintenance_threshold,
    },
  };

  for (const [profileKey, prefix] of [
    ["jobs", ""],
    ["companies", "company_"],
  ]) {
    const profile = formState[profileKey];
    const provider = profile.llm_provider;
    const providerValues = profile.providers[provider] || {};

    for (const field of getProviderFields(settingsPayload, provider)) {
      const requestKey = getProviderFieldRequestKey(field);
      if (!requestKey) {
        continue;
      }

      body[`${prefix}${requestKey}`] = getProviderFieldValue(
        field,
        providerValues[field.key],
        settingsPayload,
      );
    }

    const secretRequestKey = getProfileSecretKey(
      settingsPayload,
      profileKey,
      provider,
    );
    if (secretRequestKey) {
      appendSecret(body, secretRequestKey, providerValues.api_key);
    }
  }

  return body;
}

function buildProfileTestPayload(profileKey, formState, settingsPayload) {
  const profile = formState[profileKey];
  const provider = profile.llm_provider;
  const values = profile.providers[provider] || {};
  const providerPayload = {
    llm_provider: provider,
  };

  for (const field of getProviderFields(settingsPayload, provider)) {
    const requestKey = getProviderFieldRequestKey(field);
    if (!requestKey) {
      continue;
    }

    providerPayload[requestKey] = getProviderFieldValue(
      field,
      values[field.key],
      settingsPayload,
    );
  }

  const secretRequestKey = getProviderSecretRequestKey(
    settingsPayload,
    provider,
  );
  if (secretRequestKey) {
    appendSecret(providerPayload, secretRequestKey, values.api_key);
  }

  return {
    scope: profileKey,
    profile: providerPayload,
  };
}

function formatProbeLatency(latencyMs) {
  return latencyMs === null || latencyMs === undefined
    ? "Latency unavailable"
    : `${latencyMs} ms`;
}

function buildProfileTestFeedback(profileKey, payload) {
  const modelCheck = payload?.model_check;
  const webSearchCheck = payload?.web_search_check;

  if (profileKey !== "companies" || !modelCheck) {
    return {
      tone: "success",
      title: "Configuration test passed",
      lines: [
        `${PROFILE_LABELS[profileKey]} provider responded successfully.`,
        formatProbeLatency(payload?.latency_ms),
      ],
    };
  }

  const lines = [
    `Model check passed (${formatProbeLatency(modelCheck.latency_ms)})`,
  ];
  const hasWebSearchWarning = Boolean(webSearchCheck) && !webSearchCheck.ok;

  if (webSearchCheck) {
    if (webSearchCheck.ok) {
      lines.push(
        `Web search check passed (${formatProbeLatency(webSearchCheck.latency_ms)})`,
      );
    } else if (webSearchCheck.supported === false) {
      lines.push(
        `Web search unavailable: ${webSearchCheck.error_message || "This provider does not support web search."}`,
      );
    } else {
      lines.push(
        `Web search warning: ${webSearchCheck.error_message || "Web search probe failed."}`,
      );
    }
  }

  return {
    tone: hasWebSearchWarning ? "warning" : "success",
    title: hasWebSearchWarning
      ? "Configuration test passed with warnings"
      : "Configuration test passed",
    lines,
  };
}

function SummaryCard({ icon, label, value, hint, tone = "default" }) {
  return (
    <article className={`ai-settings-summary-card glass-panel tone-${tone}`}>
      <div className="ai-settings-summary-icon">
        {createElement(icon, { size: 18 })}
      </div>
      <div className="ai-settings-summary-copy">
        <span>{label}</span>
        <strong>{value}</strong>
        {hint ? <small>{hint}</small> : null}
      </div>
    </article>
  );
}

function getRuntimeStateLabel(runtimeStatus) {
  if (runtimeStatus?.is_ready) {
    return "Ready";
  }
  if (runtimeStatus?.requires_test) {
    return "Needs test";
  }
  return "Blocked";
}

function getAggregateRuntimeState(jobRuntimeStatus, companyRuntimeStatus) {
  const states = [
    getRuntimeStateLabel(jobRuntimeStatus),
    getRuntimeStateLabel(companyRuntimeStatus),
  ];

  if (states.every((state) => state === "Ready")) {
    return "Ready";
  }
  if (states.includes("Needs test")) {
    return "Needs test";
  }
  return "Blocked";
}

function getProfileSummaryProviderValue(
  profileKey,
  runtimeStatus,
  formProfile,
  settingsPayload,
) {
  const providerKey = getProfileProviderKey(profileKey);
  const configuredProvider =
    runtimeStatus?.configured_provider ||
    settingsPayload?.persisted_config?.[providerKey] ||
    settingsPayload?.effective_config?.[providerKey] ||
    null;

  if (configuredProvider) {
    return toProviderLabel(settingsPayload, configuredProvider);
  }

  const draftProvider = formProfile?.llm_provider;
  if (draftProvider && draftProvider !== "mock") {
    return toProviderLabel(settingsPayload, draftProvider);
  }

  return "Not configured";
}

function FeedbackBanner({ feedback }) {
  const ref = useRef(null);
  useEffect(() => { if (feedback) ref.current?.focus(); }, [feedback]);
  if (!feedback) {
    return null;
  }

  return (
    <div
      ref={ref}
      tabIndex={-1}
      className={`ai-settings-message ai-settings-message-${feedback.tone} glass-panel`}
      role="alert"
    >
      <div className="ai-settings-message-title-row">
        {feedback.tone === "error" || feedback.tone === "warning" ? (
          <AlertTriangle size={18} />
        ) : (
          <ShieldCheck size={18} />
        )}
        <strong>{feedback.title}</strong>
      </div>
      {feedback.lines?.length ? (
        <div className="ai-settings-message-copy">
          {feedback.lines.map((line) => (
            <p key={line}>{line}</p>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function ProfileSection({
  profileKey,
  profileLabel,
  formState,
  settingsPayload,
  saving,
  testing,
  isSecretVisible,
  toggleSecretVisibility,
  updateProfileProvider,
  updateProfileField,
  onTestProfile,
}) {
  const catalogProviders = getProviderCatalogProviders(settingsPayload);
  const selectedProvider =
    formState?.llm_provider || getSelectedProvider(settingsPayload, profileKey);
  const selectedProviderLabel = toProviderLabel(
    settingsPayload,
    selectedProvider,
  );
  const providerFields = getProviderFields(settingsPayload, selectedProvider);
  const providerValues = formState?.providers?.[selectedProvider] || {};
  const providerConfig = getProviderConfig(
    settingsPayload,
    profileKey,
    selectedProvider,
  );
  const hasSavedApiKey = Boolean(providerConfig?.has_api_key);
  const providerDescription = getProviderDescription(
    settingsPayload,
    selectedProvider,
  );
  const secretRequestKey = getProviderSecretRequestKey(
    settingsPayload,
    selectedProvider,
  );
  const customApiFormatOptions = getCustomApiFormatOptions(settingsPayload);
  const showProviderSetupHint =
    providerFields.length === 0 && !secretRequestKey;

  return (
    <section id={`settings-${profileKey}`} tabIndex={-1} className="ai-settings-panel glass-panel">
      <div className="ai-settings-section-heading">
        <div>
          <h2>{profileLabel} Profile</h2>
          <p>
            {profileLabel} keeps its own provider, credentials, and model
            settings.
          </p>
        </div>
        <button
          type="button"
          className="ai-settings-save-button"
          onClick={() => onTestProfile(profileKey)}
          disabled={saving || testing}
        >
          <FlaskConical size={16} />
          <span>
            {testing ? "Testing..." : `Test ${profileLabel} configuration`}
          </span>
        </button>
      </div>

      <p className="ai-settings-test-note">Testing sends the current draft to the provider and may incur usage charges. Save settings to apply edited configuration; testing alone does not save the draft.</p>
      <div
        className="ai-settings-provider-picker"
        role="group"
        aria-label={`${profileLabel} provider`}
      >
        {catalogProviders.map((providerMetadata) => {
          const provider = providerMetadata.key;
          const isSelected = provider === selectedProvider;

          return (
            <button
              key={provider}
              type="button"
              className={`ai-settings-provider-card ${isSelected ? "selected" : ""}`}
              aria-pressed={isSelected}
              onClick={() => updateProfileProvider(profileKey, provider)}
              disabled={saving}
            >
              <strong>{toProviderLabel(settingsPayload, provider)}</strong>
              <span>{getProviderSetupLabel(settingsPayload, provider)}</span>
              <small>{getProviderDescription(settingsPayload, provider)}</small>
            </button>
          );
        })}
      </div>

      <fieldset
        className="ai-settings-provider-group"
        aria-label={`${profileLabel} ${selectedProviderLabel} settings`}
      >
        <legend>
          {profileLabel} {selectedProviderLabel} settings
        </legend>

        <p className="ai-settings-field-hint">{providerDescription}</p>

        <div className="ai-settings-form-grid">
          {providerFields.map((field) => (
            <label className="ai-settings-field" key={field.key}>
              <span>{field.label}</span>
              {field.key === "api_format" ? (
                <select
                  aria-label={`${profileLabel} ${field.label}`}
                  value={normalizeApiFormatValue(
                    providerValues[field.key] || "",
                    settingsPayload,
                  )}
                  onChange={(event) =>
                    updateProfileField(
                      profileKey,
                      selectedProvider,
                      field.key,
                      event.target.value,
                    )
                  }
                  disabled={saving}
                >
                  {customApiFormatOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  aria-label={`${profileLabel} ${field.label}`}
                  type="text"
                  value={providerValues[field.key] || ""}
                  onChange={(event) =>
                    updateProfileField(
                      profileKey,
                      selectedProvider,
                      field.key,
                      event.target.value,
                    )
                  }
                  disabled={saving}
                />
              )}
            </label>
          ))}

          {secretRequestKey ? (
            <label className="ai-settings-field ai-settings-secret-field">
              <div className="ai-settings-field-label-row">
                <span>API key</span>
                {hasSavedApiKey ? (
                  <span className="ai-settings-saved-badge">
                    <KeyRound size={12} />
                    <span>API key saved</span>
                  </span>
                ) : null}
              </div>
              <div className="ai-settings-password-row">
                <input
                  aria-label={`${profileLabel} API key`}
                  type={isSecretVisible ? "text" : "password"}
                  value={providerValues.api_key || ""}
                  onChange={(event) =>
                    updateProfileField(
                      profileKey,
                      selectedProvider,
                      "api_key",
                      event.target.value,
                    )
                  }
                  placeholder={
                    hasSavedApiKey
                      ? "Leave blank to keep existing key"
                      : "Enter API key"
                  }
                  disabled={saving}
                />
                <button
                  type="button"
                  className="ai-settings-password-toggle"
                  aria-label={`${isSecretVisible ? "Hide" : "Show"} ${profileLabel} API key`}
                  onClick={() => toggleSecretVisibility(profileKey)}
                  disabled={saving}
                >
                  {isSecretVisible ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
              <div className="ai-settings-secret-meta">
                <div className="ai-settings-secret-value">
                  <KeyRound size={16} />
                  <strong>
                    {hasSavedApiKey ? "API key saved" : "No API key saved"}
                  </strong>
                  {providerConfig?.api_key_preview ? (
                    <code>{providerConfig.api_key_preview}</code>
                  ) : null}
                </div>
                <p className="ai-settings-field-hint">
                  {profileKey === "companies"
                    ? "Saved only for the Companies profile."
                    : "Saved only for the AI Enrichment profile."}
                </p>
              </div>
            </label>
          ) : null}

          {showProviderSetupHint ? (
            <div className="ai-settings-provider-empty-state">
              <p className="ai-settings-field-hint">
                {selectedProviderLabel} does not require extra setup.
              </p>
            </div>
          ) : null}
        </div>
      </fieldset>
    </section>
  );
}

function AIRuntimeSettings({ profileFocus }) {
  const [loadRevision, setLoadRevision] = useState(0);
  const [settingsPayload, setSettingsPayload] = useState(null);
  const [formState, setFormState] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testingProfile, setTestingProfile] = useState(null);
  const [error, setError] = useState(null);
  const [feedback, setFeedback] = useState(null);
  const [jevRuns, setJevRuns] = useState([]);
  const [jevRunError, setJevRunError] = useState(null);
  const [jevActionId, setJevActionId] = useState(null);
  const [secretVisibility, setSecretVisibility] = useState(
    createSecretVisibilityState,
  );

  const dirty = Boolean(formState && settingsPayload && JSON.stringify(formState) !== JSON.stringify(createFormState(settingsPayload)));
  useEffect(() => {
    if (!dirty) return undefined;
    const warn = event => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);
  useEffect(() => {
    if (!loading && profileFocus) {
      document.getElementById(`settings-${profileFocus}`)?.focus();
    }
  }, [loading, profileFocus]);

  useEffect(() => {
    let cancelled = false;

    async function loadSettings() {
      setLoading(true);
      setError(null);

      try {
        const response = await fetch(apiPath("/settings/ai"));
        if (!response.ok) {
          throw new Error(`Failed to load AI settings (${response.status})`);
        }

        const payload = await response.json();
        if (!cancelled) {
          setSettingsPayload(payload);
          setFormState(createFormState(payload));
          setSecretVisibility(createSecretVisibilityState());
        }
      } catch (err) {
        if (!cancelled) {
          setError(err.message);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    loadSettings();

    return () => {
      cancelled = true;
    };
  }, [loadRevision]);

  useEffect(() => {
    let cancelled = false;

    async function loadJevRuns() {
      try {
        const response = await fetch(apiPath("/jev/runs"));
        if (!response.ok) {
          throw new Error(`Failed to load Jev runs (${response.status})`);
        }
        const payload = await response.json();
        if (!cancelled) {
          setJevRuns(Array.isArray(payload?.runs) ? payload.runs : []);
        }
      } catch (err) {
        if (!cancelled) {
          setJevRunError(err.message);
        }
      }
    }

    loadJevRuns();
    return () => {
      cancelled = true;
    };
  }, [loadRevision]);

  function updateProfileProvider(profileKey, provider) {
    setFormState((currentState) => ({
      ...currentState,
      [profileKey]: {
        ...currentState[profileKey],
        llm_provider: provider,
      },
    }));
  }

  function updateProfileField(profileKey, provider, key, value) {
    setFormState((currentState) => ({
      ...currentState,
      [profileKey]: {
        ...currentState[profileKey],
        providers: {
          ...currentState[profileKey].providers,
          [provider]: {
            ...currentState[profileKey].providers[provider],
            [key]: value,
          },
        },
      },
    }));
  }

  function updateTopLevelField(key, value) {
    setFormState((currentState) => ({
      ...currentState,
      [key]: value,
    }));
  }

  function updateJevField(key, value) {
    setFormState((currentState) => ({
      ...currentState,
      jev: {
        ...currentState.jev,
        [key]: value,
      },
    }));
  }

  function toggleSecretVisibility(profileKey) {
    setSecretVisibility((currentState) => ({
      ...currentState,
      [profileKey]: !currentState[profileKey],
    }));
  }

  function replaceJevRun(updatedRun) {
    setJevRuns((currentRuns) => [
      updatedRun,
      ...currentRuns.filter((run) => run.id !== updatedRun.id),
    ]);
    if (updatedRun?.allowance) {
      setSettingsPayload((currentPayload) => ({
        ...currentPayload,
        jev: {
          ...currentPayload.jev,
          ...updatedRun.allowance,
        },
      }));
    }
  }

  async function performJevRunAction(runId, action) {
    setJevActionId(runId);
    setJevRunError(null);
    try {
      const response = await fetch(apiPath(`/jev/runs/${runId}/${action}`), {
        method: "POST",
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(
          typeof payload?.detail === "string"
            ? payload.detail
            : `Jev run action failed (${response.status})`,
        );
      }
      replaceJevRun(payload);
      return payload;
    } catch (err) {
      setJevRunError(err.message);
      return null;
    } finally {
      setJevActionId(null);
    }
  }

  async function runJevSmokeTest() {
    setJevActionId("new");
    setJevRunError(null);
    try {
      const response = await fetch(apiPath("/jev/runs"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          purpose: "configuration_smoke_test",
          rubric_version: "jev-smoke-v1",
          items: [
            {
              subject_id: "settings-smoke-test",
              payload: {
                state: "A job posting explicitly requires Python experience.",
                questions: {
                  requires_python: {
                    type: "noul",
                    instructions:
                      "The job explicitly requires Python experience.",
                  },
                },
              },
            },
          ],
        }),
      });
      const created = await response.json();
      if (!response.ok) {
        throw new Error(
          typeof created?.detail === "string"
            ? created.detail
            : `Failed to start Jev smoke run (${response.status})`,
        );
      }
      replaceJevRun(created);
      setJevActionId(created.id);
      const executeResponse = await fetch(
        apiPath(`/jev/runs/${created.id}/execute-next`),
        { method: "POST" },
      );
      const executed = await executeResponse.json();
      if (!executeResponse.ok) {
        const refreshedResponse = await fetch(apiPath(`/jev/runs/${created.id}`));
        if (refreshedResponse.ok) {
          replaceJevRun(await refreshedResponse.json());
        }
        throw new Error(
          formatApiErrorDetail(
            executed?.detail,
            `Jev smoke run failed (${executeResponse.status})`,
          ),
        );
      }
      replaceJevRun(executed);
    } catch (err) {
      setJevRunError(err.message);
    } finally {
      setJevActionId(null);
    }
  }

  async function handleSubmit(event) {
    event.preventDefault();
    setSaving(true);
    setFeedback(null);

    try {
      const response = await fetch(apiPath("/settings/ai"), {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(buildRequestBody(formState, settingsPayload)),
      });

      const payload = await response.json();

      if (!response.ok) {
        if (response.status === 422) {
          setFeedback({
            tone: "error",
            title: "Validation failed",
            lines: [...formatValidationErrors(payload?.detail), "Your unsaved changes are retained. Correct the fields and save again."],
          });
          return;
        }

        throw new Error(`Failed to save AI settings (${response.status})`);
      }

      setSettingsPayload(payload);
      setFormState(createFormState(payload));
      setSecretVisibility(createSecretVisibilityState());

      const degradedLines = [];
      if (payload?.runtime_status?.requires_test) {
        degradedLines.push(
          `AI Enrichment needs a successful configuration test before it can run. ${payload.runtime_status.degradation_reason || ""}`.trim(),
        );
      }
      if (payload?.company_runtime_status?.requires_test) {
        degradedLines.push(
          `Companies needs a successful configuration test before it can run. ${payload.company_runtime_status.degradation_reason || ""}`.trim(),
        );
      }

      setFeedback(
        degradedLines.length
          ? {
              tone: "warning",
              title: "AI runtime settings saved",
              lines: degradedLines,
            }
          : {
              tone: "success",
              title: "AI runtime settings saved",
              lines: ["Runtime settings are saved."],
            },
      );
    } catch (err) {
      setFeedback({
        tone: "error",
        title: "Save failed",
        lines: [err.message, "Your unsaved changes are retained. Retry Save settings when ready."],
      });
    } finally {
      setSaving(false);
    }
  }

  async function handleTestProfile(profileKey) {
    setTestingProfile(profileKey);
    setFeedback(null);

    try {
      const response = await fetch(apiPath("/settings/ai/test"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(
          buildProfileTestPayload(profileKey, formState, settingsPayload),
        ),
      });

      const payload = await response.json();

      if (!response.ok) {
        const message =
          payload?.detail?.error_message || "Configuration test failed";
        setFeedback({
          tone: "error",
          title: "Configuration test failed",
          lines: [message],
        });
        return;
      }

      const nextFeedback = buildProfileTestFeedback(profileKey, payload);
      try {
        const refreshed = await fetch(apiPath('/settings/ai'));
        if (!refreshed.ok) throw new Error('Saved runtime status could not be refreshed.');
        setSettingsPayload(await refreshed.json());
      } catch {
        nextFeedback.lines = [...(nextFeedback.lines || []), 'The test finished, but saved runtime status could not be refreshed. Your draft is retained.'];
      }
      setFeedback(nextFeedback);
    } catch (err) {
      setFeedback({
        tone: "error",
        title: "Configuration test failed",
        lines: [err.message],
      });
    } finally {
      setTestingProfile(null);
    }
  }

  if (loading) {
    return (
      <section className="ai-settings-page">
        <div className="ai-settings-hero glass-panel">
          <p className="ai-settings-eyebrow">Settings</p>
          <h1>AI Runtime</h1>
          <p className="ai-settings-subtitle">
            Loading runtime configuration...
          </p>
        </div>
      </section>
    );
  }

  if (error) {
    return (
      <section className="ai-settings-page">
        <div className="ai-settings-hero glass-panel">
          <p className="ai-settings-eyebrow">Settings</p>
          <h1>AI Runtime</h1>
        </div>
        <div
          className="ai-settings-message ai-settings-message-error glass-panel"
          role="alert"
        >
          {error}
          <button type="button" onClick={() => setLoadRevision(value => value + 1)}>Retry loading settings</button>
        </div>
      </section>
    );
  }

  const persistedConfig = settingsPayload?.persisted_config || {};
  const effectiveConfig = settingsPayload?.effective_config || {};
  const jobRuntimeStatus = settingsPayload?.runtime_status || {};
  const companyRuntimeStatus = settingsPayload?.company_runtime_status || {};
  const isAnyDegraded = Boolean(
    jobRuntimeStatus.is_degraded || companyRuntimeStatus.is_degraded,
  );
  const aggregateRuntimeState = getAggregateRuntimeState(
    jobRuntimeStatus,
    companyRuntimeStatus,
  );

  return (
    <section className="ai-settings-page">
      <header className="ai-settings-hero glass-panel">
        <div className="ai-settings-hero-copy">
          <p className="ai-settings-eyebrow">Settings</p>
          <h1>AI Runtime</h1>
          <p className="ai-settings-subtitle">
            Manage separate provider profiles for AI enrichment and company
            descriptions while reusing saved provider credentials.
          </p>
        </div>
        <div className="ai-settings-hero-badges">
          <span className="ai-settings-chip">
            {saving ? "Saving..." : dirty ? "Unsaved changes" : "Saved configuration"}
          </span>
          <span
            className={`ai-settings-chip ${isAnyDegraded ? "warning" : "success"}`}
          >
            {aggregateRuntimeState === "Ready"
              ? "Runtime ready"
              : aggregateRuntimeState}
          </span>
        </div>
      </header>

      <FeedbackBanner feedback={feedback} />

      <nav className="ai-settings-jump-nav" aria-label="Runtime configuration sections">
        {[["jobs", "AI Enrichment profile"], ["companies", "Companies profile"], ["jev", "Jev System One"], ["throughput", "Throughput"]].map(([id, label]) => <button type="button" key={id} onClick={() => document.getElementById(`settings-${id}`)?.focus()}>{label}</button>)}
      </nav>
      <section className="ai-settings-summary-grid">
        <SummaryCard
          icon={BrainCircuit}
          label="AI Enrichment"
          value={getProfileSummaryProviderValue(
            "jobs",
            jobRuntimeStatus,
            formState?.jobs,
            settingsPayload,
          )}
          hint={jobRuntimeStatus.model || "No model reported"}
          tone={jobRuntimeStatus.requires_test ? "warning" : "default"}
        />
        <SummaryCard
          icon={Layers3}
          label="Companies"
          value={getProfileSummaryProviderValue(
            "companies",
            companyRuntimeStatus,
            formState?.companies,
            settingsPayload,
          )}
          hint={companyRuntimeStatus.model || "No model reported"}
          tone={companyRuntimeStatus.requires_test ? "warning" : "default"}
        />
        <SummaryCard
          icon={Gauge}
          label="AI Enrichment Concurrency"
          value={String(
            effectiveConfig.ai_enrichment_run_concurrency ??
              persistedConfig.ai_enrichment_run_concurrency ??
              "Unavailable",
          )}
          hint="AI enrichment workers"
        />
        <SummaryCard
          icon={Gauge}
          label="Companies Concurrency"
          value={String(
            effectiveConfig.company_ai_enrichment_run_concurrency ??
              persistedConfig.company_ai_enrichment_run_concurrency ??
              effectiveConfig.ai_enrichment_run_concurrency ??
              persistedConfig.ai_enrichment_run_concurrency ??
              "Unavailable",
          )}
          hint="Company description workers"
        />
        <SummaryCard
          icon={isAnyDegraded ? AlertTriangle : ShieldCheck}
          label="Runtime state"
          value={aggregateRuntimeState}
          hint={
            jobRuntimeStatus.degradation_reason ||
            companyRuntimeStatus.degradation_reason ||
            "Both profiles are ready to run"
          }
          tone={isAnyDegraded ? "warning" : "success"}
        />
      </section>

      <form className="ai-settings-shell" onSubmit={handleSubmit} noValidate>
        <section className="ai-settings-panel ai-settings-actions glass-panel">
          <div className="ai-settings-section-heading">
            <div>
              <h2>Edit profiles</h2>
              <p>
                Pick a provider card, update only the relevant fields, then save
                once to apply both profiles.
              </p>
            </div>
            <div className="ai-settings-edit-actions">
            <span role="status">{dirty ? 'Unsaved changes' : 'All changes saved'}</span>
            <button type="button" disabled={!dirty || saving || Boolean(testingProfile)} onClick={() => {
              setFormState(createFormState(settingsPayload));
              setSecretVisibility(createSecretVisibilityState());
              setFeedback({ tone: 'success', title: 'Changes discarded', lines: ['The saved configuration is restored.'] });
            }}>Discard changes</button>
            <button
              className="ai-settings-save-button"
              type="submit"
              disabled={saving || Boolean(testingProfile)}
            >
              <Save size={16} />
              <span>{saving ? "Saving..." : "Save settings"}</span>
            </button>
            </div>
          </div>
        </section>

        <ProfileSection
          profileKey="jobs"
          profileLabel={PROFILE_LABELS.jobs}
          formState={formState.jobs}
          settingsPayload={settingsPayload}
          saving={saving || Boolean(testingProfile)}
          testing={testingProfile === "jobs"}
          isSecretVisible={secretVisibility.jobs}
          toggleSecretVisibility={toggleSecretVisibility}
          updateProfileProvider={updateProfileProvider}
          updateProfileField={updateProfileField}
          onTestProfile={handleTestProfile}
        />

        <ProfileSection
          profileKey="companies"
          profileLabel={PROFILE_LABELS.companies}
          formState={formState.companies}
          settingsPayload={settingsPayload}
          saving={saving || Boolean(testingProfile)}
          testing={testingProfile === "companies"}
          isSecretVisible={secretVisibility.companies}
          toggleSecretVisibility={toggleSecretVisibility}
          updateProfileProvider={updateProfileProvider}
          updateProfileField={updateProfileField}
          onTestProfile={handleTestProfile}
        />

        <section id="settings-jev" tabIndex={-1} className="ai-settings-panel glass-panel">
          <div className="ai-settings-section-heading">
            <div>
              <h2>Jev System One</h2>
              <p>
                Configure native bounded decisions and the cumulative allowance
                used by future Jev runs. Saving does not call the provider.
              </p>
            </div>
          </div>

          <div className="ai-settings-form-grid">
            <label className="ai-settings-field">
              <span>Enable Jev</span>
              <input
                aria-label="Enable Jev"
                type="checkbox"
                checked={formState.jev.enabled}
                onChange={(event) =>
                  updateJevField("enabled", event.target.checked)
                }
                disabled={saving}
              />
            </label>
            <label className="ai-settings-field">
              <span>Jev endpoint</span>
              <input
                aria-label="Jev endpoint"
                type="url"
                value={formState.jev.endpoint}
                onChange={(event) =>
                  updateJevField("endpoint", event.target.value)
                }
                disabled={saving}
              />
            </label>
            <label className="ai-settings-field">
              <span>Jev model</span>
              <input
                aria-label="Jev model"
                value={formState.jev.model}
                onChange={(event) => updateJevField("model", event.target.value)}
                disabled={saving}
              />
            </label>
            <label className="ai-settings-field">
              <span>Jev API key</span>
              <input
                aria-label="Jev API key"
                type={secretVisibility.jev ? "text" : "password"}
                value={formState.jev.api_key}
                onChange={(event) =>
                  updateJevField("api_key", event.target.value)
                }
                autoComplete="new-password"
                disabled={saving}
              />
              <span className="ai-settings-field-hint">
                {settingsPayload?.jev?.api_key_preview || "No saved key"}
              </span>
              <button
                className="ai-settings-password-toggle"
                type="button"
                aria-label={`${secretVisibility.jev ? "Hide" : "Show"} Jev API key`}
                onClick={() => toggleSecretVisibility("jev")}
                disabled={saving}
              >
                {secretVisibility.jev ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </label>
            <label className="ai-settings-field">
              <span>Jev allowance (USD)</span>
              <input
                aria-label="Jev allowance"
                type="number"
                min="0"
                step="0.01"
                value={formState.jev.allowance_usd}
                onChange={(event) =>
                  updateJevField("allowance_usd", event.target.value)
                }
                disabled={saving}
              />
              <span className="ai-settings-field-hint">
                Remaining: USD {(
                  Number(settingsPayload?.jev?.remaining_microdollars || 0) /
                  1_000_000
                ).toFixed(2)}
              </span>
            </label>
          </div>

          <details>
            <summary>Advanced Jev controls</summary>
            <div className="ai-settings-form-grid">
              {[
                ["sample_limit", "Jev sample limit", 1, 10000],
                ["question_batch_limit", "Jev question batch limit", 1, 100],
                ["concurrency", "Jev concurrency", 1, 50],
                ["retry_limit", "Jev retry limit", 0, 10],
                ["timeout_seconds", "Jev timeout seconds", 1, 600],
                [
                  "input_microdollars_per_million_tokens",
                  "Jev input microdollars per million tokens",
                  1,
                  undefined,
                ],
                [
                  "output_microdollars_per_million_tokens",
                  "Jev output microdollars per million tokens",
                  1,
                  undefined,
                ],
                [
                  "max_request_reservation_microdollars",
                  "Jev maximum request reservation microdollars",
                  1,
                  undefined,
                ],
              ].map(([key, label, min, max]) => (
                <label className="ai-settings-field" key={key}>
                  <span>{label}</span>
                  <input
                    aria-label={label}
                    type="number"
                    min={min}
                    max={max}
                    value={formState.jev[key]}
                    onChange={(event) => updateJevField(key, event.target.value)}
                    disabled={saving}
                  />
                </label>
              ))}
              {[
                ["evidence_threshold", "Jev evidence threshold"],
                ["recommendation_threshold", "Jev recommendation threshold"],
              ].map(([key, label]) => (
                <label className="ai-settings-field" key={key}>
                  <span>{label}</span>
                  <input
                    aria-label={label}
                    type="number"
                    min="0"
                    max="1"
                    step="0.001"
                    value={formState.jev[key]}
                    onChange={(event) => updateJevField(key, event.target.value)}
                    disabled={saving}
                  />
                </label>
              ))}
            </div>
          </details>

          <div className="ai-settings-throughput-note">
            <div className="ai-settings-section-heading">
              <div>
                <h3>Suspected duplicate associations</h3>
                <p>
                  Jev may propose that two source listings describe the same vacancy.
                  It never merges, hides, deletes, or rewrites either source Job.
                </p>
              </div>
            </div>
            <div className="ai-settings-form-grid">
              <label className="ai-settings-field">
                <span>Enable duplicate evaluation</span>
                <input
                  aria-label="Enable Jev duplicate evaluation"
                  type="checkbox"
                  checked={formState.jev.duplicate_enabled}
                  onChange={(event) =>
                    updateJevField("duplicate_enabled", event.target.checked)
                  }
                  disabled={saving}
                />
              </label>
              <label className="ai-settings-field">
                <span>Candidate pairs per Job</span>
                <input
                  aria-label="Jev duplicate candidate limit"
                  type="number"
                  min="1"
                  max="10"
                  value={formState.jev.duplicate_candidate_limit}
                  onChange={(event) =>
                    updateJevField("duplicate_candidate_limit", event.target.value)
                  }
                  disabled={saving}
                />
              </label>
              <label className="ai-settings-field">
                <span>Recent Jobs scanned per evaluation</span>
                <input
                  aria-label="Jev duplicate corpus limit"
                  type="number"
                  min="2"
                  max="1000"
                  value={formState.jev.duplicate_corpus_limit}
                  onChange={(event) =>
                    updateJevField("duplicate_corpus_limit", event.target.value)
                  }
                  disabled={saving}
                />
              </label>
            </div>
          </div>

          <div className="ai-settings-throughput-note">
            <div className="ai-settings-section-heading">
              <div>
                <h3>Search relevance reranking</h3>
                <p>
                  Jev may reorder only an explicitly previewed lexical candidate
                  prefix. Filters, membership, totals, facets, paging, and CSV
                  export remain bound to the frozen search scope.
                </p>
              </div>
            </div>
            <div className="ai-settings-form-grid">
              <label className="ai-settings-field">
                <span>Enable search reranking</span>
                <input
                  aria-label="Enable Jev search reranking"
                  type="checkbox"
                  checked={formState.jev.search_rerank_enabled}
                  onChange={(event) =>
                    updateJevField("search_rerank_enabled", event.target.checked)
                  }
                  disabled={saving}
                />
              </label>
              <label className="ai-settings-field">
                <span>Maximum candidates per rerank</span>
                <input
                  aria-label="Jev search rerank candidate limit"
                  type="number"
                  min="1"
                  max="50"
                  value={formState.jev.search_rerank_candidate_limit}
                  onChange={(event) =>
                    updateJevField("search_rerank_candidate_limit", event.target.value)
                  }
                  disabled={saving}
                />
              </label>
            </div>
          </div>

          <div className="ai-settings-throughput-note">
            <div className="ai-settings-section-heading">
              <div>
                <h3>Repeated incident triage</h3>
                <p>
                  Jev may prioritize secret-safe clusters of crawl events. Advice
                  never changes severity, retries work, dismisses an incident, or
                  writes Crawl Job lifecycle state.
                </p>
              </div>
            </div>
            <div className="ai-settings-form-grid">
              <label className="ai-settings-field">
                <span>Enable incident triage</span>
                <input
                  aria-label="Enable Jev incident triage"
                  type="checkbox"
                  checked={formState.jev.incident_triage_enabled}
                  onChange={(event) =>
                    updateJevField("incident_triage_enabled", event.target.checked)
                  }
                  disabled={saving}
                />
              </label>
              <label className="ai-settings-field">
                <span>Maximum recent incident events</span>
                <input
                  aria-label="Jev incident triage event limit"
                  type="number"
                  min="1"
                  max="1000"
                  value={formState.jev.incident_triage_event_limit}
                  onChange={(event) =>
                    updateJevField("incident_triage_event_limit", event.target.value)
                  }
                  disabled={saving}
                />
              </label>
            </div>
          </div>

          <div className="ai-settings-throughput-note">
            <div className="ai-settings-section-heading">
              <div>
                <h3>Crawl content quality advisory</h3>
                <p>
                  Jev reviews structurally successful detail content only. It never
                  retries, repairs, resumes, cancels, or changes a Crawl Job.
                </p>
              </div>
            </div>
            <div className="ai-settings-form-grid">
              <label className="ai-settings-field">
                <span>Enable crawl quality advisory</span>
                <input
                  aria-label="Enable Jev crawl quality advisory"
                  type="checkbox"
                  checked={formState.jev.crawl_quality_enabled}
                  onChange={(event) =>
                    updateJevField("crawl_quality_enabled", event.target.checked)
                  }
                  disabled={saving}
                />
              </label>
              <label className="ai-settings-field">
                <span>Maximum listings per quality evaluation</span>
                <input
                  aria-label="Jev crawl quality batch limit"
                  type="number"
                  min="1"
                  max="100"
                  value={formState.jev.crawl_quality_batch_limit}
                  onChange={(event) =>
                    updateJevField("crawl_quality_batch_limit", event.target.value)
                  }
                  disabled={saving}
                />
              </label>
            </div>
          </div>

          <div className="ai-settings-throughput-note">
            <div className="ai-settings-section-heading">
              <div>
                <h3>Skill taxonomy maintenance</h3>
                <p>
                  A stronger model periodically reviews accumulated exceptions.
                  Existing mappings, aliases, generic terms and rejections may be
                  applied automatically above the saved threshold. New Skills and
                  hierarchy changes always wait for one aggregate approval.
                </p>
              </div>
            </div>
            <div className="ai-settings-form-grid">
              <label className="ai-settings-field">
                <span>Enable Skill maintenance</span>
                <input
                  aria-label="Enable Skill maintenance"
                  type="checkbox"
                  checked={formState.jev.maintenance_enabled}
                  onChange={(event) =>
                    updateJevField("maintenance_enabled", event.target.checked)
                  }
                  disabled={saving}
                />
              </label>
              <label className="ai-settings-field">
                <span>Maintenance model</span>
                <input
                  aria-label="Jev maintenance model"
                  value={formState.jev.maintenance_model}
                  onChange={(event) =>
                    updateJevField("maintenance_model", event.target.value)
                  }
                  disabled={saving}
                />
              </label>
              <label className="ai-settings-field">
                <span>Maintenance allowance (USD)</span>
                <input
                  aria-label="Jev maintenance allowance"
                  type="number"
                  min="0"
                  step="0.01"
                  value={formState.jev.maintenance_allowance_usd}
                  onChange={(event) =>
                    updateJevField(
                      "maintenance_allowance_usd",
                      event.target.value,
                    )
                  }
                  disabled={saving}
                />
                <span className="ai-settings-field-hint">
                  Remaining: USD {formatMicrodollars(
                    settingsPayload?.jev?.maintenance_remaining_microdollars,
                  )}
                </span>
              </label>
              {[
                ["maintenance_interval_days", "Jev maintenance interval days", 1, 3650],
                ["maintenance_min_candidates", "Jev maintenance minimum candidates", 1, 100000],
                ["maintenance_batch_size", "Jev maintenance batch size", 1, 10000],
              ].map(([key, label, min, max]) => (
                <label className="ai-settings-field" key={key}>
                  <span>{label}</span>
                  <input
                    aria-label={label}
                    type="number"
                    min={min}
                    max={max}
                    value={formState.jev[key]}
                    onChange={(event) => updateJevField(key, event.target.value)}
                    disabled={saving}
                  />
                </label>
              ))}
              <label className="ai-settings-field">
                <span>Jev maintenance automatic threshold</span>
                <input
                  aria-label="Jev maintenance threshold"
                  type="number"
                  min="0"
                  max="1"
                  step="0.001"
                  value={formState.jev.maintenance_threshold}
                  onChange={(event) =>
                    updateJevField("maintenance_threshold", event.target.value)
                  }
                  disabled={saving}
                />
              </label>
            </div>
          </div>

          <div className="ai-settings-throughput-note">
            <div className="ai-settings-section-heading">
              <div>
                <h3>Jev bounded runs</h3>
                <p>
                  The smoke test is one explicit paid request. Reading this page
                  never starts provider work.
                </p>
              </div>
              <button
                type="button"
                className="ai-settings-save-button"
                onClick={runJevSmokeTest}
                disabled={
                  Boolean(jevActionId) ||
                  !settingsPayload?.jev?.enabled ||
                  !settingsPayload?.jev?.has_api_key ||
                  !settingsPayload?.jev?.max_request_reservation_microdollars
                }
              >
                <FlaskConical size={16} />
                <span>
                  {jevActionId === "new"
                    ? "Starting Jev smoke test..."
                    : "Run one Jev smoke test"}
                </span>
              </button>
            </div>
            {jevRunError ? <p role="alert">{jevRunError}</p> : null}
            {jevRuns.length === 0 ? (
              <p>No Jev runs yet.</p>
            ) : (
              <div aria-label="Jev run history">
                {jevRuns.map((run) => {
                  const busy = jevActionId === run.id;
                  const tokenUsage = getJevRunTokenUsage(run);
                  return (
                    <article key={run.id} className="ai-settings-secret-meta">
                      <div>
                        <strong>{run.purpose}</strong>
                        <p>
                          {run.status} · {run.completed_items}/{run.total_items}
                          {tokenUsage ? ` · ${tokenUsage} tokens` : ""}
                        </p>
                        <small>
                          Frozen model: {run.settings_snapshot?.model || "unknown"}
                        </small>
                        <small>
                          Frozen endpoint: {run.settings_snapshot?.endpoint || "unknown"}
                        </small>
                        <small>
                          Allowance USD {formatMicrodollars(
                            settingsPayload?.jev?.allowance_microdollars,
                          )} · spent {formatMicrodollars(
                            settingsPayload?.jev?.spent_microdollars,
                          )} · reserved {formatMicrodollars(
                            settingsPayload?.jev?.reserved_microdollars,
                          )} · remaining {formatMicrodollars(
                            settingsPayload?.jev?.remaining_microdollars,
                          )}
                        </small>
                      </div>
                      <div>
                        {["pending", "running"].includes(run.status) ? (
                          <>
                            <button
                              type="button"
                              onClick={() =>
                                performJevRunAction(run.id, "execute-next")
                              }
                              disabled={busy}
                            >
                              Execute next
                            </button>
                            <button
                              type="button"
                              onClick={() => performJevRunAction(run.id, "stop")}
                              disabled={busy}
                            >
                              Stop
                            </button>
                          </>
                        ) : null}
                        {run.status === "cancelled" ? (
                          <button
                            type="button"
                            onClick={() => performJevRunAction(run.id, "resume")}
                            disabled={busy}
                          >
                            Resume
                          </button>
                        ) : null}
                        {run.status === "completed_with_failures" ? (
                          <button
                            type="button"
                            onClick={() =>
                              performJevRunAction(run.id, "retry-failed")
                            }
                            disabled={busy}
                          >
                            Retry failed
                          </button>
                        ) : null}
                      </div>
                    </article>
                  );
                })}
              </div>
            )}
          </div>
        </section>

        <section id="settings-throughput" tabIndex={-1} className="ai-settings-panel glass-panel">
          <div className="ai-settings-section-heading">
            <div>
              <h2>AI Enrichment Throughput</h2>
              <p>
                AI Enrichment and Companies can now use different concurrency
                limits.
              </p>
            </div>
          </div>

          <div className="ai-settings-form-grid">
            <label className="ai-settings-field">
              <span>AI Enrichment concurrency</span>
              <input
                aria-label="AI Enrichment concurrency"
                type="number"
                min="1"
                value={formState.ai_enrichment_run_concurrency}
                onChange={(event) =>
                  updateTopLevelField(
                    "ai_enrichment_run_concurrency",
                    event.target.value,
                  )
                }
                disabled={saving}
              />
            </label>
            <label className="ai-settings-field">
              <span>Skill Candidate 进入待确认列表的门槛（不同 Job 数）</span>
              <input
                aria-label="Skill automatic creation threshold"
                type="number"
                min="1"
                max="1000"
                value={formState.skill_auto_create_distinct_job_threshold}
                onChange={(event) =>
                  updateTopLevelField(
                    "skill_auto_create_distinct_job_threshold",
                    event.target.value,
                  )
                }
                disabled={saving}
              />
            </label>
            <label className="ai-settings-field">
              <span>Skill 推荐数量</span>
              <input
                aria-label="Skill recommendation count"
                type="number"
                min="1"
                max="20"
                value={formState.skill_candidate_recommendation_limit}
                onChange={(event) => updateTopLevelField("skill_candidate_recommendation_limit", event.target.value)}
                disabled={saving}
              />
            </label>
            <label className="ai-settings-field">
              <span>Job evidence 展示数量</span>
              <input
                aria-label="Skill evidence count"
                type="number"
                min="1"
                max="20"
                value={formState.skill_candidate_evidence_limit}
                onChange={(event) => updateTopLevelField("skill_candidate_evidence_limit", event.target.value)}
                disabled={saving}
              />
            </label>
            <label className="ai-settings-field">
              <span>Companies concurrency</span>
              <input
                aria-label="Companies concurrency"
                type="number"
                min="1"
                value={formState.company_ai_enrichment_run_concurrency}
                onChange={(event) =>
                  updateTopLevelField(
                    "company_ai_enrichment_run_concurrency",
                    event.target.value,
                  )
                }
                disabled={saving}
              />
            </label>
          </div>

          <div
            className={`ai-settings-throughput-note ${isAnyDegraded ? "warning" : ""}`}
          >
            <span>AI Enrichment effective value</span>
            <strong>
              {String(
                effectiveConfig.ai_enrichment_run_concurrency ??
                  persistedConfig.ai_enrichment_run_concurrency ??
                  "Unavailable",
              )}
            </strong>
            <span>Companies effective value</span>
            <strong>
              {String(
                effectiveConfig.company_ai_enrichment_run_concurrency ??
                  persistedConfig.company_ai_enrichment_run_concurrency ??
                  effectiveConfig.ai_enrichment_run_concurrency ??
                  persistedConfig.ai_enrichment_run_concurrency ??
                  "Unavailable",
              )}
            </strong>
            <p>
              AI Enrichment state: {getRuntimeStateLabel(jobRuntimeStatus)}.
              Companies state: {getRuntimeStateLabel(companyRuntimeStatus)}.
            </p>
            <p>
              Candidate 会在至少{' '}
              {String(
                effectiveConfig.skill_auto_create_distinct_job_threshold ?? 10,
              )}{' '}
              个不同 Job 出现后进入待确认列表；推荐数量和 evidence 数量可在上方调整。
            </p>
            {isAnyDegraded ? (
              <p className="ai-settings-warning-copy">
                One or more profiles still need a successful configuration test
                before runtime can start.
              </p>
            ) : null}
          </div>
        </section>
      </form>
    </section>
  );
}

export default function AISettingsPage({
  initialSection = "ai-runtime",
  onOpenCrawlTasks,
}) {
  const [route, setRoute] = useState(() => parseSettingsRoute(window.location.hash, initialSection));
  const activeSection = route.section;
  const [visited, setVisited] = useState(() => new Set([activeSection]));
  useEffect(() => {
    const change = () => {
      const next = parseSettingsRoute(window.location.hash, initialSection);
      setRoute(next);
      setVisited(current => new Set([...current, next.section]));
    };
    window.addEventListener('hashchange', change);
    return () => window.removeEventListener('hashchange', change);
  }, [initialSection]);
  function switchSection(section) {
    const next = { ...route, section, profile: null };
    setRoute(next);
    setVisited(current => new Set([...current, section]));
    window.location.hash = buildSettingsRoute(next);
  }

  return (
    <div className="settings-page-shell">
      <nav className="settings-section-nav glass-panel" aria-label="Settings sections">
        <button
          type="button"
          className={activeSection === "ai-runtime" ? "active" : ""}
          aria-current={activeSection === "ai-runtime" ? "page" : undefined}
          onClick={() => switchSection("ai-runtime")}
        >
          <BrainCircuit size={17} /> AI Runtime
        </button>
        <button
          type="button"
          className={activeSection === "scraper-pacing" ? "active" : ""}
          aria-current={activeSection === "scraper-pacing" ? "page" : undefined}
          onClick={() => switchSection("scraper-pacing")}
        >
          <Settings2 size={17} /> Scraper Pacing
        </button>
      </nav>
      {route.returnToAI && <a className="settings-return-link" href={route.returnRun ? `#ai?run=${encodeURIComponent(route.returnRun)}` : '#ai'}>Return to AI Enrichment</a>}
      <p className="ai-settings-draft-note">Switching Settings sections keeps your unsaved edits here. Save before leaving Settings or reloading.</p>
      {visited.has('ai-runtime') && <div hidden={activeSection !== 'ai-runtime'}><AIRuntimeSettings profileFocus={activeSection === 'ai-runtime' ? route.profile : null} /></div>}
      {visited.has('scraper-pacing') && <div hidden={activeSection !== 'scraper-pacing'}><ScraperPacingSettings onOpenCrawlTasks={onOpenCrawlTasks} /></div>}
    </div>
  );
}
