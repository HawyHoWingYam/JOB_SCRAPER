import { useEffect, useState } from 'react';
import {
  AlertTriangle,
  BrainCircuit,
  Gauge,
  KeyRound,
  Layers3,
  Save,
  ShieldCheck,
} from 'lucide-react';
import './AISettingsPage.css';

const API_URL = import.meta.env.VITE_API_URL || '';

const PROVIDER_OPTIONS = ['anthropic', 'gemini', 'custom', 'zhipu', 'mock'];
const PROFILE_LABELS = {
  jobs: 'AI Enrichment',
  companies: 'Companies',
};

const PROVIDER_LABELS = {
  anthropic: 'Anthropic',
  claude: 'Claude',
  gemini: 'Gemini',
  custom: 'Custom',
  zhipu: 'Zhipu',
  mock: 'Mock',
};

const PROVIDER_FIELDS = {
  anthropic: [
    { key: 'model', label: 'Model', requestKey: 'anthropic_model' },
    { key: 'base_url', label: 'Base URL', requestKey: 'anthropic_base_url' },
  ],
  gemini: [{ key: 'model', label: 'Model', requestKey: 'gemini_model' }],
  custom: [
    { key: 'model', label: 'Model', requestKey: 'custom_model' },
    { key: 'base_url', label: 'Base URL', requestKey: 'custom_base_url' },
    { key: 'api_format', label: 'API Format', requestKey: 'custom_api_format' },
  ],
  zhipu: [],
  mock: [],
};

const SECRET_REQUEST_KEYS = {
  anthropic: 'anthropic_api_key',
  gemini: 'gemini_api_key',
  custom: 'custom_api_key',
  zhipu: 'zhipu_api_key',
};

function toProviderLabel(provider) {
  return PROVIDER_LABELS[provider] || String(provider || 'Unknown');
}

function getProfileProviderKey(profileKey) {
  return profileKey === 'companies' ? 'company_llm_provider' : 'llm_provider';
}

function getScopedProviderConfigKey(profileKey, provider) {
  return profileKey === 'companies' ? `company_${provider}` : provider;
}

function getSelectedProvider(payload, profileKey) {
  const providerKey = getProfileProviderKey(profileKey);
  return (
    payload?.persisted_config?.[providerKey] ||
    payload?.effective_config?.[providerKey] ||
    (profileKey === 'companies'
      ? getSelectedProvider(payload, 'jobs')
      : 'mock')
  );
}

function getProviderConfig(payload, profileKey, provider) {
  const configKey = getScopedProviderConfigKey(profileKey, provider);
  return payload?.persisted_config?.[configKey] || payload?.effective_config?.[configKey] || {};
}

function getProfileSecretKey(profileKey, provider) {
  if (profileKey === 'companies') {
    return `company_${provider}_api_key`;
  }

  return SECRET_REQUEST_KEYS[provider];
}

function getProviderInitialValue(payload, profileKey, provider, key) {
  const persistedValue = payload?.persisted_config?.[getScopedProviderConfigKey(profileKey, provider)]?.[key];
  if (persistedValue !== null && persistedValue !== undefined) {
    return String(persistedValue);
  }

  const effectiveValue = payload?.effective_config?.[getScopedProviderConfigKey(profileKey, provider)]?.[key];
  if (effectiveValue !== null && effectiveValue !== undefined) {
    return String(effectiveValue);
  }

  return '';
}

function createProfileState(payload, profileKey) {
  return {
    llm_provider: getSelectedProvider(payload, profileKey),
    providers: PROVIDER_OPTIONS.reduce((accumulator, provider) => {
      accumulator[provider] = {
        model: getProviderInitialValue(payload, profileKey, provider, 'model'),
        base_url: getProviderInitialValue(payload, profileKey, provider, 'base_url'),
        api_format: getProviderInitialValue(payload, profileKey, provider, 'api_format'),
        api_key: '',
      };
      return accumulator;
    }, {}),
  };
}

function createFormState(payload) {
  return {
    jobs: createProfileState(payload, 'jobs'),
    companies: createProfileState(payload, 'companies'),
    ai_enrichment_run_concurrency: String(
      payload?.persisted_config?.ai_enrichment_run_concurrency ??
        payload?.effective_config?.ai_enrichment_run_concurrency ??
        '',
    ),
  };
}

function formatValidationErrors(detail) {
  if (!Array.isArray(detail)) {
    return ['Failed to save AI runtime settings.'];
  }

  return detail.map((item) => {
    const location = Array.isArray(item?.loc) ? item.loc.slice(1).join('.') : 'settings';
    const message = item?.msg || 'Invalid value';
    return `${location}: ${message}`;
  });
}

function appendSecret(body, requestKey, value) {
  const nextValue = value ?? '';
  if (!(requestKey in body) || nextValue) {
    body[requestKey] = nextValue;
  }
}

function buildRequestBody(formState) {
  const body = {
    llm_provider: formState.jobs.llm_provider,
    company_llm_provider: formState.companies.llm_provider,
    ai_enrichment_run_concurrency: Number(formState.ai_enrichment_run_concurrency),
  };

  for (const [profileKey, prefix] of [['jobs', ''], ['companies', 'company_']]) {
    const profile = formState[profileKey];
    const provider = profile.llm_provider;
    const providerValues = profile.providers[provider] || {};

    for (const field of PROVIDER_FIELDS[provider] || []) {
      body[`${prefix}${field.requestKey}`] = providerValues[field.key] ?? '';
    }

    const secretRequestKey = getProfileSecretKey(profileKey, provider);
    if (secretRequestKey) {
      appendSecret(body, secretRequestKey, providerValues.api_key);
    }
  }

  return body;
}

function SummaryCard({ icon: Icon, label, value, hint, tone = 'default' }) {
  return (
    <article className={`ai-settings-summary-card glass-panel tone-${tone}`}>
      <div className="ai-settings-summary-icon">
        <Icon size={18} />
      </div>
      <div className="ai-settings-summary-copy">
        <span>{label}</span>
        <strong>{value}</strong>
        {hint ? <small>{hint}</small> : null}
      </div>
    </article>
  );
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
        {feedback.tone === 'error' || feedback.tone === 'warning' ? <AlertTriangle size={18} /> : <ShieldCheck size={18} />}
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
  runtimeStatus,
  saving,
  updateProfileProvider,
  updateProfileField,
}) {
  const selectedProvider = formState?.llm_provider || getSelectedProvider(settingsPayload, profileKey);
  const providerFields = PROVIDER_FIELDS[selectedProvider] || [];
  const providerValues = formState?.providers?.[selectedProvider] || {};
  const providerConfig = getProviderConfig(settingsPayload, profileKey, selectedProvider);
  const hasSavedApiKey = Boolean(providerConfig?.has_api_key);
  const isDegraded = Boolean(runtimeStatus?.is_degraded);

  return (
    <section className="ai-settings-panel glass-panel">
      <div className="ai-settings-section-heading">
        <div>
          <h2>{profileLabel} Profile</h2>
          <p>{profileLabel} can use a different provider and model than the other AI workflow.</p>
        </div>
      </div>

      <div className="ai-settings-form-grid">
        <label className="ai-settings-field">
          <span>{profileLabel} Provider</span>
          <select
            aria-label={`${profileLabel} provider`}
            value={selectedProvider}
            onChange={(event) => updateProfileProvider(profileKey, event.target.value)}
            disabled={saving}
          >
            {PROVIDER_OPTIONS.map((provider) => (
              <option key={provider} value={provider}>
                {toProviderLabel(provider)}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="ai-settings-runtime-meta">
        <div>
          <span>Configured provider</span>
          <strong>{toProviderLabel(runtimeStatus?.configured_provider || selectedProvider)}</strong>
        </div>
        <div>
          <span>Active provider</span>
          <strong>{toProviderLabel(runtimeStatus?.active_provider || runtimeStatus?.provider || selectedProvider)}</strong>
        </div>
        <div>
          <span>Model</span>
          <strong>{runtimeStatus?.model || providerConfig?.model || 'Unavailable'}</strong>
        </div>
        <div>
          <span>Degraded state</span>
          <strong>{isDegraded ? 'Degraded' : 'Healthy'}</strong>
        </div>
      </div>

      <fieldset className="ai-settings-provider-group" aria-label={`${profileLabel} ${toProviderLabel(selectedProvider)} settings`}>
        <legend>{profileLabel} {toProviderLabel(selectedProvider)} settings</legend>

        <div className="ai-settings-form-grid">
          {providerFields.map((field) => (
            <label className="ai-settings-field" key={field.key}>
              <span>{field.label}</span>
              <input
                aria-label={`${profileLabel} ${field.label}`}
                type="text"
                value={providerValues[field.key] || ''}
                onChange={(event) => updateProfileField(profileKey, selectedProvider, field.key, event.target.value)}
                disabled={saving}
              />
            </label>
          ))}

          {SECRET_REQUEST_KEYS[selectedProvider] ? (
            <label className="ai-settings-field ai-settings-secret-field">
              <span>API key</span>
              <input
                aria-label={`${profileLabel} API key`}
                type="password"
                value={providerValues.api_key || ''}
                onChange={(event) => updateProfileField(profileKey, selectedProvider, 'api_key', event.target.value)}
                placeholder={hasSavedApiKey ? 'Leave blank to keep existing key' : 'Enter API key'}
                disabled={saving}
              />
              <div className="ai-settings-secret-meta">
                <div className="ai-settings-secret-value">
                  <KeyRound size={16} />
                  <strong>{hasSavedApiKey ? 'API key saved' : 'No API key saved'}</strong>
                  {providerConfig?.api_key_preview ? <code>{providerConfig.api_key_preview}</code> : null}
                </div>
                <p className="ai-settings-field-hint">
                  {profileKey === 'companies'
                    ? 'Saved only for the Companies profile.'
                    : 'Saved only for the AI Enrichment profile.'}
                </p>
              </div>
            </label>
          ) : null}
        </div>
      </fieldset>
    </section>
  );
}

export default function AISettingsPage() {
  const [settingsPayload, setSettingsPayload] = useState(null);
  const [formState, setFormState] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [feedback, setFeedback] = useState(null);

  useEffect(() => {
    let cancelled = false;

    async function loadSettings() {
      setLoading(true);
      setError(null);

      try {
        const response = await fetch(`${API_URL}/api/v1/settings/ai`);
        if (!response.ok) {
          throw new Error(`Failed to load AI settings (${response.status})`);
        }

        const payload = await response.json();
        if (!cancelled) {
          setSettingsPayload(payload);
          setFormState(createFormState(payload));
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

  async function handleSubmit(event) {
    event.preventDefault();
    setSaving(true);
    setFeedback(null);

    try {
      const response = await fetch(`${API_URL}/api/v1/settings/ai`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(buildRequestBody(formState)),
      });

      const payload = await response.json();

      if (!response.ok) {
        if (response.status === 422) {
          setFeedback({
            tone: 'error',
            title: 'Validation failed',
            lines: formatValidationErrors(payload?.detail),
          });
          return;
        }

        throw new Error(`Failed to save AI settings (${response.status})`);
      }

      setSettingsPayload(payload);
      setFormState(createFormState(payload));

      const degradedLines = [];
      if (payload?.runtime_status?.is_degraded) {
        degradedLines.push(
          `AI Enrichment runtime is degraded. ${payload.runtime_status.degradation_reason || 'The selected provider did not initialize cleanly.'}`,
        );
      }
      if (payload?.company_runtime_status?.is_degraded) {
        degradedLines.push(
          `Companies runtime is degraded. ${payload.company_runtime_status.degradation_reason || 'The selected provider did not initialize cleanly.'}`,
        );
      }

      setFeedback(
        degradedLines.length
          ? {
              tone: 'warning',
              title: 'AI runtime settings saved',
              lines: degradedLines,
            }
          : {
              tone: 'success',
              title: 'AI runtime settings saved',
              lines: ['Runtime settings are active for both profiles.'],
            },
      );
    } catch (err) {
      setFeedback({
        tone: 'error',
        title: 'Save failed',
        lines: [err.message],
      });
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <section className="ai-settings-page">
        <div className="ai-settings-hero glass-panel">
          <p className="ai-settings-eyebrow">Settings</p>
          <h1>AI Runtime</h1>
          <p className="ai-settings-subtitle">Loading runtime configuration...</p>
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
        <div className="ai-settings-message ai-settings-message-error glass-panel" role="alert">
          {error}
        </div>
      </section>
    );
  }

  const persistedConfig = settingsPayload?.persisted_config || {};
  const effectiveConfig = settingsPayload?.effective_config || {};
  const jobRuntimeStatus = settingsPayload?.runtime_status || {};
  const companyRuntimeStatus = settingsPayload?.company_runtime_status || {};
  const isAnyDegraded = Boolean(jobRuntimeStatus.is_degraded || companyRuntimeStatus.is_degraded);

  return (
    <section className="ai-settings-page">
      <header className="ai-settings-hero glass-panel">
        <div className="ai-settings-hero-copy">
          <p className="ai-settings-eyebrow">Settings</p>
          <h1>AI Runtime</h1>
          <p className="ai-settings-subtitle">
            Manage separate provider profiles for AI enrichment and company descriptions while reusing saved provider credentials.
          </p>
        </div>
        <div className="ai-settings-hero-badges">
          <span className="ai-settings-chip">{saving ? 'Saving…' : 'Editable'}</span>
          <span className={`ai-settings-chip ${isAnyDegraded ? 'warning' : 'success'}`}>
            {isAnyDegraded ? 'Degraded runtime' : 'Runtime ready'}
          </span>
        </div>
      </header>

      <FeedbackBanner feedback={feedback} />

      <section className="ai-settings-summary-grid">
        <SummaryCard
          icon={BrainCircuit}
          label="AI Enrichment"
          value={toProviderLabel(jobRuntimeStatus.configured_provider || formState?.jobs?.llm_provider)}
          hint={jobRuntimeStatus.model || 'No model reported'}
          tone={jobRuntimeStatus.is_degraded ? 'warning' : 'default'}
        />
        <SummaryCard
          icon={Layers3}
          label="Companies"
          value={toProviderLabel(companyRuntimeStatus.configured_provider || formState?.companies?.llm_provider)}
          hint={companyRuntimeStatus.model || 'No model reported'}
          tone={companyRuntimeStatus.is_degraded ? 'warning' : 'default'}
        />
        <SummaryCard
          icon={Gauge}
          label="Concurrency"
          value={String(
            effectiveConfig.ai_enrichment_run_concurrency ??
              persistedConfig.ai_enrichment_run_concurrency ??
              'Unavailable',
          )}
          hint="AI enrichment workers"
        />
        <SummaryCard
          icon={isAnyDegraded ? AlertTriangle : ShieldCheck}
          label="Runtime state"
          value={isAnyDegraded ? 'Degraded' : 'Healthy'}
          hint={
            jobRuntimeStatus.degradation_reason ||
            companyRuntimeStatus.degradation_reason ||
            'Both profiles initialized successfully'
          }
          tone={isAnyDegraded ? 'warning' : 'success'}
        />
      </section>

      <form className="ai-settings-shell" onSubmit={handleSubmit} noValidate>
        <section className="ai-settings-panel glass-panel">
          <div className="ai-settings-section-heading">
            <div>
              <h2>Model Profiles</h2>
              <p>Save separate providers and models for AI enrichment and company descriptions.</p>
            </div>
            <button className="ai-settings-save-button" type="submit" disabled={saving}>
              <Save size={16} />
              <span>{saving ? 'Saving…' : 'Save settings'}</span>
            </button>
          </div>
        </section>

        <ProfileSection
          profileKey="jobs"
          profileLabel={PROFILE_LABELS.jobs}
          formState={formState.jobs}
          settingsPayload={settingsPayload}
          runtimeStatus={jobRuntimeStatus}
          saving={saving}
          updateProfileProvider={updateProfileProvider}
          updateProfileField={updateProfileField}
        />

        <ProfileSection
          profileKey="companies"
          profileLabel={PROFILE_LABELS.companies}
          formState={formState.companies}
          settingsPayload={settingsPayload}
          runtimeStatus={companyRuntimeStatus}
          saving={saving}
          updateProfileProvider={updateProfileProvider}
          updateProfileField={updateProfileField}
        />

        <section className="ai-settings-panel glass-panel">
          <div className="ai-settings-section-heading">
            <div>
              <h2>AI Enrichment Throughput</h2>
              <p>Concurrency is still global for job enrichment workers.</p>
            </div>
          </div>

          <div className="ai-settings-form-grid">
            <label className="ai-settings-field">
              <span>Concurrency</span>
              <input
                aria-label="Concurrency"
                type="number"
                min="1"
                value={formState.ai_enrichment_run_concurrency}
                onChange={(event) => updateTopLevelField('ai_enrichment_run_concurrency', event.target.value)}
                disabled={saving}
              />
            </label>
          </div>

          <div className={`ai-settings-throughput-note ${isAnyDegraded ? 'warning' : ''}`}>
            <span>Effective value</span>
            <strong>
              {String(
                effectiveConfig.ai_enrichment_run_concurrency ??
                  persistedConfig.ai_enrichment_run_concurrency ??
                  'Unavailable',
              )}
            </strong>
            <p>
              AI Enrichment active provider: {toProviderLabel(jobRuntimeStatus.active_provider || jobRuntimeStatus.provider || formState.jobs.llm_provider)}.
              Companies active provider: {toProviderLabel(companyRuntimeStatus.active_provider || companyRuntimeStatus.provider || formState.companies.llm_provider)}.
            </p>
            {isAnyDegraded ? (
              <p className="ai-settings-warning-copy">
                One or more profiles are degraded. Check the saved provider configuration and try again.
              </p>
            ) : null}
          </div>
        </section>
      </form>
    </section>
  );
}
