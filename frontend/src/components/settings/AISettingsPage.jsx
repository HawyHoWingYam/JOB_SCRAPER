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

function getSelectedProvider(payload) {
  return payload?.persisted_config?.llm_provider || payload?.effective_config?.llm_provider || 'mock';
}

function getProviderConfig(payload, provider) {
  return payload?.persisted_config?.[provider] || payload?.effective_config?.[provider] || {};
}

function getProviderInitialValue(payload, provider, key) {
  const persistedValue = payload?.persisted_config?.[provider]?.[key];
  if (persistedValue !== null && persistedValue !== undefined) {
    return String(persistedValue);
  }

  const effectiveValue = payload?.effective_config?.[provider]?.[key];
  if (effectiveValue !== null && effectiveValue !== undefined) {
    return String(effectiveValue);
  }

  return '';
}

function createFormState(payload) {
  return {
    llm_provider: getSelectedProvider(payload),
    ai_enrichment_run_concurrency: String(
      payload?.persisted_config?.ai_enrichment_run_concurrency ??
        payload?.effective_config?.ai_enrichment_run_concurrency ??
        '',
    ),
    providers: PROVIDER_OPTIONS.reduce((accumulator, provider) => {
      accumulator[provider] = {
        model: getProviderInitialValue(payload, provider, 'model'),
        base_url: getProviderInitialValue(payload, provider, 'base_url'),
        api_format: getProviderInitialValue(payload, provider, 'api_format'),
        api_key: '',
      };
      return accumulator;
    }, {}),
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

function buildRequestBody(formState) {
  const provider = formState.llm_provider;
  const body = {
    llm_provider: provider,
    ai_enrichment_run_concurrency: Number(formState.ai_enrichment_run_concurrency),
  };
  const providerValues = formState.providers[provider] || {};

  for (const field of PROVIDER_FIELDS[provider] || []) {
    body[field.requestKey] = providerValues[field.key] ?? '';
  }

  if (SECRET_REQUEST_KEYS[provider]) {
    body[SECRET_REQUEST_KEYS[provider]] = providerValues.api_key ?? '';
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

  function updateField(provider, key, value) {
    setFormState((currentState) => ({
      ...currentState,
      providers: {
        ...currentState.providers,
        [provider]: {
          ...currentState.providers[provider],
          [key]: value,
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
      setFeedback(
        payload?.runtime_status?.is_degraded
          ? {
              tone: 'warning',
              title: 'AI runtime settings saved',
              lines: [
                'Runtime is degraded.',
                payload.runtime_status.degradation_reason || 'The selected provider did not initialize cleanly.',
              ],
            }
          : {
              tone: 'success',
              title: 'AI runtime settings saved',
              lines: ['Runtime settings are active.'],
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

  const selectedProvider = formState?.llm_provider || getSelectedProvider(settingsPayload);
  const persistedConfig = settingsPayload?.persisted_config || {};
  const effectiveConfig = settingsPayload?.effective_config || {};
  const runtimeStatus = settingsPayload?.runtime_status || {};
  const providerConfig = getProviderConfig(settingsPayload, selectedProvider);
  const providerFields = PROVIDER_FIELDS[selectedProvider] || [];
  const providerValues = formState?.providers?.[selectedProvider] || {};
  const isDegraded = Boolean(runtimeStatus.is_degraded);
  const hasSavedApiKey = Boolean(providerConfig?.has_api_key);

  return (
    <section className="ai-settings-page">
      <header className="ai-settings-hero glass-panel">
        <div className="ai-settings-hero-copy">
          <p className="ai-settings-eyebrow">Settings</p>
          <h1>AI Runtime</h1>
          <p className="ai-settings-subtitle">
            Manage persisted provider settings, keep existing secrets when left blank, and verify the active runtime posture after each save.
          </p>
        </div>
        <div className="ai-settings-hero-badges">
          <span className="ai-settings-chip">{saving ? 'Saving…' : 'Editable'}</span>
          <span className={`ai-settings-chip ${isDegraded ? 'warning' : 'success'}`}>
            {isDegraded ? 'Degraded runtime' : 'Runtime ready'}
          </span>
        </div>
      </header>

      <FeedbackBanner feedback={feedback} />

      <section className="ai-settings-summary-grid">
        <SummaryCard
          icon={BrainCircuit}
          label="Configured provider"
          value={toProviderLabel(runtimeStatus.configured_provider || selectedProvider)}
          hint="Persisted selection"
        />
        <SummaryCard
          icon={Layers3}
          label="Active provider"
          value={toProviderLabel(runtimeStatus.active_provider || runtimeStatus.provider || selectedProvider)}
          hint={runtimeStatus.model || 'No model reported'}
          tone={isDegraded ? 'warning' : 'default'}
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
          icon={isDegraded ? AlertTriangle : ShieldCheck}
          label="Runtime state"
          value={isDegraded ? 'Degraded' : 'Healthy'}
          hint={runtimeStatus.degradation_reason || 'Provider initialized successfully'}
          tone={isDegraded ? 'warning' : 'success'}
        />
      </section>

      <form className="ai-settings-shell" onSubmit={handleSubmit} noValidate>
        <section className="ai-settings-panel glass-panel">
          <div className="ai-settings-section-heading">
            <div>
              <h2>AI Runtime</h2>
              <p>Provider selection, provider-specific settings, and secret preservation.</p>
            </div>
            <button className="ai-settings-save-button" type="submit" disabled={saving}>
              <Save size={16} />
              <span>{saving ? 'Saving…' : 'Save settings'}</span>
            </button>
          </div>

          <div className="ai-settings-form-grid">
            <label className="ai-settings-field">
              <span>Provider</span>
              <select
                aria-label="Provider"
                value={selectedProvider}
                onChange={(event) => updateTopLevelField('llm_provider', event.target.value)}
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
              <strong>{toProviderLabel(runtimeStatus.configured_provider || selectedProvider)}</strong>
            </div>
            <div>
              <span>Active provider</span>
              <strong>{toProviderLabel(runtimeStatus.active_provider || runtimeStatus.provider || selectedProvider)}</strong>
            </div>
            <div>
              <span>Model</span>
              <strong>{runtimeStatus.model || providerConfig?.model || 'Unavailable'}</strong>
            </div>
            <div>
              <span>Degraded state</span>
              <strong>{isDegraded ? 'Degraded' : 'Healthy'}</strong>
            </div>
          </div>

          <fieldset className="ai-settings-provider-group" aria-label={`${toProviderLabel(selectedProvider)} settings`}>
            <legend>{toProviderLabel(selectedProvider)} provider</legend>

            <div className="ai-settings-form-grid">
              {providerFields.map((field) => (
                <label className="ai-settings-field" key={field.key}>
                  <span>{field.label}</span>
                  <input
                    aria-label={field.label}
                    type="text"
                    value={providerValues[field.key] || ''}
                    onChange={(event) => updateField(selectedProvider, field.key, event.target.value)}
                    disabled={saving}
                  />
                </label>
              ))}

              {SECRET_REQUEST_KEYS[selectedProvider] ? (
                <label className="ai-settings-field ai-settings-secret-field">
                  <span>API key</span>
                  <input
                    aria-label="API key"
                    type="password"
                    value={providerValues.api_key || ''}
                    onChange={(event) => updateField(selectedProvider, 'api_key', event.target.value)}
                    placeholder={hasSavedApiKey ? 'Leave blank to keep existing key' : 'Enter API key'}
                    disabled={saving}
                  />
                  <div className="ai-settings-secret-meta">
                    <div className="ai-settings-secret-value">
                      <KeyRound size={16} />
                      <strong>{hasSavedApiKey ? 'API key saved' : 'No API key saved'}</strong>
                      {providerConfig?.api_key_preview ? <code>{providerConfig.api_key_preview}</code> : null}
                    </div>
                    <p className="ai-settings-field-hint">Leave blank to keep the existing key.</p>
                  </div>
                </label>
              ) : null}
            </div>
          </fieldset>
        </section>

        <section className="ai-settings-panel glass-panel">
          <div className="ai-settings-section-heading">
            <div>
              <h2>AI Enrichment Throughput</h2>
              <p>Concurrency is editable and the runtime summary below reflects the latest saved response.</p>
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

          <div className={`ai-settings-throughput-note ${isDegraded ? 'warning' : ''}`}>
            <span>Effective value</span>
            <strong>
              {String(
                effectiveConfig.ai_enrichment_run_concurrency ??
                  persistedConfig.ai_enrichment_run_concurrency ??
                  'Unavailable',
              )}
            </strong>
            <p>
              Configured provider: {toProviderLabel(runtimeStatus.configured_provider || selectedProvider)}. Active provider:{' '}
              {toProviderLabel(runtimeStatus.active_provider || runtimeStatus.provider || selectedProvider)}. Model:{' '}
              {runtimeStatus.model || 'Unavailable'}.
            </p>
            {isDegraded ? (
              <p className="ai-settings-warning-copy">
                Runtime is degraded. {runtimeStatus.degradation_reason || 'Check the provider configuration and try again.'}
              </p>
            ) : null}
          </div>
        </section>
      </form>
    </section>
  );
}
