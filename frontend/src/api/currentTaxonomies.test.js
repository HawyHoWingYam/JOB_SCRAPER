import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fetchCurrentJobSkills, fetchCurrentSkillTree } from './currentTaxonomies';

function responseJson(payload) {
  return {
    ok: true,
    status: 200,
    json: async () => payload,
  };
}

describe('current taxonomy API', () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn().mockResolvedValue(responseJson({ nodes: [] }));
  });

  it('uses only ordinary current Skill routes', async () => {
    await fetchCurrentSkillTree();
    await fetchCurrentJobSkills('job/id');

    const paths = globalThis.fetch.mock.calls.map(([path]) => path);
    expect(paths).toEqual([
      '/api/job-intelligence/skills/tree',
      '/api/job-intelligence/jobs/job%2Fid/skills',
    ]);
    expect(paths.every((path) => !path.includes('revision'))).toBe(true);
    expect(paths.every((path) => !path.includes('governance'))).toBe(true);
    expect(paths.every((path) => !path.includes('review'))).toBe(true);
  });
});
