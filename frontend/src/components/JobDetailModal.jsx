import React, { useEffect, useState } from 'react';
import DOMPurify from 'dompurify';
import SkillTags from './SkillTags';

const JOBSDB_BASE_URL = 'https://hk.jobsdb.com/job';

function buildOriginalJobUrl(jobId) {
  return jobId ? `${JOBSDB_BASE_URL}/${jobId}` : null;
}

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

function JobDetailModal({ jobId, apiUrl, onClose }) {
  const [job, setJob] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetch(`${apiUrl}/api/v1/jobs/${jobId}`)
      .then((res) => {
        if (!res.ok) throw new Error('Job not found');
        return res.json();
      })
      .then((data) => {
        setJob(data);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });
  }, [jobId, apiUrl]);

  const handleOverlayClick = (e) => {
    if (e.target === e.currentTarget) {
      onClose();
    }
  };

  const originalJobUrl = job ? buildOriginalJobUrl(job.job_id) : null;
  const aiStateMessage = job ? getAiStateMessage(job) : null;
  const expiryLabel = job ? getExpiryLabel(job) : null;

  return (
    <div className="modal-overlay" onClick={handleOverlayClick}>
      <div className="modal-content job-detail-modal">
        <button className="modal-close" onClick={onClose}>×</button>

        {loading && <div className="modal-loading">Loading...</div>}

        {error && (
          <div className="modal-error">
            <p>{error}</p>
            <button onClick={onClose}>Close</button>
          </div>
        )}

        {job && (
          <>
            <div className="modal-header">
              <h2>{job.title}</h2>
              <p className="modal-company">{job.company_name}</p>
              <p className="modal-location">{job.location}</p>
            </div>

            <section className="modal-section">
              <h3>Role Snapshot</h3>
              <dl className="modal-kv">
                <dt>Salary</dt>
                <dd>{job.salary_range || 'Not specified'}</dd>
                <dt>Employment type</dt>
                <dd>{job.employment_type || 'Not specified'}</dd>
                <dt>Source classification</dt>
                <dd>{job.source_classification_name || 'Not provided'}</dd>
                <dt>Source sub-classification</dt>
                <dd>{job.source_subclassification_name || 'Not provided'}</dd>
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

            <section className="modal-section">
              <h3>Company Context</h3>
              <dl className="modal-kv">
                <dt>Company industry</dt>
                <dd>{job.company_industry || 'Not provided'}</dd>
                <dt>Company AI description</dt>
                <dd>{job.company_ai_description || 'No company AI description available'}</dd>
              </dl>
            </section>

            <section className="modal-section modal-section-ai">
              <h3>AI Insights</h3>
              {aiStateMessage && <p className="modal-ai-state">{aiStateMessage}</p>}

              <div className="modal-subsection">
                <h4>Skills</h4>
                {job.skills && job.skills.length > 0 ? (
                  <SkillTags skills={job.skills} />
                ) : (
                  <p className="modal-empty">
                    {job.ai_enriched_at
                      ? 'No technical skills extracted from this posting'
                      : getAwaitingAiCopy()}
                  </p>
                )}
              </div>

              <div className="modal-subsection">
                <h4>AI Summary</h4>
                <p className={!job.ai_summary ? 'modal-empty' : undefined}>
                  {job.ai_summary || (job.ai_enriched_at
                    ? 'No AI summary extracted from this posting'
                    : getAwaitingAiCopy())}
                </p>
              </div>

              <div className="modal-subsection">
                <h4>AI Category</h4>
                <p className={!job.ai_category ? 'modal-empty' : undefined}>
                  {job.ai_category || (job.ai_enriched_at
                    ? 'No AI category assigned'
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
          </>
        )}
      </div>
    </div>
  );
}

export default JobDetailModal;
