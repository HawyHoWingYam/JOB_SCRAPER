const EXPERIENCE_LEVEL_LABELS = {
  entry_level: 'Entry Level', junior_level: 'Junior Level', junior: 'Junior',
  mid_level: 'Mid Level', senior_level: 'Senior Level', senior: 'Senior',
  lead_level: 'Lead Level', lead: 'Lead', principal: 'Principal',
  manager_level: 'Manager Level', manager: 'Manager', director: 'Director',
  director_level: 'Director Level', executive_level: 'Executive Level',
  internship: 'Internship',
};

function formatLevel(level) {
  if (!level) return '';
  if (EXPERIENCE_LEVEL_LABELS[level]) return EXPERIENCE_LEVEL_LABELS[level];
  return String(level).replace(/[_-]+/g, ' ').trim()
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

export function formatExperienceDisplay(job = {}) {
  if (job.experience_level === 'not_specified') {
    return { label: 'Not specified', detail: 'The posting does not specify experience', estimated: false };
  }
  const hasMin = job.experience_min_years != null;
  const hasMax = job.experience_max_years != null;
  const min = Number(job.experience_min_years);
  const max = Number(job.experience_max_years);
  const estimated = job.experience_provenance === 'inferred' || job.experience_is_estimated === true;
  if (hasMin && hasMax && min === 0 && max === 0) {
    return { label: '0+', detail: 'No experience required', estimated: false };
  }
  if (hasMin) {
    const detail = hasMax && max !== min ? `${min}–${max} years` : `At least ${min} ${min === 1 ? 'year' : 'years'}`;
    return { label: `${estimated ? 'About ' : ''}${min}+`, detail: `${estimated ? 'Estimated ' : ''}${detail}`, estimated };
  }
  if (hasMax) {
    return { label: `${estimated ? 'About ' : ''}≤${max}`, detail: `${estimated ? 'Estimated up to' : 'Up to'} ${max} ${max === 1 ? 'year' : 'years'}`, estimated };
  }
  const level = formatLevel(job.experience_level);
  if (level) {
    return { label: level, detail: 'Seniority level only; no year range is available', estimated: false };
  }
  return { label: 'Not available', detail: 'Experience has not been processed', estimated: false };
}
