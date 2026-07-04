import { describe, expect, it } from 'vitest';

import { resolveDefaultMaxPages } from './maxPages';

describe('resolveDefaultMaxPages', () => {
    it('uses 50 for OfferToday and 3 for other sources', () => {
        expect(resolveDefaultMaxPages('offertoday')).toBe(50);
        expect(resolveDefaultMaxPages('jobsdb')).toBe(3);
        expect(resolveDefaultMaxPages('ctgoodjobs')).toBe(3);
        expect(resolveDefaultMaxPages(undefined)).toBe(3);
    });
});
