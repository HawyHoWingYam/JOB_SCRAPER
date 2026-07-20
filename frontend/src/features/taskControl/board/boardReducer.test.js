import { describe, expect, it } from 'vitest';
import { boardReducer, createBoardState } from './boardReducer';

describe('boardReducer', () => {
  it('suppresses late responses and preserves prior good data on refresh failure', () => {
    const value = { selectedSource: 'jobsdb' };
    let state = createBoardState('jobsdb');
    state = boardReducer(state, { type: 'loadStarted', version: 2 });
    state = boardReducer(state, { type: 'loadSucceeded', version: 2, value });
    state = boardReducer(state, { type: 'loadStarted', version: 3 });
    expect(boardReducer(state, { type: 'loadSucceeded', version: 2, value: {} })).toBe(state);
    const failed = boardReducer(state, { type: 'loadFailed', version: 3, error: { message: 'offline' } });
    expect(failed.board.value).toBe(value);
    expect(failed.board.status).toBe('stale');
  });
});
