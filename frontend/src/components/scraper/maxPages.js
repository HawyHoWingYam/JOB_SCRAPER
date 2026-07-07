const DEFAULT_MAX_PAGES = 3;

export function resolveDefaultMaxPages(sourceSite, sources = {}) {
    const defaultMaxPages = Number.parseInt(`${sources?.[sourceSite]?.default_max_pages ?? ''}`, 10);

    return Number.isInteger(defaultMaxPages) && defaultMaxPages > 0
        ? defaultMaxPages
        : DEFAULT_MAX_PAGES;
}
