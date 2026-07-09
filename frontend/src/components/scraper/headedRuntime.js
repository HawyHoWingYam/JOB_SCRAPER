export function resolveHeadedRuntimeMode(sourceSite, sourceCatalog = {}) {
  const runtimeMode = sourceCatalog?.[sourceSite]?.headed_runtime_mode;

  if (typeof runtimeMode === 'string' && runtimeMode.trim()) {
    return runtimeMode;
  }

  return 'source_executor';
}

export function sourceRequiresExternalHeadedWorker(sourceSite, sourceCatalog = {}) {
  return resolveHeadedRuntimeMode(sourceSite, sourceCatalog) === 'external_worker';
}
