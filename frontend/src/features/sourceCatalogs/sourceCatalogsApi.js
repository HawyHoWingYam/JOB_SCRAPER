import { apiPath } from '../../api/base';
import { apiFetchJson, ApiRequestError } from '../../api/client';

const SOURCES = new Set(['jobsdb', 'ctgoodjobs', 'offertoday']);
export const DEFAULT_CATALOG_ACTOR = 'local-operator';

export class SourceCatalogPayloadError extends Error {
  constructor(path, message) {
    super(`Invalid Source Catalog response at ${path}: ${message}`);
    this.name = 'SourceCatalogPayloadError';
    this.path = path;
  }
}

function object(value, path) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new SourceCatalogPayloadError(path, 'expected object');
  }
  return value;
}

function array(value, path) {
  if (!Array.isArray(value)) {
    throw new SourceCatalogPayloadError(path, 'expected array');
  }
  return value;
}

function string(value, path, { nullable = false } = {}) {
  if (nullable && value === null) return null;
  if (typeof value !== 'string' || !value.trim()) {
    throw new SourceCatalogPayloadError(path, 'expected non-empty string');
  }
  return value;
}

function number(value, path, fallback = null) {
  if (value === undefined && fallback !== null) return fallback;
  if (!Number.isInteger(value) || value < 0) {
    throw new SourceCatalogPayloadError(path, 'expected non-negative integer');
  }
  return value;
}

function boolean(value, path) {
  if (typeof value !== 'boolean') {
    throw new SourceCatalogPayloadError(path, 'expected boolean');
  }
  return value;
}

function optionalObject(value, path) {
  return value == null ? null : object(value, path);
}

function decodeSource(value, path) {
  const source = string(value, path);
  if (!SOURCES.has(source)) {
    throw new SourceCatalogPayloadError(path, `unsupported source ${source}`);
  }
  return source;
}

function decodeRevision(value, path) {
  const row = object(value, path);
  return {
    id: string(row.id, `${path}.id`),
    sourceSite: decodeSource(row.source_site, `${path}.source_site`),
    sequence: number(row.sequence, `${path}.sequence`),
    fingerprint: string(row.fingerprint, `${path}.fingerprint`),
    predecessorRevisionId:
      row.predecessor_revision_id == null
        ? null
        : string(row.predecessor_revision_id, `${path}.predecessor_revision_id`),
    publishedBy: string(row.published_by, `${path}.published_by`),
    publishedAt: string(row.published_at, `${path}.published_at`),
    provenance: optionalObject(row.provenance, `${path}.provenance`) || {},
    publicationMetadata:
      optionalObject(row.publication_metadata, `${path}.publication_metadata`) || {},
    validationSummary:
      optionalObject(row.validation_summary, `${path}.validation_summary`) || {},
    nodeCount: number(row.node_count, `${path}.node_count`, 0),
    queryTargetCount: number(
      row.query_target_count,
      `${path}.query_target_count`,
      0,
    ),
  };
}

function decodeLatestCandidate(value, path) {
  if (value == null) return null;
  const row = object(value, path);
  return {
    id: string(row.id, `${path}.id`),
    fingerprint: string(row.fingerprint, `${path}.fingerprint`),
    state: string(row.state, `${path}.state`),
    createdAt: string(row.created_at, `${path}.created_at`),
  };
}

export function decodeCatalogSummaries(value) {
  const payload = object(value, '$');
  return array(payload.sources, '$.sources').map((item, index) => {
    const row = object(item, `$.sources[${index}]`);
    if (!('published_revision' in row) || !('latest_candidate' in row)) {
      throw new SourceCatalogPayloadError(
        `$.sources[${index}]`,
        'missing published_revision or latest_candidate',
      );
    }
    return {
      sourceSite: decodeSource(row.source_site, `$.sources[${index}].source_site`),
      publishedRevision:
        row.published_revision == null
          ? null
          : decodeRevision(row.published_revision, `$.sources[${index}].published_revision`),
      latestCandidate: decodeLatestCandidate(
        row.latest_candidate,
        `$.sources[${index}].latest_candidate`,
      ),
      affectedAutomationCount: number(
        row.affected_automation_count,
        `$.sources[${index}].affected_automation_count`,
        0,
      ),
    };
  });
}

function decodeNode(value, path) {
  const row = object(value, path);
  const nativeId = row.native_id;
  if (!['string', 'number'].includes(typeof nativeId)) {
    throw new SourceCatalogPayloadError(`${path}.native_id`, 'expected string or number');
  }
  return {
    nodeKey: string(row.node_key, `${path}.node_key`),
    sourceSite: decodeSource(row.source_site, `${path}.source_site`),
    classificationId:
      row.classification_id == null
        ? null
        : string(row.classification_id, `${path}.classification_id`),
    nativeId,
    nativeLabel: string(row.native_label, `${path}.native_label`),
    parentNodeKey:
      row.parent_node_key == null
        ? null
        : string(row.parent_node_key, `${path}.parent_node_key`),
    nativePath: array(row.native_path, `${path}.native_path`).map((part, index) =>
      string(part, `${path}.native_path[${index}]`),
    ),
    depth: number(row.depth, `${path}.depth`),
    selectable: boolean(row.selectable, `${path}.selectable`),
    supportsExact: boolean(row.supports_exact, `${path}.supports_exact`),
    supportsSubtree: boolean(row.supports_subtree, `${path}.supports_subtree`),
    queryable: boolean(row.queryable, `${path}.queryable`),
    aliasOfNodeKey:
      row.alias_of_node_key == null
        ? null
        : string(row.alias_of_node_key, `${path}.alias_of_node_key`),
    querySemanticsHash:
      row.query_semantics_hash == null
        ? null
        : string(row.query_semantics_hash, `${path}.query_semantics_hash`),
    sourceMetadata: optionalObject(row.source_metadata, `${path}.source_metadata`) || {},
  };
}

function decodeCatalog(value, path) {
  const row = object(value, path);
  const capabilities = object(row.capabilities, `${path}.capabilities`);
  return {
    version: number(row.version, `${path}.version`),
    sourceSite: decodeSource(row.source_site, `${path}.source_site`),
    nodes: array(row.nodes, `${path}.nodes`).map((node, index) =>
      decodeNode(node, `${path}.nodes[${index}]`),
    ),
    capabilities: {
      supportsAllScope: boolean(
        capabilities.supports_all_scope,
        `${path}.capabilities.supports_all_scope`,
      ),
      allScopeRootNodeKeys: array(
        capabilities.all_scope_root_node_keys,
        `${path}.capabilities.all_scope_root_node_keys`,
      ).map((item, index) =>
        string(item, `${path}.capabilities.all_scope_root_node_keys[${index}]`),
      ),
      recommendedScope:
        optionalObject(
          capabilities.recommended_scope,
          `${path}.capabilities.recommended_scope`,
        ),
    },
  };
}

const DIFF_KEYS = [
  'added',
  'removed',
  'renamed',
  'moved',
  'alias_changed',
  'capabilities_changed',
  'query_semantics_changed',
];

function decodeDiff(value, path) {
  const row = object(value, path);
  return Object.fromEntries(
    DIFF_KEYS.map((key) => [
      key,
      array(row[key] || [], `${path}.${key}`).map((item, index) =>
        object(item, `${path}.${key}[${index}]`),
      ),
    ]),
  );
}

export function decodeCandidate(value, path = '$') {
  const row = object(value, path);
  return {
    id: string(row.id, `${path}.id`),
    sourceSite: decodeSource(row.source_site, `${path}.source_site`),
    baseRevisionId:
      row.base_revision_id == null
        ? null
        : string(row.base_revision_id, `${path}.base_revision_id`),
    fingerprint: string(row.fingerprint, `${path}.fingerprint`),
    state: string(row.state, `${path}.state`),
    catalog: decodeCatalog(row.normalized_payload, `${path}.normalized_payload`),
    diff: decodeDiff(row.diff, `${path}.diff`),
    validationSummary:
      optionalObject(row.validation_summary, `${path}.validation_summary`) || {},
    provenance: optionalObject(row.provenance, `${path}.provenance`) || {},
    createdAt: string(row.created_at, `${path}.created_at`),
    validatedAt:
      row.validated_at == null ? null : string(row.validated_at, `${path}.validated_at`),
    publishedAt:
      row.published_at == null ? null : string(row.published_at, `${path}.published_at`),
  };
}

function decodeValidationRun(value, path) {
  const row = object(value, path);
  return {
    id: string(row.id, `${path}.id`),
    candidateId: string(row.candidate_id, `${path}.candidate_id`),
    validationKind: string(row.validation_kind, `${path}.validation_kind`),
    classificationId:
      row.classification_id == null
        ? null
        : string(row.classification_id, `${path}.classification_id`),
    targetHashPrefix: string(row.target_hash_prefix, `${path}.target_hash_prefix`),
    status: string(row.status, `${path}.status`),
    attempt: number(row.attempt, `${path}.attempt`),
    evidence: optionalObject(row.evidence, `${path}.evidence`) || {},
    error: optionalObject(row.error, `${path}.error`),
    manualAction: optionalObject(row.manual_action, `${path}.manual_action`),
    createdAt: string(row.created_at, `${path}.created_at`),
    completedAt:
      row.completed_at == null
        ? null
        : string(row.completed_at, `${path}.completed_at`),
  };
}

function decodeValidationRuns(value) {
  const payload = object(value, '$');
  return array(payload.runs, '$.runs').map((run, index) =>
    decodeValidationRun(run, `$.runs[${index}]`),
  );
}

function decodeReview(value) {
  const payload = object(value, '$');
  return {
    reviewId: string(payload.review_id, '$.review_id'),
    reviewToken: string(payload.review_token, '$.review_token'),
    expiresAt: string(payload.expires_at, '$.expires_at'),
    impact: object(payload.impact, '$.impact'),
  };
}

function decodePublication(value, path) {
  const row = object(value, path);
  return {
    id: string(row.id, `${path}.id`),
    operation: string(row.operation, `${path}.operation`),
    revisionId: string(row.revision_id, `${path}.revision_id`),
    previousRevisionId:
      row.previous_revision_id == null
        ? null
        : string(row.previous_revision_id, `${path}.previous_revision_id`),
    actor: string(row.actor, `${path}.actor`),
    createdAt: string(row.created_at, `${path}.created_at`),
  };
}

function decodeHistory(value) {
  const payload = object(value, '$');
  return {
    sourceSite: decodeSource(payload.source_site, '$.source_site'),
    revisions: array(payload.revisions, '$.revisions').map((row, index) =>
      decodeRevision(row, `$.revisions[${index}]`),
    ),
    publications: array(payload.publications || [], '$.publications').map((row, index) =>
      decodePublication(row, `$.publications[${index}]`),
    ),
  };
}

function jsonBody(value) {
  return {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(value),
  };
}

function catalogPath(source, suffix = '') {
  return apiPath(`/source-catalogs/${encodeURIComponent(source)}${suffix}`);
}

export async function getCatalogSummaries({ signal } = {}) {
  return decodeCatalogSummaries(
    await apiFetchJson(apiPath('/source-catalogs'), { signal }),
  );
}

export async function getPublishedCatalog(source, { signal } = {}) {
  const payload = object(
    await apiFetchJson(catalogPath(source, '/published'), { signal }),
    '$',
  );
  return {
    revision: decodeRevision(payload.revision, '$.revision'),
    catalog: decodeCatalog(payload.catalog, '$.catalog'),
  };
}

export async function discoverCandidate(source) {
  const payload = object(
    await apiFetchJson(catalogPath(source, '/candidates'), { method: 'POST' }),
    '$',
  );
  return {
    created: boolean(payload.created, '$.created'),
    candidate: decodeCandidate(payload.candidate, '$.candidate'),
  };
}

export async function getCandidate(source, candidateId, { signal } = {}) {
  return decodeCandidate(
    await apiFetchJson(
      catalogPath(source, `/candidates/${encodeURIComponent(candidateId)}`),
      { signal },
    ),
  );
}

export async function startValidation(source, candidateId) {
  return decodeValidationRuns(
    await apiFetchJson(
      catalogPath(
        source,
        `/candidates/${encodeURIComponent(candidateId)}/validation-runs`,
      ),
      { method: 'POST' },
    ),
  );
}

export async function getValidationRuns(source, candidateId, { signal } = {}) {
  return decodeValidationRuns(
    await apiFetchJson(
      catalogPath(
        source,
        `/candidates/${encodeURIComponent(candidateId)}/validation-runs`,
      ),
      { signal },
    ),
  );
}

export async function createPublicationReview(
  source,
  candidateId,
  actor = DEFAULT_CATALOG_ACTOR,
) {
  return decodeReview(
    await apiFetchJson(
      catalogPath(
        source,
        `/candidates/${encodeURIComponent(candidateId)}/publication-reviews`,
      ),
      jsonBody({ actor }),
    ),
  );
}

export async function publishCandidate(
  source,
  candidateId,
  reviewToken,
  actor = DEFAULT_CATALOG_ACTOR,
) {
  const payload = object(
    await apiFetchJson(
      catalogPath(source, `/candidates/${encodeURIComponent(candidateId)}/publish`),
      jsonBody({ actor, review_token: reviewToken }),
    ),
    '$',
  );
  return decodeRevision(payload.revision, '$.revision');
}

export async function getRevisionHistory(source, { signal } = {}) {
  return decodeHistory(
    await apiFetchJson(catalogPath(source, '/revisions'), { signal }),
  );
}

export async function createRollbackReview(
  source,
  revisionId,
  actor = DEFAULT_CATALOG_ACTOR,
) {
  return decodeReview(
    await apiFetchJson(
      catalogPath(
        source,
        `/revisions/${encodeURIComponent(revisionId)}/rollback-reviews`,
      ),
      jsonBody({ actor }),
    ),
  );
}

export async function rollbackRevision(
  source,
  revisionId,
  reviewToken,
  actor = DEFAULT_CATALOG_ACTOR,
) {
  const payload = object(
    await apiFetchJson(
      catalogPath(source, `/revisions/${encodeURIComponent(revisionId)}/rollback`),
      jsonBody({ actor, review_token: reviewToken }),
    ),
    '$',
  );
  return decodeRevision(payload.revision, '$.revision');
}

export function catalogErrorState(error) {
  if (!(error instanceof ApiRequestError)) {
    return { kind: 'network', message: error?.message || 'Request failed', error };
  }
  const kind = {
    CATALOG_CANDIDATE_STALE: 'stale-candidate',
    CATALOG_IMPACT_STALE: 'stale-impact',
    CATALOG_VALIDATION_REQUIRED: 'validation-required',
    CATALOG_VALIDATION_FAILED: 'validation-failed',
    CATALOG_MANUAL_ACTION_REQUIRED: 'manual-action-required',
    CATALOG_NOT_PUBLISHED: 'not-published',
  }[error.code] || 'api';
  return {
    kind,
    code: error.code,
    message: error.message,
    details: error.details,
    requestId: error.requestId,
    error,
  };
}
