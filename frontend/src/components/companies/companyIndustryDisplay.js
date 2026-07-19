export function formatCompanyIndustryNode(node) {
  const label = node?.labels?.en || 'Unknown Company Industry';
  return node?.code ? `${node.code} · ${label}` : label;
}

export function formatCompanyIndustryBreadcrumb(breadcrumb) {
  if (!Array.isArray(breadcrumb) || breadcrumb.length === 0) {
    return 'Unknown Company Industry';
  }

  return breadcrumb.map(formatCompanyIndustryNode).join(' / ');
}

export function getCompanyIndustryDisplay(company) {
  const availability = company?.company_industry_availability;
  if (availability?.available === false) {
    return {
      state: 'unavailable',
      assignments: [],
      primary: null,
      additionalCount: 0,
      summary: 'Company Industry: Unavailable',
      unavailableCode: availability.unavailable_code || 'UNKNOWN',
    };
  }

  const assignments = Array.isArray(company?.company_industries?.assignments)
    ? company.company_industries.assignments
    : [];
  const primary = assignments.find((assignment) => assignment?.is_primary) || null;

  if (primary) {
    const additionalCount = assignments.length - 1;
    return {
      state: 'assigned',
      assignments,
      primary,
      additionalCount,
      summary: `Primary · ${formatCompanyIndustryBreadcrumb(primary.breadcrumb)}${
        additionalCount > 0 ? ` +${additionalCount}` : ''
      }`,
      unavailableCode: null,
    };
  }

  if (assignments.length > 0) {
    return {
      state: 'assigned_without_primary',
      assignments,
      primary: null,
      additionalCount: assignments.length,
      summary: `${assignments.length} governed Company ${
        assignments.length === 1 ? 'Industry' : 'Industries'
      } · no Primary`,
      unavailableCode: null,
    };
  }

  return {
    state: 'unassigned',
    assignments: [],
    primary: null,
    additionalCount: 0,
    summary: 'Company Industry: Unassigned',
    unavailableCode: null,
  };
}
