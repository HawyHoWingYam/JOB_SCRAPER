import { apiPath } from "./base";
import { apiFetchJson } from "./client";

export const SCRAPER_PACING_SOURCES = [
  { value: "jobsdb", label: "JobsDB" },
  { value: "ctgoodjobs", label: "CTGoodJobs" },
  { value: "offertoday", label: "OfferToday" },
];

export const SCRAPER_PACING_DEFAULTS = {
  interval_min_seconds: 1,
  interval_max_seconds: 3,
  burst_size: 20,
  burst_pause_seconds: 30,
};

export function pacingSettingsPath(sourceSite = null) {
  const base = apiPath("/settings/scraper-pacing");
  return sourceSite ? `${base}/${encodeURIComponent(sourceSite)}` : base;
}

export function loadScraperPacingSettings(options) {
  return apiFetchJson(pacingSettingsPath(), options);
}

export function saveScraperPacingSettings(sourceSite, values, options = {}) {
  return apiFetchJson(pacingSettingsPath(sourceSite), {
    ...options,
    method: "PUT",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    body: JSON.stringify(values),
  });
}

export function resetScraperPacingSettings(sourceSite, options = {}) {
  return apiFetchJson(`${pacingSettingsPath(sourceSite)}/reset`, {
    ...options,
    method: "POST",
  });
}

export function formatPacingInterval(settings) {
  if (!settings) {
    return "Unavailable";
  }
  return `${settings.interval_min_seconds}-${settings.interval_max_seconds} seconds`;
}

export function formatPacingSummary(settings) {
  if (!settings) {
    return null;
  }
  return [
    `Random interval ${formatPacingInterval(settings)}`,
    `Burst ${settings.burst_size} attempts`,
    `Burst pause ${settings.burst_pause_seconds} seconds`,
  ];
}
