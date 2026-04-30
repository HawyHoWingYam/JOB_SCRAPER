import { createEmptyJobBrowserQuery, normalizeQueryForSubmit } from './jobBrowserQueryUtils';

function createEmptyStructuredFilters() {
  const filters = createEmptyJobBrowserQuery();
  delete filters.search_query;
  return filters;
}

function normalizeTextExpression(value) {
  return typeof value === 'string' ? value.trim() : '';
}

function normalizeStructuredFilters(filters) {
  const normalized = normalizeQueryForSubmit({
    ...createEmptyStructuredFilters(),
    ...(filters || {}),
  });
  const structuredFilters = { ...normalized };
  delete structuredFilters.search_query;
  return structuredFilters;
}

export function createEmptyJobBrowserLayer(clientId = 'draft') {
  return {
    client_id: clientId,
    text_expression: '',
    structured_filters: createEmptyStructuredFilters(),
  };
}

export function createEmptyJobBrowserScope() {
  return { layers: [] };
}

export function normalizeLayerForSubmit(layer) {
  return {
    client_id: layer?.client_id || 'draft',
    text_expression: normalizeTextExpression(layer?.text_expression),
    structured_filters: normalizeStructuredFilters(layer?.structured_filters),
  };
}

export function replaceScopeWithLayer(_scope, layer) {
  return {
    layers: [normalizeLayerForSubmit(layer)],
  };
}

export function appendLayerToScope(scope, layer) {
  return {
    layers: [...(scope?.layers || []).map(normalizeLayerForSubmit), normalizeLayerForSubmit(layer)],
  };
}

export function removeLayerFromScope(scope, clientId) {
  return {
    layers: (scope?.layers || [])
      .map(normalizeLayerForSubmit)
      .filter((layer) => layer.client_id !== clientId),
  };
}

export function hasPendingLayerChanges(appliedLayer, draftLayer) {
  return JSON.stringify(normalizeLayerForSubmit(appliedLayer)) !== JSON.stringify(normalizeLayerForSubmit(draftLayer));
}
