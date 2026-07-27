export const OFFERTODAY_QUERY_TARGET_COUNT = 36;
export const OFFERTODAY_DEFAULT_PAGE_DEPTH = 100;
export const OFFERTODAY_DEFAULT_RUN_PAGE_CAP = 3600;
export const LISTING_TECHNICAL_RUN_PAGE_CAP = 1_000_000_000;

export function offerTodayEstimatedMaxPages(pageDepthValue) {
  const pageDepth = Number(pageDepthValue);
  if (!Number.isSafeInteger(pageDepth) || pageDepth < 1) return null;
  const estimate = OFFERTODAY_QUERY_TARGET_COUNT * pageDepth;
  if (!Number.isSafeInteger(estimate) || estimate > LISTING_TECHNICAL_RUN_PAGE_CAP) {
    return null;
  }
  return estimate;
}
