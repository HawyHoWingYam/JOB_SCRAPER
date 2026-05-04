import { describe, expect, it } from 'vitest';

import {
  appendLayerToScope,
  createEmptyJobBrowserLayer,
  createEmptyJobBrowserScope,
  hasPendingLayerChanges,
  normalizeLayerForSubmit,
  removeLayerFromScope,
  replaceScopeWithLayer,
} from './jobBrowserScopeUtils';

describe('jobBrowserScopeUtils', () => {
  it('creates an empty draft layer with nested structured filters', () => {
    expect(createEmptyJobBrowserLayer()).toEqual({
      client_id: 'draft',
      text_expression: '',
      structured_filters: {
        employment_type: '',
        subcategory_ids: [],
        industry: '',
        posted_date_from: '',
        posted_date_to: '',
        experience_years_from: '',
        experience_years_to: '',
      },
    });
  });

  it('normalizes a layer for submit without destroying exact and phrase syntax', () => {
    expect(
      normalizeLayerForSubmit({
        client_id: 'draft',
        text_expression: '  =ERP   "ERP system"  ',
        structured_filters: {
          industry: '  Healthcare  ',
          experience_years_from: '02',
          experience_years_to: '5',
        },
      }),
    ).toEqual({
      client_id: 'draft',
      text_expression: '=ERP   "ERP system"',
      structured_filters: {
        employment_type: '',
        subcategory_ids: [],
        industry: 'Healthcare',
        posted_date_from: '',
        posted_date_to: '',
        experience_years_from: '2',
        experience_years_to: '5',
      },
    });
  });

  it('replaces the scope with one normalized root layer', () => {
    expect(
      replaceScopeWithLayer(
        {
          layers: [{ client_id: 'old-root', text_expression: 'legacy', structured_filters: {} }],
        },
        {
          client_id: 'root',
          text_expression: 'erp',
          structured_filters: { industry: 'Healthcare' },
        },
      ),
    ).toEqual({
      layers: [
        {
          client_id: 'root',
          text_expression: 'erp',
          structured_filters: {
            employment_type: '',
            subcategory_ids: [],
            industry: 'Healthcare',
            posted_date_from: '',
            posted_date_to: '',
            experience_years_from: '',
            experience_years_to: '',
          },
        },
      ],
    });
  });

  it('appends a normalized refine layer to an existing scope', () => {
    expect(
      appendLayerToScope(
        {
          layers: [{ client_id: 'root', text_expression: 'erp', structured_filters: createEmptyJobBrowserLayer().structured_filters }],
        },
        {
          client_id: 'refine-1',
          text_expression: '"ERP system"',
          structured_filters: {},
        },
      ),
    ).toEqual({
      layers: [
        {
          client_id: 'root',
          text_expression: 'erp',
          structured_filters: createEmptyJobBrowserLayer().structured_filters,
        },
        {
          client_id: 'refine-1',
          text_expression: '"ERP system"',
          structured_filters: createEmptyJobBrowserLayer().structured_filters,
        },
      ],
    });
  });

  it('removes one layer by client id', () => {
    expect(
      removeLayerFromScope(
        {
          layers: [
            { client_id: 'root', text_expression: 'erp', structured_filters: createEmptyJobBrowserLayer().structured_filters },
            { client_id: 'refine-1', text_expression: '"ERP system"', structured_filters: createEmptyJobBrowserLayer().structured_filters },
          ],
        },
        'refine-1',
      ),
    ).toEqual({
      layers: [
        { client_id: 'root', text_expression: 'erp', structured_filters: createEmptyJobBrowserLayer().structured_filters },
      ],
    });
  });

  it('detects pending draft changes against the empty draft layer', () => {
    expect(
      hasPendingLayerChanges(
        createEmptyJobBrowserLayer(),
        {
          client_id: 'draft',
          text_expression: '=ERP',
          structured_filters: {},
        },
      ),
    ).toBe(true);
  });

  it('creates an empty scope by default', () => {
    expect(createEmptyJobBrowserScope()).toEqual({ layers: [] });
  });
});
