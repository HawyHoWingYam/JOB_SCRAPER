import React, { useEffect, useRef, useState } from 'react';
import DOMPurify from 'dompurify';
import { X } from 'lucide-react';
import SkillTags from './SkillTags';
import { governanceHash } from './jobIntelligence/governanceRoute';

const RELATED_JOBS_UNAVAILABLE_MESSAGE = 'Related jobs are unavailable in the current runtime profile.';

function formatRelativePostedState(postedDate) {
  if (!postedDate) {
    return 'Posted date unavailable';
  }

  const parsed = new Date(postedDate);
  if (Number.isNaN(parsed.getTime())) {
    return 'Posted date unavailable';
  }

  const diffMs = Math.max(0, Date.now() - parsed.getTime());
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

  if (diffDays === 0) {
    return 'Posted today';
  }
  if (diffDays === 1) {
    return 'Posted 1 day ago';
  }
  return `Posted ${diffDays} days ago`;
}

function formatLongDate(value) {
  if (!value) {
    return null;
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return null;
  }

  return parsed.toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  });
}

function getAiStateMessage(job) {
  if (!job.ai_enriched_at) {
    return 'AI enrichment not run yet';
  }
  return null;
}

function getAwaitingAiCopy() {
  return 'Awaiting AI enrichment output';
}

function formatExperienceLevel(level) {
  if (!level || level === 'not_specified') {
    return null;
  }

  const known = {
    junior_level: 'Junior level',
    entry_level: 'Entry level',
    junior: 'Junior',
    mid_level: 'Mid level',
    senior_level: 'Senior level',
    senior: 'Senior',
    lead_level: 'Lead level',
    lead: 'Lead',
    principal: 'Principal',
    manager_level: 'Manager level',
    manager: 'Manager',
    director: 'Director',
    director_level: 'Director level',
    executive_level: 'Executive level',
    internship: 'Internship',
  };

  if (known[level]) {
    return known[level];
  }

  // Best-effort humanization for unexpected enum values.
  return String(level)
    .replace(/[_-]+/g, ' ')
    .trim()
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

function hasExperienceYears(value) {
  return value != null;
}

function getExperienceLabel(job) {
  if (!job.ai_enriched_at) {
    return getAwaitingAiCopy();
  }

  // When enrichment ran but explicitly found nothing, treat the whole block as empty.
  // Some test fixtures keep min/max defaults while setting `experience_level: not_specified`;
  // `not_specified` should win and still render the empty-state copy.
  if (job.experience_level === 'not_specified') {
    return 'No explicit experience requirement found in the posting';
  }

  const levelLabel = formatExperienceLevel(job.experience_level);
  const hasMinYears = hasExperienceYears(job.experience_min_years);
  const hasMaxYears = hasExperienceYears(job.experience_max_years);

  if (hasMinYears && hasMaxYears) {
    return `${job.experience_min_years}-${job.experience_max_years} years`;
  }

  if (hasMinYears) {
    return `${job.experience_min_years}+ years`;
  }

  if (hasMaxYears) {
    return `Up to ${job.experience_max_years} years`;
  }

  return levelLabel || 'No explicit experience requirement found in the posting';
}

function isExperienceEmpty(job) {
  if (!job.ai_enriched_at) {
    return true;
  }

  if (job.experience_level === 'not_specified') {
    return true;
  }

  if (hasExperienceYears(job.experience_min_years) || hasExperienceYears(job.experience_max_years)) {
    return false;
  }

  return !formatExperienceLevel(job.experience_level);
}

function getExpiryLabel(job) {
  const formatted = formatLongDate(job.expiry_date);
  if (!formatted) {
    return null;
  }

  if (job.is_expired) {
    return `Expired on ${formatted}`;
  }
  return `Application closes ${formatted}`;
}

function formatRelatedJobScore(score) {
  const numericScore = Number(score);
  if (!Number.isFinite(numericScore)) {
    return 'Score unavailable';
  }

  return `${Math.round(numericScore * 100)}%`;
}

function humanizeContractValue(value) {
  if (!value) {
    return 'Unknown';
  }

  return String(value)
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, (character) => character.toUpperCase())
    .replace(/\bAi\b/g, 'AI');
}

function sourceClassificationPathLabel(path) {
  const labels = Array.isArray(path?.nodes)
    ? path.nodes.map((node) => node?.label).filter(Boolean)
    : [];
  return labels.length > 0 ? labels.join(' / ') : 'Unknown Source Classification Path';
}

function canonicalBreadcrumbLabel(breadcrumb) {
  const labels = [
    breadcrumb?.domain?.label,
    breadcrumb?.category?.label,
    breadcrumb?.subcategory?.label,
  ].filter(Boolean);
  return labels.length === 3 ? labels.join(' / ') : null;
}

function relatedEmploymentTypesLabel(relatedJob) {
  if (relatedJob?.job_intelligence_availability?.source_attributes?.available === false) {
    return 'Employment Types unavailable';
  }

  const labels = Array.isArray(relatedJob?.employment_types)
    ? relatedJob.employment_types.map((employmentType) => employmentType?.label).filter(Boolean)
    : [];
  return labels.length > 0 ? labels.join(', ') : 'Employment Types Unknown';
}

function relatedCanonicalTaxonomyLabel(relatedJob) {
  if (relatedJob?.job_intelligence_availability?.canonical_taxonomy?.available === false) {
    return 'Canonical Job Taxonomy unavailable';
  }

  const canonicalState = relatedJob?.canonical_taxonomy;
  if (canonicalState?.state === 'assigned' && canonicalState.assignment) {
    return canonicalBreadcrumbLabel(canonicalState.assignment.breadcrumb)
      || 'Canonical Job Taxonomy breadcrumb unavailable';
  }
  if (canonicalState?.state === 'unassigned') {
    return 'Unassigned Canonical Taxonomy';
  }
  return 'Canonical Job Taxonomy Unknown';
}

function companyIndustryBreadcrumbLabel(breadcrumb) {
  if (!Array.isArray(breadcrumb) || breadcrumb.length === 0) {
    return 'Unknown Company Industry';
  }

  return breadcrumb
    .map((node) => {
      const label = node?.labels?.en || 'Unknown Company Industry';
      return node?.code ? `${node.code} · ${label}` : label;
    })
    .join(' / ');
}

function JobDetailModal({ jobId, apiUrl, onClose, capabilities = null, capabilitiesLoading = false }) {
  const dialogRef = useRef(null);
  const closeButtonRef = useRef(null);
  const onCloseRef = useRef(onClose);
  const [job, setJob] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [relatedJobs, setRelatedJobs] = useState([]);
  const [relatedJobsLoading, setRelatedJobsLoading] = useState(true);
  const [relatedJobsError, setRelatedJobsError] = useState('');
  const recommendationsAvailable = capabilities?.recommendations?.similar_jobs?.available !== false;

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    const previouslyFocused = document.activeElement;
    closeButtonRef.current?.focus();

    const handleKeyDown = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        event.stopPropagation();
        onCloseRef.current();
        return;
      }

      if (event.key !== 'Tab') {
        return;
      }

      const focusable = Array.from(dialogRef.current?.querySelectorAll(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ) || []).filter((element) => element.getAttribute('aria-hidden') !== 'true');
      if (focusable.length === 0) {
        return;
      }

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const activeElement = document.activeElement;
      const focusIsOutsideDialog = !dialogRef.current?.contains(activeElement);

      if (event.shiftKey && (activeElement === first || focusIsOutsideDialog)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (activeElement === last || focusIsOutsideDialog)) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      if (previouslyFocused instanceof HTMLElement && previouslyFocused.isConnected) {
        previouslyFocused.focus();
      }
    };
  }, []);

  useEffect(() => {
    let isActive = true;
    setLoading(true);
    setError(null);

    fetch(`${apiUrl}/api/v1/jobs/${jobId}`)
      .then((res) => {
        if (!res.ok) throw new Error('Job not found');
        return res.json();
      })
      .then((data) => {
        if (!isActive) {
          return;
        }
        setJob(data);
        setLoading(false);
      })
      .catch((err) => {
        if (!isActive) {
          return;
        }
        setError(err.message);
        setLoading(false);
      });

    return () => {
      isActive = false;
    };
  }, [jobId, apiUrl]);

  useEffect(() => {
    let isActive = true;

    setRelatedJobs([]);
    setRelatedJobsError('');

    if (capabilitiesLoading) {
      setRelatedJobsLoading(true);
      return () => {
        isActive = false;
      };
    }

    if (!recommendationsAvailable) {
      setRelatedJobsLoading(false);
      setRelatedJobsError(RELATED_JOBS_UNAVAILABLE_MESSAGE);
      return () => {
        isActive = false;
      };
    }

    setRelatedJobsLoading(true);

    const controller = new AbortController();
    const TIMEOUT_MS = 10000;
    const timeoutId = setTimeout(() => controller.abort(), TIMEOUT_MS);

    fetch(`${apiUrl}/api/v1/jobs/${jobId}/similar`, { signal: controller.signal })
      .then((res) => {
        if (!res.ok) {
          throw new Error('Related jobs are unavailable right now');
        }
        return res.json();
      })
      .then((data) => {
        if (!isActive) {
          return;
        }
        setRelatedJobs(data.recommendations || []);
        setRelatedJobsLoading(false);
      })
      .catch((err) => {
        if (!isActive) {
          return;
        }
        if (err.name === 'AbortError') {
          setRelatedJobsError('Related jobs timed out. Try again later.');
        } else {
          setRelatedJobsError(err.message);
        }
        setRelatedJobsLoading(false);
      })
      .finally(() => {
        clearTimeout(timeoutId);
      });

    return () => {
      isActive = false;
      controller.abort();
      clearTimeout(timeoutId);
    };
  }, [jobId, apiUrl, capabilitiesLoading, recommendationsAvailable]);

  const handleOverlayClick = (e) => {
    if (e.target === e.currentTarget) {
      onClose();
    }
  };

  const originalJobUrl = job?.original_job_url || null;
  const aiStateMessage = job ? getAiStateMessage(job) : null;
  const expiryLabel = job ? getExpiryLabel(job) : null;
  const sourceClassificationPaths = Array.isArray(job?.source_classification_paths)
    ? job.source_classification_paths
    : [];
  const employmentTypes = Array.isArray(job?.employment_types)
    ? job.employment_types
    : [];
  const sourceEmploymentLabels = Array.isArray(job?.source_employment_labels)
    ? job.source_employment_labels
    : [];
  const canonicalState = job?.canonical_taxonomy || null;
  const canonicalAvailability = job?.job_intelligence_availability?.canonical_taxonomy;
  const companyIndustryState = job?.company_industries || null;
  const companyIndustryAvailability = job?.job_intelligence_availability?.company_industries;
  const companyIndustryAssignments = Array.isArray(companyIndustryState?.assignments)
    ? companyIndustryState.assignments
    : [];
  const primaryCompanyIndustry = companyIndustryAssignments.find(
    (assignment) => assignment?.is_primary === true,
  );
  const additionalCompanyIndustryCount = primaryCompanyIndustry
    ? Math.max(companyIndustryAssignments.length - 1, 0)
    : 0;
  const governedSkillNames = Array.isArray(job?.skill_state?.skills)
    ? job.skill_state.skills.map((skill) => skill?.name).filter(Boolean)
    : (job?.skills || []);
  const structuredUnreviewedMentions = Array.isArray(job?.skill_state?.unreviewed_skill_mentions)
    ? job.skill_state.unreviewed_skill_mentions
    : (Array.isArray(job?.unreviewed_skill_mentions)
      ? job.unreviewed_skill_mentions
      : null);
  const unreviewedSkillMentions = structuredUnreviewedMentions === null
    ? (job?.provisional_skills || []).map((rawName) => ({ raw_name: rawName }))
    : structuredUnreviewedMentions;
  const hasUnreviewedSkillMentions = unreviewedSkillMentions.length > 0;

  return (
    <div className="modal-overlay" onClick={handleOverlayClick}>
      <div
        ref={dialogRef}
        className="modal-content job-detail-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby={job ? 'job-detail-title' : undefined}
        aria-label={job ? undefined : 'Job details'}
      >
        <button
          ref={closeButtonRef}
          type="button"
          className="modal-close"
          onClick={onClose}
          aria-label="Close job details"
        >
          <X size={18} />
        </button>

        {loading && (
          <div className="modal-loading" role="status" aria-live="polite">
            Loading job details…
          </div>
        )}

        {error && (
          <div className="modal-error" role="alert">
            <p>{error}</p>
            <button type="button" onClick={onClose}>Close</button>
          </div>
        )}

        {job && (
          <>
            <div className="modal-header">
              <h2 id="job-detail-title">{job.title}</h2>
              <p className="modal-company">{job.company_name}</p>
              <p className="modal-location">{job.location}</p>
            </div>

            <section
              className="modal-section"
              role="region"
              aria-labelledby="job-role-evidence-heading"
            >
              <h3 id="job-role-evidence-heading">Role Evidence</h3>
              <dl className="modal-kv">
                <dt>Salary</dt>
                <dd>{job.salary_range || 'Not specified'}</dd>
                <dt>Employment Types</dt>
                <dd>
                  {employmentTypes.length > 0 ? (
                    <span className="modal-inline-tags">
                      {employmentTypes.map((employmentType) => (
                        <span key={employmentType.code} className="tag type-tag">
                          {employmentType.label}
                        </span>
                      ))}
                    </span>
                  ) : (
                    'Unknown'
                  )}
                </dd>
                <dt>Source Classification Paths</dt>
                <dd>
                  {sourceClassificationPaths.length > 0 ? (
                    <ul className="modal-contract-list">
                      {sourceClassificationPaths.map((path) => (
                        <li key={path.id}>
                          <strong>{sourceClassificationPathLabel(path)}</strong>
                          <span>
                            {path.is_primary
                              ? `Primary (${humanizeContractValue(path.primary_basis)})`
                              : 'Not declared Primary'}
                          </span>
                          {path.provenance_limited && (
                            <span>Historical catalog revision unavailable</span>
                          )}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    'Unknown'
                  )}
                </dd>
                <dt>Source Employment Labels</dt>
                <dd>
                  {sourceEmploymentLabels.length > 0 ? (
                    <ul className="modal-contract-list compact">
                      {sourceEmploymentLabels.map((label) => (
                        <li key={label.id}>
                          <span>{label.raw_label || label.raw_code || 'Unknown source label'}</span>
                          <span>
                            {label.mapped_type_code
                              ? `Mapped to ${humanizeContractValue(label.mapped_type_code)}`
                              : 'Unmapped evidence'}
                          </span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    'No Source Employment Label evidence'
                  )}
                </dd>
              </dl>

              <div className="modal-meta">
                <p className="modal-meta-item">{formatRelativePostedState(job.posted_date)}</p>
                {expiryLabel && <p className="modal-meta-item">{expiryLabel}</p>}
                {originalJobUrl && (
                  <a className="modal-link" href={originalJobUrl} target="_blank" rel="noreferrer">
                    Original job post
                  </a>
                )}
              </div>
            </section>

            <section
              className="modal-section"
              role="region"
              aria-labelledby="canonical-job-taxonomy-heading"
            >
              <h3 id="canonical-job-taxonomy-heading">Canonical Job Taxonomy</h3>
              {canonicalAvailability?.available === false ? (
                <p className="modal-empty">
                  Unavailable ({canonicalAvailability.unavailable_code || 'UNKNOWN'})
                </p>
              ) : canonicalState?.state === 'assigned' && canonicalState.assignment ? (
                <div className="modal-contract-state">
                  <p className="modal-contract-primary">
                    {canonicalBreadcrumbLabel(canonicalState.assignment.breadcrumb)
                      || 'Assigned breadcrumb unavailable'}
                  </p>
                  <p>
                    Assignment method: {humanizeContractValue(canonicalState.assignment.method)}
                  </p>
                </div>
              ) : canonicalState?.state === 'unassigned' ? (
                <div className="modal-contract-state">
                  <p className="modal-empty">Unassigned Canonical Taxonomy</p>
                  <p>
                    Reasons: {canonicalState.reasons?.length > 0
                      ? canonicalState.reasons.map(humanizeContractValue).join(', ')
                      : 'Unknown'}
                  </p>
                </div>
              ) : (
                <p className="modal-empty">Canonical Job Taxonomy state is Unknown</p>
              )}
              <div className="modal-governance-links">
                <a className="modal-link" href={governanceHash('job-taxonomy')}>
                  Open Job Taxonomy Review
                </a>
                {canonicalState?.review_item_refs?.map((review) => (
                  <a
                    key={review.id}
                    className="modal-link"
                    href={governanceHash('job-taxonomy', review.id)}
                  >
                    Open review item
                  </a>
                ))}
              </div>
            </section>

            <section
              className="modal-section"
              role="region"
              aria-labelledby="company-industries-heading"
            >
              <h3 id="company-industries-heading">Company Industries</h3>
              {companyIndustryAvailability?.available === false ? (
                <p className="modal-empty">
                  Unavailable ({companyIndustryAvailability.unavailable_code || 'UNKNOWN'})
                </p>
              ) : companyIndustryAssignments.length > 0 ? (
                <ul className="modal-contract-list">
                  {companyIndustryAssignments.map((assignment) => (
                    <li key={assignment.id}>
                      <strong>{companyIndustryBreadcrumbLabel(assignment.breadcrumb)}</strong>
                      <span>
                        {assignment.is_primary
                          ? `Primary Company Industry${additionalCompanyIndustryCount > 0
                            ? ` +${additionalCompanyIndustryCount}`
                            : ''}`
                          : 'Additional Company Industry'}
                      </span>
                      <span>Basis: {humanizeContractValue(assignment.primary_basis || assignment.method)}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="modal-empty">No governed Company Industry assignment</p>
              )}
              <div className="modal-governance-links">
                <a className="modal-link" href={governanceHash('company-industries')}>
                  Open Company Industries
                </a>
                {companyIndustryState?.review_item_refs?.map((review) => (
                  <a
                    key={review.id}
                    className="modal-link"
                    href={governanceHash('company-industries', review.id)}
                  >
                    Open Industry review item
                  </a>
                ))}
              </div>
              <dl className="modal-kv modal-company-description">
                <dt>Company AI description</dt>
                <dd>{job.company_ai_description || 'No company AI description available'}</dd>
              </dl>
            </section>

            <section className="modal-section" aria-labelledby="governed-skills-heading">
              <h3 id="governed-skills-heading">Skills</h3>
              <div className="modal-subsection">
                <h4>Governed Skills</h4>
                {governedSkillNames.length > 0 ? (
                  <SkillTags skills={governedSkillNames} />
                ) : (
                  <p className="modal-empty">
                    {job.ai_enriched_at
                      ? (hasUnreviewedSkillMentions
                        ? 'No governed skills matched yet'
                        : 'No technical skills extracted from this posting')
                      : getAwaitingAiCopy()}
                  </p>
                )}
              </div>

              {hasUnreviewedSkillMentions && (
                <div className="modal-subsection">
                  <h4>Unreviewed Skill Mentions</h4>
                  <p className="modal-evidence-note">
                    Secondary evidence awaiting human taxonomy review.
                  </p>
                  <div className="skill-tags-container">
                    {unreviewedSkillMentions.map((mention, index) => (
                      mention.candidate_id ? (
                        <a
                          key={mention.id || mention.candidate_id}
                          className="skill-tag modal-skill-review-link"
                          href={governanceHash('skill-candidates', mention.candidate_id)}
                          aria-label={`Review ${mention.raw_name}`}
                        >
                          {mention.raw_name}
                        </a>
                      ) : (
                        <span key={`${mention.raw_name}-${index}`} className="skill-tag">
                          {mention.raw_name}
                        </span>
                      )
                    ))}
                  </div>
                </div>
              )}

              <div className="modal-governance-links">
                <a className="modal-link" href={governanceHash('skill-candidates')}>
                  Open Skill Candidates
                </a>
              </div>
            </section>

            <section className="modal-section modal-section-ai">
              <h3>AI Insights</h3>
              {aiStateMessage && <p className="modal-ai-state">{aiStateMessage}</p>}

              <div className="modal-subsection">
                <h4>AI Summary</h4>
                <p className={!job.ai_summary ? 'modal-empty' : undefined}>
                  {job.ai_summary || (job.ai_enriched_at
                    ? 'No AI summary extracted from this posting'
                  : getAwaitingAiCopy())}
                </p>
              </div>

              <div className="modal-subsection">
                <h4>Experience</h4>
                <p className={isExperienceEmpty(job) ? 'modal-empty modal-experience-label' : 'modal-experience-label'}>
                  {getExperienceLabel(job)}
                </p>
              </div>
            </section>

            <section className="modal-section">
              <h3>Description</h3>
              <div
                className="modal-description"
                dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(job.description ?? '') }}
              />
            </section>

            <section className="modal-section">
              <h3>Related Jobs</h3>
              {relatedJobsLoading ? (
                <p className="modal-empty">Loading related jobs...</p>
              ) : relatedJobs.length > 0 ? (
                <div className="related-jobs-list">
                  {relatedJobs.map((relatedJob) => (
                    <article
                      key={relatedJob.id}
                      className="related-job-card"
                      aria-labelledby={`related-job-${relatedJob.id}-title`}
                    >
                      <div className="related-job-card-header">
                        <h4 id={`related-job-${relatedJob.id}-title`}>{relatedJob.title}</h4>
                        <span className="related-job-score">
                          {formatRelatedJobScore(relatedJob.combined_score)}
                        </span>
                      </div>
                      <p className="related-job-company">{relatedJob.company_name || 'Unknown company'}</p>
                      <div className="related-job-meta">
                        {relatedJob.location && <span>{relatedJob.location}</span>}
                        <span>{relatedEmploymentTypesLabel(relatedJob)}</span>
                        {relatedJob.posted_date && <span>{formatRelativePostedState(relatedJob.posted_date)}</span>}
                      </div>
                      <p className="related-job-taxonomy">
                        {relatedCanonicalTaxonomyLabel(relatedJob)}
                      </p>
                    </article>
                  ))}
                </div>
              ) : (
                <p className="modal-empty">
                  {relatedJobsError || 'No related jobs available yet'}
                </p>
              )}
            </section>
          </>
        )}
      </div>
    </div>
  );
}

export default JobDetailModal;
