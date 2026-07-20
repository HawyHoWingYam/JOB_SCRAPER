export function createBoardState(sourceSite) {
  return {
    sourceSite,
    board: { status: 'idle', value: null, error: null, requestVersion: 0, stale: false },
    expanded: new Set(),
    showArchived: false,
    mutation: { status: 'idle', entityId: null, kind: null, error: null },
    dialog: null,
    deleteReview: null,
    notice: null,
  };
}

export function boardReducer(state, action) {
  switch (action.type) {
    case 'sourceChanged':
      return createBoardState(action.sourceSite);
    case 'loadStarted':
      return { ...state, board: { ...state.board, status: state.board.value ? 'refreshing' : 'loading', error: null, requestVersion: action.version, stale: false } };
    case 'loadSucceeded':
      if (action.version !== state.board.requestVersion) return state;
      return { ...state, board: { status: 'success', value: action.value, error: null, requestVersion: action.version, stale: false } };
    case 'loadFailed':
      if (action.version !== state.board.requestVersion) return state;
      return { ...state, board: { ...state.board, status: state.board.value ? 'stale' : 'error', error: action.error, stale: Boolean(state.board.value) } };
    case 'expandedToggled': {
      const expanded = new Set(state.expanded);
      if (expanded.has(action.id)) expanded.delete(action.id); else expanded.add(action.id);
      return { ...state, expanded };
    }
    case 'archivedToggled':
      return { ...state, showArchived: !state.showArchived };
    case 'mutationStarted':
      if (state.mutation.status === 'loading') return state;
      return { ...state, mutation: { status: 'loading', entityId: action.entityId, kind: action.kind, error: null } };
    case 'mutationSucceeded':
      return { ...state, mutation: { status: 'success', entityId: action.entityId, kind: action.kind, error: null }, dialog: null, deleteReview: null, notice: action.notice || null };
    case 'mutationFailed':
      return { ...state, mutation: { ...state.mutation, status: 'error', error: action.error } };
    case 'dialogOpened':
      return { ...state, dialog: action.dialog, deleteReview: action.deleteReview || null, mutation: { status: 'idle', entityId: null, kind: null, error: null } };
    case 'dialogClosed':
      return { ...state, dialog: null, deleteReview: null, mutation: { status: 'idle', entityId: null, kind: null, error: null } };
    default:
      return state;
  }
}
