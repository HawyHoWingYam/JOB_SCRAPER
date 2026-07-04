const DEFAULT_MAX_PAGES = 3;

const DEFAULT_MAX_PAGES_BY_SOURCE = {
    offertoday: 50,
};

export function resolveDefaultMaxPages(sourceSite) {
    return DEFAULT_MAX_PAGES_BY_SOURCE[sourceSite] ?? DEFAULT_MAX_PAGES;
}
