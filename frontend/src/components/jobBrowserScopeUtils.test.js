import { describe, expect, it } from 'vitest';

import {
  createEmptyJobBrowserLayer,
  replaceLayerInScope,
} from './jobBrowserScopeUtils';


describe('Job Browser scope transitions', () => {
  it('edits one applied layer in place without losing hidden governed fields', () => {
    const root = createEmptyJobBrowserLayer('root');
    root.structured_filters.skill_ids = ['python'];
    root.structured_filters.technology_ids = ['react'];
    root.structured_filters.salary_min = '30000';
    const refinement = createEmptyJobBrowserLayer('refine-1');
    refinement.structured_filters.employment_type_codes = ['full_time'];
    const edited = {
      ...root,
      text_expression: 'platform engineer',
      structured_filters: {
        ...root.structured_filters,
        source_classification_ids: ['jobsdb:technology.backend'],
      },
    };

    const scope = replaceLayerInScope(
      { layers: [root, refinement] },
      'root',
      edited,
    );

    expect(scope.layers.map((layer) => layer.client_id)).toEqual([
      'root',
      'refine-1',
    ]);
    expect(scope.layers[0]).toEqual(expect.objectContaining({
      text_expression: 'platform engineer',
      structured_filters: expect.objectContaining({
        skill_ids: ['python'],
        technology_ids: ['react'],
        salary_min: '30000',
        source_classification_ids: ['jobsdb:technology.backend'],
      }),
    }));
    expect(scope.layers[1].structured_filters.employment_type_codes).toEqual([
      'full_time',
    ]);
  });
});
