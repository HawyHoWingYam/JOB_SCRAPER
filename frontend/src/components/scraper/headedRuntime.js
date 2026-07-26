export function resolveHeadedRuntimeMode(sourceSite, sourceSites = {}) {
  const runtimeMode = sourceSites?.[sourceSite]?.headed_runtime_mode;

  if (typeof runtimeMode === 'string' && runtimeMode.trim()) {
    return runtimeMode;
  }

  return 'source_executor';
}

export function sourceRequiresExternalHeadedWorker(sourceSite, sourceSites = {}) {
  return resolveHeadedRuntimeMode(sourceSite, sourceSites) === 'external_worker';
}
