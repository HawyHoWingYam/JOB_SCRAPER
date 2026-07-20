export const SOURCE_CATALOG_SOURCES = ['jobsdb', 'ctgoodjobs', 'offertoday'];

export function parseSourceCatalogRoute(hash = window.location.hash) {
  const raw = String(hash || '').replace(/^#/, '');
  const [, query = ''] = raw.split('?', 2);
  const requested = new URLSearchParams(query).get('source')?.toLowerCase();
  return {
    source: SOURCE_CATALOG_SOURCES.includes(requested)
      ? requested
      : SOURCE_CATALOG_SOURCES[0],
  };
}

export function sourceCatalogHash(source) {
  const safeSource = SOURCE_CATALOG_SOURCES.includes(source)
    ? source
    : SOURCE_CATALOG_SOURCES[0];
  return `#source-catalogs?source=${encodeURIComponent(safeSource)}`;
}
