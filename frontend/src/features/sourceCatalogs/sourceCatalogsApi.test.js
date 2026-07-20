import { describe, expect, it } from 'vitest';
import {
  decodeCatalogSummaries,
  SourceCatalogPayloadError,
} from './sourceCatalogsApi';
import { parseSourceCatalogRoute } from './sourceCatalogsRoute';

describe('Source Catalog boundaries', () => {
  it('parses supported source hashes and falls back safely', () => {
    expect(parseSourceCatalogRoute('#source-catalogs?source=offertoday').source).toBe(
      'offertoday',
    );
    expect(parseSourceCatalogRoute('#source-catalogs?source=unknown').source).toBe(
      'jobsdb',
    );
  });

  it('rejects malformed summary payloads at the API boundary', () => {
    expect(() =>
      decodeCatalogSummaries({ sources: [{ source_site: 'jobsdb' }] }),
    ).toThrow(SourceCatalogPayloadError);
  });
});
