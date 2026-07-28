import { describe, expect, it } from 'vitest';

import { toggleHierarchySelection } from './filterFacetUtils';


const OPTIONS = [
  { id: 'technology', parent_id: null },
  { id: 'software', parent_id: 'technology' },
  { id: 'backend', parent_id: 'software' },
  { id: 'frontend', parent_id: 'software' },
];


describe('hierarchical facet selection', () => {
  it('keeps only the selected ancestor and removes redundant descendants', () => {
    expect(toggleHierarchySelection(
      OPTIONS,
      ['backend', 'frontend'],
      'software',
      true,
    )).toEqual(['software']);

    expect(toggleHierarchySelection(
      OPTIONS,
      ['software'],
      'backend',
      true,
    )).toEqual(['software']);

    expect(toggleHierarchySelection(
      OPTIONS,
      ['software'],
      'software',
      false,
    )).toEqual([]);
  });
});
