import { createElement, useEffect, useState } from "react";
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
import { apiPath } from "../../api/base";
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
  };
}

function createSecretVisibilityState() {
  return {
    jobs: false,
    companies: false,
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
  if (!feedback) {
    return null;
  }

  return (
    <div
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
    <section className="ai-settings-panel glass-panel">
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

function AIRuntimeSettings() {
  const [settingsPayload, setSettingsPayload] = useState(null);
  const [formState, setFormState] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testingProfile, setTestingProfile] = useState(null);
  const [error, setError] = useState(null);
  const [feedback, setFeedback] = useState(null);
  const [secretVisibility, setSecretVisibility] = useState(
    createSecretVisibilityState,
  );

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
  }, []);

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

  function toggleSecretVisibility(profileKey) {
    setSecretVisibility((currentState) => ({
      ...currentState,
      [profileKey]: !currentState[profileKey],
    }));
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
            lines: formatValidationErrors(payload?.detail),
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
        lines: [err.message],
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

      setFeedback(buildProfileTestFeedback(profileKey, payload));
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
            {saving ? "Saving..." : "Editable"}
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
            <button
              className="ai-settings-save-button"
              type="submit"
              disabled={saving}
            >
              <Save size={16} />
              <span>{saving ? "Saving..." : "Save settings"}</span>
            </button>
          </div>
        </section>

        <ProfileSection
          profileKey="jobs"
          profileLabel={PROFILE_LABELS.jobs}
          formState={formState.jobs}
          settingsPayload={settingsPayload}
          saving={saving}
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
          saving={saving}
          testing={testingProfile === "companies"}
          isSecretVisible={secretVisibility.companies}
          toggleSecretVisibility={toggleSecretVisibility}
          updateProfileProvider={updateProfileProvider}
          updateProfileField={updateProfileField}
          onTestProfile={handleTestProfile}
        />

        <section className="ai-settings-panel glass-panel">
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
  const [activeSection, setActiveSection] = useState(initialSection);

  useEffect(() => {
    setActiveSection(initialSection);
  }, [initialSection]);

  return (
    <div className="settings-page-shell">
      <nav className="settings-section-nav glass-panel" aria-label="Settings sections">
        <button
          type="button"
          className={activeSection === "ai-runtime" ? "active" : ""}
          aria-current={activeSection === "ai-runtime" ? "page" : undefined}
          onClick={() => setActiveSection("ai-runtime")}
        >
          <BrainCircuit size={17} /> AI Runtime
        </button>
        <button
          type="button"
          className={activeSection === "scraper-pacing" ? "active" : ""}
          aria-current={activeSection === "scraper-pacing" ? "page" : undefined}
          onClick={() => setActiveSection("scraper-pacing")}
        >
          <Settings2 size={17} /> Scraper Pacing
        </button>
      </nav>
      {activeSection === "scraper-pacing" ? (
        <ScraperPacingSettings onOpenCrawlTasks={onOpenCrawlTasks} />
      ) : (
        <AIRuntimeSettings />
      )}
    </div>
  );
}
