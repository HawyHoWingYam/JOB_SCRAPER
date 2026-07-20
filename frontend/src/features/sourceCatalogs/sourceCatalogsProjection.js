export const DIFF_CATEGORIES = [
  ['added', 'Added'],
  ['renamed', 'Renamed'],
  ['moved', 'Moved'],
  ['removed', 'Removed'],
  ['alias_changed', 'Alias changed'],
  ['capabilities_changed', 'Capability changed'],
  ['query_semantics_changed', 'Query semantics changed'],
];

const EXECUTION_AFFECTING = new Set([
  'added',
  'removed',
  'moved',
  'capabilities_changed',
  'query_semantics_changed',
]);

export function projectCandidateDiff(candidate, published) {
  if (!candidate) return [];
  const nodes = new Map([
    ...(published?.catalog?.nodes || []),
    ...(candidate.catalog?.nodes || []),
  ].map((node) => [node.nodeKey, node]));

  return DIFF_CATEGORIES.flatMap(([key, label]) =>
    (candidate.diff[key] || []).map((change, index) => {
      const node = nodes.get(change.node_key);
      const nativePath = node?.nativePath?.length
        ? node.nativePath.join(' / ')
        : change.classification_id || change.node_key || 'Unknown Source node';
      return {
        id: `${key}:${change.node_key || change.classification_id || index}`,
        category: key,
        categoryLabel: label,
        executionAffecting: EXECUTION_AFFECTING.has(key),
        nativePath,
        classificationId: change.classification_id || node?.classificationId || null,
        change,
        canonicalMatch:
          node?.sourceMetadata?.clean_match ||
          node?.sourceMetadata?.canonical_clean_match ||
          null,
      };
    }),
  );
}

export function impactRows(review) {
  return (review?.impact?.automations || []).map((row) => {
    const impact = row.impact || {};
    const scope = impact.authored_scope || {};
    const rules = scope.rules || [];
    const scopeLabel =
      scope.mode === 'all'
        ? 'All'
        : rules.map((rule) => `${rule.kind}: ${rule.classification_id}`).join(', ');
    const beforeWorkload = impact.before_listing_workload;
    const afterWorkload = impact.after_listing_workload;
    return {
      id: row.automation_id,
      revision: row.expected_revision,
      lifecycle: row.lifecycle_state,
      phase: row.crawl_phase,
      scopeLabel,
      beforeCount: impact.before?.query_target_count ?? '—',
      afterCount: impact.after?.query_target_count ?? '—',
      capEffect:
        afterWorkload == null
          ? 'Unavailable'
          : `${afterWorkload.estimated_max_pages}/${afterWorkload.run_page_cap} pages${
              beforeWorkload
                ? ` (was ${beforeWorkload.estimated_max_pages})`
                : ''
            }`,
      status: row.status,
      reasons: impact.reason_codes || [],
    };
  });
}

export function isPublishable(candidate) {
  return candidate?.state === 'validated';
}
