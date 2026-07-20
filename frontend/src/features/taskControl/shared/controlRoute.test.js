import { describe, expect, it } from 'vitest';
import { buildControlRoute, parseControlRoute } from './controlRoute';
import { formatControlDateTime } from './controlTime';

describe('Task Control routes and time', () => {
  it('parses and builds encoded feature-local routes while preserving board entry', () => {
    expect(parseControlRoute('#scheduler')).toEqual({
      kind: 'board',
      sourceSite: 'jobsdb',
    });
    expect(buildControlRoute({ kind: 'board' })).toBe('#scheduler');
    const hash = buildControlRoute({
      flow: 'automation', mode: 'edit', automationId: 'automation-1',
      sourceSite: 'jobsdb', draftId: 'draft-1',
    });
    expect(hash).toBe('#scheduler/automation/automation-1/edit?source=jobsdb&draft=draft-1');
    expect(parseControlRoute(hash)).toMatchObject({
      kind: 'wizard', flow: 'automation', mode: 'edit',
      automationId: 'automation-1', draftId: 'draft-1', sourceSite: 'jobsdb',
    });
    const scopedHash = buildControlRoute({
      flow: 'one_off', mode: 'create', sourceSite: 'jobsdb', draftId: 'draft-2', step: 'execution',
    });
    expect(parseControlRoute(scopedHash).step).toBe('execution');
    expect(parseControlRoute(`${scopedHash.replace('execution', 'unknown')}`).step).toBeNull();
    expect(parseControlRoute('#scheduler/automation/%20/edit').kind).toBe('invalid');
  });

  it('formats every instant with an explicit timezone', () => {
    const instant = '2026-07-21T00:00:00Z';
    expect(formatControlDateTime(instant, 'Asia/Hong_Kong')).not.toBe(
      formatControlDateTime(instant, 'America/New_York'),
    );
  });
});
