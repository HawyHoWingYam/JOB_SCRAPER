const EMPTY_QUERY = {
  search_query: '',
  source_site: '',
  source_classification_ids: [],
  employment_type: '',
  employment_type_codes: [],
  subcategory_ids: [],
  canonical_subcategory_ids: [],
  canonical_category_ids: [],
  canonical_domain_ids: [],
  industry: '',
  company_industry_node_ids: [],
  posted_date_from: '',
  posted_date_to: '',
  experience_years_from: '',
  experience_years_to: '',
};

const SUPPORTED_SOURCE_SITES = new Set(['jobsdb', 'ctgoodjobs', 'offertoday']);

function normalizeValue(value) {
  return typeof value === 'string' ? value.trim() : '';
}

function normalizeSourceSite(value) {
  const normalized = normalizeValue(value).toLowerCase();
  return SUPPORTED_SOURCE_SITES.has(normalized) ? normalized : '';
}

function getRawNumericString(value) {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return `${value}`;
  }
  return typeof value === 'string' ? value.trim() : '';
}

function isNonNegativeIntegerString(value) {
  return /^\d+$/.test(value);
}

function normalizeNumericString(value) {
  const rawValue = getRawNumericString(value);
  if (!rawValue) {
    return '';
  }

  if (isNonNegativeIntegerString(rawValue)) {
    return `${Number.parseInt(rawValue, 10)}`;
  }

  return rawValue;
}

function normalizeIdArray(value) {
  if (Array.isArray(value)) {
    return value
      .map((item) => normalizeValue(item))
      .filter(Boolean);
  }

  if (typeof value === 'string') {
    const normalized = normalizeValue(value);
    return normalized ? [normalized] : [];
  }

  return [];
}

function startOfToday(referenceDate = new Date()) {
  return new Date(referenceDate.getFullYear(), referenceDate.getMonth(), referenceDate.getDate());
}

export function formatDateInputValue(date) {
  const year = date.getFullYear();
  const month = `${date.getMonth() + 1}`.padStart(2, '0');
  const day = `${date.getDate()}`.padStart(2, '0');
  return `${year}-${month}-${day}`;
}

export function createEmptyJobBrowserQuery() {
  return { ...EMPTY_QUERY };
}

export function normalizeDraftKeyword(value) {
  return normalizeValue(value).replace(/[,\s]+/g, ' ').trim();
}

export function normalizeQueryForSubmit(query) {
  return {
    ...createEmptyJobBrowserQuery(),
    ...query,
    search_query: normalizeDraftKeyword(query?.search_query || ''),
    source_site: normalizeSourceSite(query?.source_site),
    source_classification_ids: normalizeIdArray(
      query?.source_classification_ids,
    ),
    employment_type: normalizeValue(query?.employment_type),
    employment_type_codes: normalizeIdArray(query?.employment_type_codes),
    subcategory_ids: normalizeIdArray(query?.subcategory_ids),
    canonical_subcategory_ids: normalizeIdArray(
      query?.canonical_subcategory_ids,
    ),
    canonical_category_ids: normalizeIdArray(query?.canonical_category_ids),
    canonical_domain_ids: normalizeIdArray(query?.canonical_domain_ids),
    industry: normalizeValue(query?.industry),
    company_industry_node_ids: normalizeIdArray(
      query?.company_industry_node_ids,
    ),
    posted_date_from: normalizeValue(query?.posted_date_from),
    posted_date_to: normalizeValue(query?.posted_date_to),
    experience_years_from: normalizeNumericString(query?.experience_years_from),
    experience_years_to: normalizeNumericString(query?.experience_years_to),
  };
}

export function queriesAreEqual(left, right) {
  const normalizedLeft = normalizeQueryForSubmit(left || {});
  const normalizedRight = normalizeQueryForSubmit(right || {});

  return Object.keys(EMPTY_QUERY).every((key) => {
    if (Array.isArray(normalizedLeft[key]) || Array.isArray(normalizedRight[key])) {
      return JSON.stringify(normalizedLeft[key] || []) === JSON.stringify(normalizedRight[key] || []);
    }
    return normalizedLeft[key] === normalizedRight[key];
  });
}

export function countPendingQueryChanges(appliedQuery, draftQuery) {
  const applied = normalizeQueryForSubmit(appliedQuery || {});
  const draft = normalizeQueryForSubmit(draftQuery || {});
  let count = 0;

  if (applied.search_query !== draft.search_query) {
    count += 1;
  }
  if (applied.source_site !== draft.source_site) {
    count += 1;
  }
  if (
    JSON.stringify(applied.source_classification_ids) !==
    JSON.stringify(draft.source_classification_ids)
  ) {
    count += 1;
  }
  if (applied.employment_type !== draft.employment_type) {
    count += 1;
  }
  if (
    JSON.stringify(applied.employment_type_codes) !==
    JSON.stringify(draft.employment_type_codes)
  ) {
    count += 1;
  }
  if (JSON.stringify(applied.subcategory_ids) !== JSON.stringify(draft.subcategory_ids)) {
    count += 1;
  }
  if (
    JSON.stringify(applied.canonical_subcategory_ids) !==
      JSON.stringify(draft.canonical_subcategory_ids) ||
    JSON.stringify(applied.canonical_category_ids) !==
      JSON.stringify(draft.canonical_category_ids) ||
    JSON.stringify(applied.canonical_domain_ids) !==
      JSON.stringify(draft.canonical_domain_ids)
  ) {
    count += 1;
  }
  if (applied.industry !== draft.industry) {
    count += 1;
  }
  if (
    JSON.stringify(applied.company_industry_node_ids) !==
    JSON.stringify(draft.company_industry_node_ids)
  ) {
    count += 1;
  }
  if (
    applied.posted_date_from !== draft.posted_date_from ||
    applied.posted_date_to !== draft.posted_date_to
  ) {
    count += 1;
  }

  if (
    applied.experience_years_from !== draft.experience_years_from ||
    applied.experience_years_to !== draft.experience_years_to
  ) {
    // Treat the experience range as one logical change, similar to the posting window.
    count += 1;
  }

  return count;
}

export function getDatePresetForQuery(query) {
  const normalized = normalizeQueryForSubmit(query || {});
  const today = startOfToday();
  const todayValue = formatDateInputValue(today);
  const last7 = new Date(today);
  last7.setDate(today.getDate() - 6);
  const last30 = new Date(today);
  last30.setDate(today.getDate() - 29);
  const monthStart = new Date(today.getFullYear(), today.getMonth(), 1);

  if (!normalized.posted_date_from && !normalized.posted_date_to) {
    return 'any_time';
  }

  if (
    normalized.posted_date_from === todayValue &&
    normalized.posted_date_to === todayValue
  ) {
    return 'today';
  }

  if (
    normalized.posted_date_from === formatDateInputValue(last7) &&
    normalized.posted_date_to === todayValue
  ) {
    return 'last_7_days';
  }

  if (
    normalized.posted_date_from === formatDateInputValue(last30) &&
    normalized.posted_date_to === todayValue
  ) {
    return 'last_30_days';
  }

  if (
    normalized.posted_date_from === formatDateInputValue(monthStart) &&
    normalized.posted_date_to === todayValue
  ) {
    return 'this_month';
  }

  return 'custom';
}

export function getDatePresetRange(preset, referenceDate = new Date()) {
  const today = startOfToday(referenceDate);

  if (preset === 'any_time') {
    return {
      posted_date_from: '',
      posted_date_to: '',
    };
  }

  if (preset === 'today') {
    const value = formatDateInputValue(today);
    return {
      posted_date_from: value,
      posted_date_to: value,
    };
  }

  if (preset === 'last_7_days') {
    const start = new Date(today);
    start.setDate(today.getDate() - 6);
    return {
      posted_date_from: formatDateInputValue(start),
      posted_date_to: formatDateInputValue(today),
    };
  }

  if (preset === 'last_30_days') {
    const start = new Date(today);
    start.setDate(today.getDate() - 29);
    return {
      posted_date_from: formatDateInputValue(start),
      posted_date_to: formatDateInputValue(today),
    };
  }

  if (preset === 'this_month') {
    const monthStart = new Date(today.getFullYear(), today.getMonth(), 1);
    return {
      posted_date_from: formatDateInputValue(monthStart),
      posted_date_to: formatDateInputValue(today),
    };
  }

  return {
    posted_date_from: '',
    posted_date_to: '',
  };
}

export function getDateValidationError(query) {
  const normalized = normalizeQueryForSubmit(query || {});

  if (
    normalized.posted_date_from &&
    normalized.posted_date_to &&
    normalized.posted_date_from > normalized.posted_date_to
  ) {
    return 'Date from must be on or before date to.';
  }

  if (
    (normalized.experience_years_from && !isNonNegativeIntegerString(normalized.experience_years_from)) ||
    (normalized.experience_years_to && !isNonNegativeIntegerString(normalized.experience_years_to))
  ) {
    return 'Experience filters must use whole numbers greater than or equal to 0.';
  }

  if (normalized.experience_years_from && normalized.experience_years_to) {
    const fromYears = Number(normalized.experience_years_from);
    const toYears = Number(normalized.experience_years_to);

    if (Number.isFinite(fromYears) && Number.isFinite(toYears) && fromYears > toYears) {
      return 'Experience from must be on or before experience to.';
    }
  }

  return '';
}
