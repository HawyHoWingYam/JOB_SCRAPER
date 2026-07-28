import { normalizeLayerForSubmit } from './jobBrowserScopeUtils';


function optionLabel(options, id) {
  return options?.find((option) => option.id === id)?.label || id;
}


function optionLabels(options, ids) {
  return (ids || []).map((id) => optionLabel(options, id)).join(', ');
}


export function summarizeJobBrowserLayer(layer, facets = {}) {
  const normalized = normalizeLayerForSubmit(layer);
  const filters = normalized.structured_filters;
  const clauses = [];

  if (normalized.text_expression) clauses.push(`Text: ${normalized.text_expression}`);
  if (filters.source_site) {
    clauses.push(`Source: ${optionLabel(facets.sources, filters.source_site)}`);
  }
  if (filters.source_classification_ids.length > 0) {
    clauses.push(`Source Classification: ${optionLabels(
      facets.source_classifications,
      filters.source_classification_ids,
    )}`);
  }
  const employmentIds = filters.employment_type_codes.length > 0
    ? filters.employment_type_codes
    : filters.employment_type ? [filters.employment_type] : [];
  if (employmentIds.length > 0) {
    clauses.push(`Employment Type: ${optionLabels(facets.employment_types, employmentIds)}`);
  }
  const taxonomyIds = [
    ...filters.canonical_domain_ids,
    ...filters.canonical_category_ids,
    ...filters.canonical_subcategory_ids,
  ];
  if (taxonomyIds.length > 0) {
    clauses.push(`Canonical Job Taxonomy: ${optionLabels(
      facets.canonical_job_taxonomy,
      taxonomyIds,
    )}`);
  }
  if (filters.company_industry_node_ids.length > 0) {
    clauses.push(`Company Industry: ${optionLabels(
      facets.company_industries,
      filters.company_industry_node_ids,
    )}`);
  }
  if (filters.posted_date_from) clauses.push(`Posted from: ${filters.posted_date_from}`);
  if (filters.posted_date_to) clauses.push(`Posted to: ${filters.posted_date_to}`);
  if (filters.experience_years_from && filters.experience_years_to) {
    clauses.push(`Experience: ${filters.experience_years_from}–${filters.experience_years_to} years`);
  } else if (filters.experience_years_from) {
    clauses.push(`Experience: ${filters.experience_years_from}+ years`);
  } else if (filters.experience_years_to) {
    clauses.push(`Experience: up to ${filters.experience_years_to} years`);
  }
  if (filters.skill_ids.length > 0) {
    clauses.push(`Skills: ${filters.skill_ids.join(', ')}`);
  }
  if (filters.subcategory_ids.length > 0) {
    clauses.push(`Legacy subcategories: ${filters.subcategory_ids.join(', ')}`);
  }

  return clauses.length > 0 ? clauses : ['All jobs'];
}
