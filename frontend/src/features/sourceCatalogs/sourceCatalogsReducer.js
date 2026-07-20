const resource = (value = null) => ({ status: 'idle', value, error: null });

export function createSourceCatalogState(source) {
  return {
    source,
    requestVersion: 0,
    summaries: resource([]),
    published: resource(),
    candidate: resource(),
    validation: resource([]),
    impactReview: resource(),
    history: resource({ revisions: [], publications: [] }),
    mutation: { kind: null, status: 'idle', error: null },
    feedback: null,
    dialog: null,
  };
}

function updateResource(state, key, update, version) {
  if (version !== undefined && version !== state.requestVersion) return state;
  return { ...state, [key]: { ...state[key], ...update } };
}

export function sourceCatalogsReducer(state, action) {
  switch (action.type) {
    case 'sourceChanged':
      return {
        ...createSourceCatalogState(action.source),
        summaries: state.summaries,
        requestVersion: state.requestVersion + 1,
      };
    case 'refreshRequested':
      return {
        ...state,
        requestVersion: state.requestVersion + 1,
        impactReview: resource(),
      };
    case 'resourceStarted':
      return updateResource(
        state,
        action.resource,
        { status: 'loading', error: null },
        action.version,
      );
    case 'resourceSucceeded':
      return updateResource(
        state,
        action.resource,
        { status: 'success', value: action.value, error: null },
        action.version,
      );
    case 'resourceFailed':
      return updateResource(
        state,
        action.resource,
        {
          status: state[action.resource].value == null ? 'error' : 'stale',
          error: action.error,
        },
        action.version,
      );
    case 'mutationStarted':
      return {
        ...state,
        mutation: { kind: action.kind, status: 'loading', error: null },
        feedback: null,
      };
    case 'mutationFailed':
      return {
        ...state,
        mutation: { kind: action.kind, status: 'error', error: action.error },
      };
    case 'mutationSucceeded':
      return {
        ...state,
        mutation: { kind: action.kind, status: 'success', error: null },
        feedback: action.message,
      };
    case 'reviewSucceeded':
      return {
        ...state,
        impactReview: { status: 'success', value: action.value, error: null },
        mutation: { kind: action.kind, status: 'success', error: null },
      };
    case 'dialogOpened':
      return { ...state, dialog: action.dialog };
    case 'dialogClosed':
      return { ...state, dialog: null };
    default:
      return state;
  }
}
