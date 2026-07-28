import { describe, expect, it } from 'vitest';

import {
  JOB_BROWSER_SESSION_KEY,
  readJobBrowserSession,
  writeJobBrowserSession,
} from './jobBrowserSessionStorage';


function memoryStorage() {
  const values = new Map();
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key),
  };
}


describe('Job Browser session restoration', () => {
  it('round-trips only a versioned normalized applied scope', () => {
    const storage = memoryStorage();
    const scope = {
      layers: [
        {
          client_id: ' root ',
          text_expression: '  platform engineer  ',
          structured_filters: {
            source_site: 'JobsDB',
            skill_ids: [' python ', ''],
            employment_type_codes: ['full_time'],
          },
        },
      ],
    };

    writeJobBrowserSession(storage, scope);

    expect(JSON.parse(storage.getItem(JOB_BROWSER_SESSION_KEY))).toEqual({
      version: 1,
      scope: expect.any(Object),
    });
    expect(readJobBrowserSession(storage)).toEqual({
      layers: [
        expect.objectContaining({
          client_id: ' root ',
          text_expression: 'platform engineer',
          structured_filters: expect.objectContaining({
            source_site: 'jobsdb',
            skill_ids: ['python'],
            employment_type_codes: ['full_time'],
          }),
        }),
      ],
    });
  });
});
