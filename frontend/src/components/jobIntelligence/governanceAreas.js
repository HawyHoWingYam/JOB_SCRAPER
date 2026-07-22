import {
  decideCanonicalReviewItem,
  decideCompanyIndustryReviewItem,
  decideSkillCandidate,
  fetchCanonicalAudit,
  fetchCanonicalReviewItems,
  fetchCanonicalReviewItem,
  fetchCanonicalTree,
  fetchCompanyIndustryAudit,
  fetchCompanyIndustryMappings,
  fetchCompanyIndustryReviewItems,
  fetchCompanyIndustryReviewItem,
  fetchCompanyIndustryTree,
  fetchSkillAudit,
  fetchSkillCandidate,
  fetchSkillCandidates,
  fetchSkillRecommendations,
  fetchSkillTree,
} from '../../api/jobIntelligence';

function canonicalOptions(tree) {
  return (tree?.domains || []).flatMap((domain) =>
    (domain.categories || []).flatMap((category) =>
      (category.subcategories || [])
        .filter((subcategory) => subcategory.is_assignable)
        .map((subcategory) => ({
          value: subcategory.id,
          label: `${domain.label} / ${category.label} / ${subcategory.label}`,
        })),
    ),
  );
}

function skillOptions(tree) {
  return (tree?.categories || []).flatMap((category) =>
    (category.technologies || []).flatMap((technology) =>
      (technology.skills || []).map((skill) => ({
        value: skill.id,
        label: `${category.name} / ${technology.name} / ${skill.name}`,
      })),
    ),
  );
}

function industryOptions(tree) {
  return (tree?.nodes || []).map((node) => ({
    value: node.id,
    label: `${node.code} · ${node.labels?.en || 'Unknown Industry'}`,
    hasChildren: node.level !== 'subclass',
  }));
}

const canonicalActions = [
  {
    value: 'assign_existing_subcategory',
    label: 'Assign existing Job Subcategory',
    requiresTarget: true,
    consequence:
      'This accepts an existing governed Job Subcategory and updates the Job Intelligence Projection.',
  },
  {
    value: 'mark_insufficient_evidence',
    label: 'Mark insufficient evidence',
    consequence:
      'The Job remains Unassigned until new evidence is reviewed.',
  },
];

function isSourceEvidenceReason(item) {
  return (item?.reasons || []).some((reason) => (
    reason === 'source_catalog_provenance_missing'
    || reason === 'source_classification_paths_missing'
  ));
}

export const GOVERNANCE_AREA_ADAPTERS = {
  'job-taxonomy': {
    queueSearchLabel: 'Filter by Job ID',
    loadQueue: ({ query, cursor, page, limit = 10, scope = {} } = {}, options) =>
      fetchCanonicalReviewItems(
        {
          status: ['active'],
          ...(scope.reason ? { reason: [scope.reason] } : {}),
          ...(query ? { jobId: query } : {}),
          ...(scope.jobIds ? { jobIds: scope.jobIds } : {}),
          ...(scope.sourceSites ? { sourceSites: scope.sourceSites } : {}),
          ...(scope.sourceClassificationIds
            ? { sourceClassificationIds: scope.sourceClassificationIds }
            : {}),
          ...(scope.sourceSubclassificationIds
            ? { sourceSubclassificationIds: scope.sourceSubclassificationIds }
            : {}),
          ...(scope.postedDateFrom ? { postedDateFrom: scope.postedDateFrom } : {}),
          ...(scope.postedDateTo ? { postedDateTo: scope.postedDateTo } : {}),
          ...(scope.pendingLimit ? { pendingLimit: scope.pendingLimit } : {}),
          ...(cursor ? { cursor } : {}),
          ...(page && !cursor ? { page } : {}),
          limit,
        },
        options,
      ),
    queueLabel: (item) => item.job_title || 'Job details unavailable',
    queueMeta: (item) => [
      item.company_name || 'Company unavailable',
      (item.reasons || []).join(', ') || 'Unassigned',
    ].join(' · '),
    loadDetail: (id, options) => fetchCanonicalReviewItem(id, options),
    loadAudit: (id, options) =>
      fetchCanonicalAudit({ subjectId: id, limit: 50 }, options),
    loadOptions: async (options) =>
      canonicalOptions(await fetchCanonicalTree(options)),
    decide: decideCanonicalReviewItem,
    affectedLabel: () => '1 Job',
    evidenceSummary: (item) =>
      (item.reasons || []).join(', ') || item.evidence_hash,
    actions: canonicalActions,
    getActions: (item) => (isSourceEvidenceReason(item) ? [] : canonicalActions),
    isSourceEvidenceReason,
  },
  'skill-candidates': {
    queueSearchLabel: 'Search Skill Candidates',
    loadQueue: ({ query, cursor, page, limit = 10 } = {}, options) =>
      fetchSkillCandidates(
        {
          status: ['pending'],
          ...(query ? { search: query } : {}),
          ...(cursor ? { cursor } : {}),
          ...(page && !cursor ? { page } : {}),
          limit,
        },
        options,
      ),
    queueLabel: (item) => item.canonical_raw_name,
    queueMeta: (item) =>
      `${item.affected_job_count} affected Jobs · ${item.occurrence_count} Mentions`,
    loadDetail: (id, options) => fetchSkillCandidate(id, options),
    loadAudit: (id, options) =>
      fetchSkillAudit({ subjectId: id, limit: 50 }, options),
    loadOptions: async (options) => skillOptions(await fetchSkillTree(options)),
    loadRecommendations: fetchSkillRecommendations,
    decide: decideSkillCandidate,
    affectedLabel: (item) => `${item.affected_job_count} Jobs`,
    evidenceSummary: (item) => (item.raw_variants || []).join(', '),
    actions: [
      {
        value: 'merge_existing',
        label: 'Merge into governed Skill',
        requiresTarget: true,
        consequence:
          'Every active Mention is resolved to the selected governed Skill and affected Job projections are rebuilt.',
      },
      {
        value: 'create_skill',
        label: 'Create governed Skill',
        inputKind: 'create-skill',
        consequence:
          'A new immutable governed Skill is created and every affected Mention is resolved to it.',
      },
      {
        value: 'classify_generic',
        label: 'Classify as generic',
        inputKind: 'generic-tag',
        consequence:
          'The evidence remains auditable but will not appear as a governed Skill.',
      },
      {
        value: 'reject',
        label: 'Reject candidate',
        inputKind: 'rejection-reason',
        consequence:
          'The evidence remains auditable and is excluded from governed Skill consumers.',
      },
    ],
  },
  'company-industries': {
    queueSearchLabel: 'Filter by Source Industry value',
    loadQueue: ({ query, cursor, page, limit = 10 } = {}, options) =>
      fetchCompanyIndustryReviewItems(
        {
          status: ['active'],
          ...(query ? { rawValue: query } : {}),
          ...(cursor ? { cursor } : {}),
          ...(page && !cursor ? { page } : {}),
          limit,
        },
        options,
      ),
    queueLabel: (item) => item.raw_value || `Company ${item.company_id}`,
    queueMeta: (item) => `${item.source_site || 'Unknown Source'} · ${item.reason}`,
    loadDetail: (id, options) => fetchCompanyIndustryReviewItem(id, options),
    loadAudit: (id, options) =>
      fetchCompanyIndustryAudit({ subjectId: id, limit: 50 }, options),
    loadOptions: async (options) => {
      const [tree, mappings] = await Promise.all([
        fetchCompanyIndustryTree({}, options),
        fetchCompanyIndustryMappings({ status: ['active'] }, options),
      ]);
      return { targets: industryOptions(tree), mappings, tree };
    },
    loadTargetChildren: async (parentId, options) =>
      industryOptions(
        await fetchCompanyIndustryTree({ parentId }, options),
      ),
    targetBrowseLabel: 'Show child Industries',
    decide: decideCompanyIndustryReviewItem,
    affectedLabel: () => '1 Company',
    evidenceSummary: (item) => item.raw_value || item.reason,
    actions: [
      {
        value: 'assign_existing_industry',
        label: 'Assign existing Company Industry',
        requiresTarget: true,
        consequence:
          'The selected governed Industry becomes a non-Primary Company assignment.',
      },
      {
        value: 'assign_existing_primary_industry',
        label: 'Assign as Primary Company Industry',
        requiresTarget: true,
        consequence:
          'The selected governed Industry becomes the explicit Primary assignment for this Company.',
      },
      {
        value: 'approve_mapping_and_assign',
        label: 'Approve mapping and assign',
        requiresTarget: true,
        consequence:
          'This creates reusable Source Industry mapping authority and assigns this Company.',
      },
      {
        value: 'approve_mapping_and_assign_primary',
        label: 'Approve mapping and assign Primary',
        requiresTarget: true,
        consequence:
          'This creates reusable mapping authority and an explicit Primary assignment.',
      },
      {
        value: 'mark_insufficient_evidence',
        label: 'Mark insufficient evidence',
        consequence:
          'No governed Company Industry assignment is created.',
      },
      {
        value: 'mark_not_company_industry',
        label: 'Mark as not Company Industry',
        consequence:
          'This evidence is closed without creating an Industry assignment.',
      },
    ],
  },
};
