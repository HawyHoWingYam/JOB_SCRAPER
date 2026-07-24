import { describe, expect, it } from 'vitest';
import { BoardPayloadError, decodeBoard } from './boardDecoders';

const action = {
  action: 'view_task',
  enabled: true,
  reason_code: null,
};

function boardPayload(attention) {
  return {
    version: 2,
    selected_source: 'jobsdb',
    source_summaries: [],
    needs_attention: [attention],
    active_runs: [],
    upcoming: [],
    archived_automations: [],
    all_clear: false,
    refreshed_at: '2026-07-24T12:00:00Z',
  };
}

function attentionItem(overrides = {}) {
  return {
    item_id: 'run:failed-task:failed_run',
    kind: 'failed_run',
    priority: 40,
    source_site: 'jobsdb',
    code: 'RUN_FAILED',
    title: 'Run failed',
    summary: 'Synthetic failure',
    entity_kind: 'run',
    entity_id: 'failed-task',
    failure_event_sequence: 7,
    primary_action: action,
    secondary_actions: [],
    ...overrides,
  };
}

describe('decodeBoard failed-run attention revision', () => {
  it('decodes a positive failure event sequence', () => {
    const board = decodeBoard(boardPayload(attentionItem()));

    expect(board.needsAttention[0].failureEventSequence).toBe(7);
  });

  it('accepts a null sequence for attention that is not a failed run', () => {
    const board = decodeBoard(boardPayload(attentionItem({
      item_id: 'catalog:jobsdb:catalog_issue',
      kind: 'catalog_issue',
      entity_kind: 'catalog',
      entity_id: 'jobsdb',
      failure_event_sequence: null,
    })));

    expect(board.needsAttention[0].failureEventSequence).toBeNull();
  });

  it.each([0, -1, 1.5, '7'])(
    'rejects an invalid failure event sequence: %s',
    (failureEventSequence) => {
      expect(() => decodeBoard(boardPayload(attentionItem({
        failure_event_sequence: failureEventSequence,
      })))).toThrow(BoardPayloadError);
    },
  );
});
