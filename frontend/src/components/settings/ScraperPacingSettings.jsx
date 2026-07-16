import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, RotateCcw, Save, SlidersHorizontal } from "lucide-react";
import {
  SCRAPER_PACING_SOURCES,
  loadScraperPacingSettings,
  resetScraperPacingSettings,
  saveScraperPacingSettings,
} from "../../api/scraperPacing";

const FIELD_DEFINITIONS = [
  {
    key: "interval_min_seconds",
    label: "Minimum interval",
    min: 0.1,
    max: 60,
    step: 0.1,
    help: "0.1-60 seconds",
  },
  {
    key: "interval_max_seconds",
    label: "Maximum interval",
    min: 0.1,
    max: 60,
    step: 0.1,
    help: "0.1-60 seconds",
  },
  {
    key: "burst_size",
    label: "Burst size",
    min: 1,
    max: 1000,
    step: 1,
    help: "1-1000 attempts",
  },
  {
    key: "burst_pause_seconds",
    label: "Burst pause",
    min: 0,
    max: 3600,
    step: 0.1,
    help: "0-3600 seconds",
  },
];

function toFormValues(settings) {
  return Object.fromEntries(
    FIELD_DEFINITIONS.map(({ key }) => [key, String(settings?.[key] ?? "")]),
  );
}

function createCardState(settings) {
  const form = toFormValues(settings);
  return {
    saved: form,
    form,
    pending: null,
    feedback: null,
    feedbackTone: null,
  };
}

function validateCard(form) {
  const errors = {};
  for (const field of FIELD_DEFINITIONS) {
    const value = Number(form[field.key]);
    if (form[field.key] === "" || !Number.isFinite(value)) {
      errors[field.key] = "Enter a number.";
    } else if (value < field.min || value > field.max) {
      errors[field.key] = `Use a value from ${field.min} to ${field.max}.`;
    } else if (field.key === "burst_size" && !Number.isInteger(value)) {
      errors[field.key] = "Use a whole number.";
    }
  }

  const minimum = Number(form.interval_min_seconds);
  const maximum = Number(form.interval_max_seconds);
  if (Number.isFinite(minimum) && Number.isFinite(maximum) && minimum > maximum) {
    errors.interval_max_seconds = "Maximum must be greater than or equal to minimum.";
  }
  return errors;
}

function isDirty(card) {
  return FIELD_DEFINITIONS.some(({ key }) => card.form[key] !== card.saved[key]);
}

function toRequestValues(form) {
  return {
    interval_min_seconds: Number(form.interval_min_seconds),
    interval_max_seconds: Number(form.interval_max_seconds),
    burst_size: Number(form.burst_size),
    burst_pause_seconds: Number(form.burst_pause_seconds),
  };
}

export default function ScraperPacingSettings({ onOpenCrawlTasks }) {
  const [cards, setCards] = useState({});
  const [activeDetailTaskCount, setActiveDetailTaskCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    loadScraperPacingSettings()
      .then((payload) => {
        if (cancelled) return;
        const itemsBySource = Object.fromEntries(
          (payload?.items || []).map((item) => [item.source_site, item]),
        );
        setCards(
          Object.fromEntries(
            SCRAPER_PACING_SOURCES.map(({ value }) => [
              value,
              createCardState(itemsBySource[value]),
            ]),
          ),
        );
        setActiveDetailTaskCount(Number(payload?.active_detail_task_count || 0));
      })
      .catch((error) => {
        if (!cancelled) setLoadError(error.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const validationBySource = useMemo(
    () =>
      Object.fromEntries(
        Object.entries(cards).map(([source, card]) => [source, validateCard(card.form)]),
      ),
    [cards],
  );

  function updateField(source, field, value) {
    setCards((current) => ({
      ...current,
      [source]: {
        ...current[source],
        form: { ...current[source].form, [field]: value },
        feedback: null,
        feedbackTone: null,
      },
    }));
  }

  async function runAction(source, action) {
    setCards((current) => ({
      ...current,
      [source]: { ...current[source], pending: action, feedback: null, feedbackTone: null },
    }));
    try {
      const response =
        action === "reset"
          ? await resetScraperPacingSettings(source)
          : await saveScraperPacingSettings(source, toRequestValues(cards[source].form));
      setCards((current) => ({
        ...current,
        [source]: {
          ...createCardState(response),
          feedback: action === "reset" ? "Defaults restored." : "Settings saved.",
          feedbackTone: "success",
        },
      }));
    } catch (error) {
      setCards((current) => ({
        ...current,
        [source]: {
          ...current[source],
          pending: null,
          feedback: error.message || "Request failed.",
          feedbackTone: "error",
        },
      }));
    }
  }

  if (loading) {
    return <div className="ai-settings-message glass-panel">Loading scraper pacing...</div>;
  }
  if (loadError) {
    return (
      <div className="ai-settings-message ai-settings-message-error glass-panel" role="alert">
        {loadError}
      </div>
    );
  }

  return (
    <div className="scraper-pacing-shell">
      <header className="ai-settings-hero glass-panel">
        <div className="ai-settings-hero-copy">
          <p className="ai-settings-eyebrow">Settings</p>
          <h1>Scraper Pacing</h1>
          <p className="ai-settings-subtitle">
            Tune manual Job Detail request spacing independently for each source.
            Listing crawls are unchanged.
          </p>
        </div>
        <span className="ai-settings-chip">
          <SlidersHorizontal size={15} /> New tasks only
        </span>
      </header>

      <section className="scraper-pacing-active-note glass-panel">
        <AlertTriangle size={18} aria-hidden="true" />
        <div>
          <strong>{activeDetailTaskCount} active manual detail task{activeDetailTaskCount === 1 ? "" : "s"}</strong>
          <p>Edits are allowed, but running and paused tasks keep the pacing snapshot they started with.</p>
        </div>
        <button type="button" onClick={onOpenCrawlTasks}>Open Crawl Tasks</button>
      </section>

      <section className="scraper-pacing-grid" aria-label="Source pacing settings">
        {SCRAPER_PACING_SOURCES.map(({ value: source, label }) => {
          const card = cards[source];
          const errors = validationBySource[source] || {};
          const invalid = Object.keys(errors).length > 0;
          const dirty = isDirty(card);
          const pending = Boolean(card.pending);
          const feedbackIsError = card.feedbackTone === "error";
          return (
            <article className="scraper-pacing-card glass-panel" key={source}>
              <div className="scraper-pacing-card-heading">
                <div>
                  <p className="ai-settings-eyebrow">Job Detail</p>
                  <h2>{label}</h2>
                </div>
                <span className={`scraper-pacing-state ${dirty ? "dirty" : "saved"}`}>
                  {pending ? `${card.pending === "reset" ? "Resetting" : "Saving"}...` : dirty ? "Unsaved" : "Saved"}
                </span>
              </div>

              <div className="scraper-pacing-fields">
                {FIELD_DEFINITIONS.map((field) => {
                  const errorId = `${source}-${field.key}-error`;
                  return (
                    <label className="ai-settings-field" key={field.key}>
                      <span>{field.label}</span>
                      <input
                        aria-label={`${label} ${field.label}`}
                        aria-invalid={Boolean(errors[field.key])}
                        aria-describedby={errors[field.key] ? errorId : undefined}
                        type="number"
                        min={field.min}
                        max={field.max}
                        step={field.step}
                        value={card.form[field.key]}
                        disabled={pending}
                        onChange={(event) => updateField(source, field.key, event.target.value)}
                      />
                      <small>{field.help}</small>
                      {errors[field.key] ? <small id={errorId} className="scraper-pacing-field-error">{errors[field.key]}</small> : null}
                    </label>
                  );
                })}
              </div>

              {card.feedback ? (
                <div className={`scraper-pacing-feedback ${feedbackIsError ? "error" : ""}`} role={feedbackIsError ? "alert" : "status"}>
                  {card.feedback}
                </div>
              ) : null}

              <div className="scraper-pacing-actions">
                <button type="button" onClick={() => runAction(source, "reset")} disabled={pending}>
                  <RotateCcw size={15} /> Reset defaults
                </button>
                <button type="button" className="ai-settings-save-button" onClick={() => runAction(source, "save")} disabled={pending || invalid || !dirty}>
                  <Save size={15} /> Save {label}
                </button>
              </div>
            </article>
          );
        })}
      </section>
    </div>
  );
}
