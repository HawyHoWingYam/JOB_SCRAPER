const DEFAULT_TIMEOUT_MS = 180000;
const DEFAULT_BASE_URL = process.env.LIVE_SMOKE_BASE_URL || 'http://127.0.0.1:5173';

const SCENARIO_DEFINITIONS = {
  jobsdb: {
    listing: {
      crawlMode: 'headed',
      maxPages: 1,
      detailLimit: 1,
      skipExisting: true,
      preferredCategoryLabels: ['Engineering', 'Information Technology'],
    },
    detail: {
      crawlMode: 'headed',
      maxPages: 1,
      detailLimit: 1,
      skipExisting: true,
      preferredCategoryLabels: ['Engineering', 'Information Technology'],
    },
  },
  ctgoodjobs: {
    listing: {
      crawlMode: 'headed',
      maxPages: 1,
      detailLimit: 1,
      skipExisting: true,
      preferredCategoryLabels: ['Information & Communication Technology', 'Information Technology'],
    },
    detail: {
      crawlMode: 'headed',
      maxPages: 1,
      detailLimit: 1,
      skipExisting: true,
      preferredCategoryLabels: ['Information & Communication Technology', 'Information Technology'],
    },
  },
  offertoday: {
    listing: {
      crawlMode: 'headless',
      maxPages: 1,
      detailLimit: 1,
      skipExisting: true,
      leaveCategoriesBlank: true,
      preferredCategoryLabels: [],
    },
    detail: {
      crawlMode: 'headless',
      maxPages: 1,
      detailLimit: 1,
      skipExisting: true,
      leaveCategoriesBlank: true,
      preferredCategoryLabels: [],
    },
  },
};

export const LIVE_SCENARIOS = Object.freeze(SCENARIO_DEFINITIONS);

export function buildScenario({
  source,
  phase,
  baseUrl = DEFAULT_BASE_URL,
  artifactsDir,
  allowManualRecovery = false,
  timeoutMs = DEFAULT_TIMEOUT_MS,
} = {}) {
  const sourceDefinition = SCENARIO_DEFINITIONS[source];
  if (!sourceDefinition) {
    throw new Error(`Unsupported live smoke source: ${source}`);
  }

  const phaseDefinition = sourceDefinition[phase];
  if (!phaseDefinition) {
    throw new Error(`Unsupported live smoke phase for ${source}: ${phase}`);
  }

  return {
    source,
    phase,
    baseUrl,
    artifactsDir,
    allowManualRecovery,
    timeoutMs,
    ...phaseDefinition,
  };
}

export function buildScenarioMatrix({
  baseUrl = DEFAULT_BASE_URL,
  artifactsDir,
  allowManualRecovery = false,
  timeoutMs = DEFAULT_TIMEOUT_MS,
} = {}) {
  return Object.entries(SCENARIO_DEFINITIONS).flatMap(([source, phases]) =>
    Object.keys(phases).map((phase) =>
      buildScenario({
        source,
        phase,
        baseUrl,
        artifactsDir,
        allowManualRecovery,
        timeoutMs,
      })
    )
  );
}
