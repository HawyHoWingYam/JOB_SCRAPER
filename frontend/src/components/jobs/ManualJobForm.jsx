import React, { useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, Loader, Search } from 'lucide-react';

import { apiPath } from '../../api/base';
import { getCompanyIndustryDisplay } from '../companies/companyIndustryDisplay';
import './AddJobPage.css';

const EMPTY_DETAILS = {
  salaryMin: '',
  salaryMax: '',
  salaryCurrency: 'HKD',
  location: '',
  employmentTypeCodes: [],
  postedDate: '',
  experienceMin: '',
  experienceMax: '',
};

const SALARY_CURRENCIES = ['HKD', 'USD', 'CNY', 'GBP', 'EUR', 'SGD', 'AUD', 'CAD', 'JPY'];

function newIdempotencyKey() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `manual-job-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function errorMessage(data, fallback) {
  const detail = data?.detail;
  if (typeof detail === 'string') return detail;
  if (typeof detail?.message === 'string') return detail.message;
  if (typeof data?.message === 'string') return data.message;
  return fallback;
}

export default function ManualJobForm({
  endpoint = '/jobs/manual',
  method = 'POST',
  initialValue = null,
  submitLabel = 'Add Job',
  onSuccess,
  onCancel,
}) {
  const [title, setTitle] = useState(initialValue?.title || '');
  const [description, setDescription] = useState(initialValue?.description || '');
  const [companyMode, setCompanyMode] = useState(
    initialValue?.company?.mode === 'new' ? 'new' : 'existing',
  );
  const [selectedCompany, setSelectedCompany] = useState(
    initialValue?.company?.mode === 'existing' ? initialValue.company.value : null,
  );
  const [companySearch, setCompanySearch] = useState(selectedCompany?.name || '');
  const [companySuggestions, setCompanySuggestions] = useState([]);
  const [companySearchError, setCompanySearchError] = useState('');
  const [isSearchingCompany, setIsSearchingCompany] = useState(false);
  const [activeSuggestion, setActiveSuggestion] = useState(-1);
  const [newCompany, setNewCompany] = useState({
    name: initialValue?.company?.name || '',
    website: initialValue?.company?.website || '',
    industry: initialValue?.company?.industry || '',
    location: initialValue?.company?.location || '',
  });
  const [details, setDetails] = useState({
    ...EMPTY_DETAILS,
    ...(initialValue?.details || {}),
  });
  const [employmentTypeOptions, setEmploymentTypeOptions] = useState([]);
  const [employmentTypesError, setEmploymentTypesError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formError, setFormError] = useState('');
  const [duplicateReview, setDuplicateReview] = useState(null);
  const keyRef = useRef(newIdempotencyKey());
  const attemptedPayloadRef = useRef('');

  useEffect(() => {
    const controller = new AbortController();
    fetch(apiPath('/jobs/filters'), { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error('Failed to load governed Employment Types');
        return response.json();
      })
      .then((payload) => {
        setEmploymentTypeOptions(
          Array.isArray(payload.employment_types) ? payload.employment_types : [],
        );
      })
      .catch((error) => {
        if (error.name !== 'AbortError') setEmploymentTypesError(error.message);
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (companyMode !== 'existing' || selectedCompany || !companySearch.trim()) {
      setCompanySuggestions([]);
      setCompanySearchError('');
      return undefined;
    }
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setIsSearchingCompany(true);
      setCompanySearchError('');
      try {
        const params = new URLSearchParams({
          q: companySearch.trim(), status: 'all', page_size: '10', page: '1',
        });
        const response = await fetch(apiPath(`/companies?${params}`), {
          signal: controller.signal,
        });
        if (!response.ok) throw new Error('Company search failed. Please try again.');
        const payload = await response.json();
        setCompanySuggestions(Array.isArray(payload.items) ? payload.items : []);
        setActiveSuggestion(-1);
      } catch (error) {
        if (error.name !== 'AbortError') {
          setCompanySuggestions([]);
          setCompanySearchError(error.message);
        }
      } finally {
        if (!controller.signal.aborted) setIsSearchingCompany(false);
      }
    }, 300);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [companyMode, companySearch, selectedCompany]);

  const companyChoice = useMemo(() => {
    if (companyMode === 'existing') {
      return selectedCompany
        ? { mode: 'existing', company_id: selectedCompany.id }
        : null;
    }
    return newCompany.name.trim()
      ? {
          mode: 'new',
          name: newCompany.name.trim(),
          website: newCompany.website.trim() || null,
          industry: newCompany.industry.trim() || null,
          location: newCompany.location.trim() || null,
        }
      : null;
  }, [companyMode, newCompany, selectedCompany]);

  const buildPayload = (confirmation = null) => ({
    company: companyChoice,
    title: title.trim(),
    description: description.trim() || null,
    salary_min: details.salaryMin === '' ? null : Number(details.salaryMin),
    salary_max: details.salaryMax === '' ? null : Number(details.salaryMax),
    salary_currency: details.salaryCurrency,
    location: details.location.trim() || null,
    employment_type_codes: details.employmentTypeCodes,
    posted_date: details.postedDate || null,
    experience_min_years: details.experienceMin === '' ? null : Number(details.experienceMin),
    experience_max_years: details.experienceMax === '' ? null : Number(details.experienceMax),
    ...(confirmation ? { duplicate_confirmation: confirmation } : {}),
  });

  const validate = (payload) => {
    if (!payload.title) return 'Job title is required.';
    if (!payload.company) return 'Company is required.';
    if (
      payload.salary_min !== null && payload.salary_max !== null
      && payload.salary_min > payload.salary_max
    ) return 'Salary minimum cannot exceed salary maximum.';
    if (
      payload.experience_min_years !== null && payload.experience_max_years !== null
      && payload.experience_min_years > payload.experience_max_years
    ) return 'Experience minimum cannot exceed experience maximum.';
    return '';
  };

  const submit = async (confirmation = null) => {
    const payload = buildPayload(confirmation);
    const validationError = validate(payload);
    if (validationError) {
      setFormError(validationError);
      return;
    }
    const logicalPayload = JSON.stringify(buildPayload());
    if (attemptedPayloadRef.current && attemptedPayloadRef.current !== logicalPayload) {
      keyRef.current = newIdempotencyKey();
    }
    attemptedPayloadRef.current = logicalPayload;
    setIsSubmitting(true);
    setFormError('');
    try {
      const response = await fetch(apiPath(endpoint), {
        method,
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key': keyRef.current,
        },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok) {
        if (response.status === 409 && data?.detail?.code === 'duplicate_candidates') {
          setDuplicateReview(data.detail);
          return;
        }
        throw new Error(errorMessage(data, `Request failed with status ${response.status}`));
      }
      setDuplicateReview(null);
      onSuccess?.(data);
    } catch (error) {
      setFormError(error.message || 'Failed to save Job. Please try again.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const chooseSuggestion = (company) => {
    setSelectedCompany(company);
    setCompanySearch(company.name);
    setCompanySuggestions([]);
    setActiveSuggestion(-1);
  };

  return (
    <form className="add-job-form glass-panel" onSubmit={(event) => {
      event.preventDefault();
      submit();
    }}>
      <div className="add-job-form-section">
        <h3>Job details</h3>
        <div className="add-job-field">
          <label htmlFor="job-title" className="add-job-label">Job Title *</label>
          <input id="job-title" className="add-job-input" value={title}
            onChange={(event) => setTitle(event.target.value)} disabled={isSubmitting} />
        </div>

        <fieldset className="add-job-company-mode">
          <legend className="add-job-label">Company *</legend>
          <label><input type="radio" name="company-mode" checked={companyMode === 'existing'}
            onChange={() => { setCompanyMode('existing'); setDuplicateReview(null); }} /> Existing Company</label>
          <label><input type="radio" name="company-mode" checked={companyMode === 'new'}
            onChange={() => { setCompanyMode('new'); setDuplicateReview(null); }} /> New Company</label>
        </fieldset>

        {companyMode === 'existing' ? (
          <div className="add-job-field add-job-company-search">
            <label htmlFor="company-search-input" className="add-job-label">Search Company</label>
            <div className="add-job-company-input-wrapper">
              <Search size={16} className="add-job-company-search-icon" />
              <input id="company-search-input" className="add-job-input add-job-company-input"
                value={companySearch} disabled={isSubmitting}
                onChange={(event) => { setCompanySearch(event.target.value); setSelectedCompany(null); }}
                onKeyDown={(event) => {
                  if (!companySuggestions.length) return;
                  if (event.key === 'ArrowDown') {
                    event.preventDefault();
                    setActiveSuggestion((value) => (value + 1) % companySuggestions.length);
                  } else if (event.key === 'ArrowUp') {
                    event.preventDefault();
                    setActiveSuggestion((value) => (value <= 0 ? companySuggestions.length - 1 : value - 1));
                  } else if (event.key === 'Enter' && activeSuggestion >= 0) {
                    event.preventDefault();
                    chooseSuggestion(companySuggestions[activeSuggestion]);
                  }
                }} />
              {isSearchingCompany && <Loader size={16} className="add-job-spinner" />}
            </div>
            {companySearchError && <p className="add-job-field-error" role="alert">{companySearchError}</p>}
            {companySuggestions.length > 0 && !selectedCompany && (
              <ul className="add-job-suggestions" role="listbox" aria-label="Company suggestions">
                {companySuggestions.map((company, index) => (
                  <li key={company.id} role="option" aria-selected={activeSuggestion === index}>
                    <button type="button" className="add-job-suggestion-item"
                      onClick={() => chooseSuggestion(company)}>
                      <span className="add-job-suggestion-name">{company.name}</span>
                      <span className="add-job-suggestion-industry">
                        {getCompanyIndustryDisplay(company).summary}
                        {company.location ? ` · ${company.location}` : ''}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {selectedCompany && <p className="add-job-selected-company">Selected: {selectedCompany.name}</p>}
          </div>
        ) : (
          <div className="add-job-new-company-grid">
            <div className="add-job-field"><label htmlFor="new-company-name" className="add-job-label">Company Name *</label>
              <input id="new-company-name" className="add-job-input" value={newCompany.name}
                onChange={(event) => setNewCompany({ ...newCompany, name: event.target.value })} /></div>
            <div className="add-job-field"><label htmlFor="new-company-website" className="add-job-label">Website</label>
              <input id="new-company-website" className="add-job-input" value={newCompany.website}
                placeholder="example.com" onChange={(event) => setNewCompany({ ...newCompany, website: event.target.value })} /></div>
            <div className="add-job-field"><label htmlFor="new-company-industry" className="add-job-label">Company Industry evidence</label>
              <input id="new-company-industry" className="add-job-input" value={newCompany.industry}
                onChange={(event) => setNewCompany({ ...newCompany, industry: event.target.value })} />
              <p className="add-job-field-note">Free text is stored as Company Industry evidence.</p></div>
            <div className="add-job-field"><label htmlFor="new-company-location" className="add-job-label">Company Location</label>
              <input id="new-company-location" className="add-job-input" value={newCompany.location}
                onChange={(event) => setNewCompany({ ...newCompany, location: event.target.value })} /></div>
          </div>
        )}

        <div className="add-job-field">
          <label htmlFor="job-description" className="add-job-label">Description</label>
          <p className="add-job-field-note">Optional for saving · Required for AI enrichment</p>
          <textarea id="job-description" className="add-job-textarea" rows={7}
            value={description} onChange={(event) => setDescription(event.target.value)} />
        </div>
      </div>

      <details className="add-job-optional-details">
        <summary>Optional job details</summary>
        <div className="add-job-row">
          <div className="add-job-field"><label htmlFor="salary-min" className="add-job-label">Salary Min</label>
            <input id="salary-min" type="number" min="0" className="add-job-input" value={details.salaryMin}
              onChange={(event) => setDetails({ ...details, salaryMin: event.target.value })} /></div>
          <div className="add-job-field"><label htmlFor="salary-max" className="add-job-label">Salary Max</label>
            <input id="salary-max" type="number" min="0" className="add-job-input" value={details.salaryMax}
              onChange={(event) => setDetails({ ...details, salaryMax: event.target.value })} /></div>
          <div className="add-job-field"><label htmlFor="salary-currency" className="add-job-label">Currency</label>
            <select id="salary-currency" className="add-job-select" value={details.salaryCurrency}
              onChange={(event) => setDetails({ ...details, salaryCurrency: event.target.value })}>
              {SALARY_CURRENCIES.map((currency) => <option key={currency} value={currency}>{currency}</option>)}
            </select></div>
        </div>
        <div className="add-job-row">
          <div className="add-job-field"><label htmlFor="job-location" className="add-job-label">Job Location</label>
            <input id="job-location" className="add-job-input" value={details.location}
              onChange={(event) => setDetails({ ...details, location: event.target.value })} /></div>
          <div className="add-job-field"><label htmlFor="posted-date" className="add-job-label">Posted Date</label>
            <input id="posted-date" type="date" className="add-job-input" value={details.postedDate}
              onChange={(event) => setDetails({ ...details, postedDate: event.target.value })} /></div>
        </div>
        <div className="add-job-field">
          <label htmlFor="employment-types" className="add-job-label">Employment Types</label>
          <select id="employment-types" className="add-job-select add-job-multi-select" multiple
            aria-label="Employment Types" value={details.employmentTypeCodes}
            onChange={(event) => setDetails({ ...details, employmentTypeCodes: Array.from(event.target.selectedOptions, (option) => option.value) })}>
            {employmentTypeOptions.map((option) => <option key={option.code} value={option.code}>{option.label}</option>)}
          </select>
          {employmentTypesError && <p className="add-job-field-error" role="status">{employmentTypesError}</p>}
        </div>
        <div className="add-job-row">
          <div className="add-job-field"><label htmlFor="exp-min" className="add-job-label">Exp. Min (years)</label>
            <input id="exp-min" type="number" min="0" className="add-job-input" value={details.experienceMin}
              onChange={(event) => setDetails({ ...details, experienceMin: event.target.value })} /></div>
          <div className="add-job-field"><label htmlFor="exp-max" className="add-job-label">Exp. Max (years)</label>
            <input id="exp-max" type="number" min="0" className="add-job-input" value={details.experienceMax}
              onChange={(event) => setDetails({ ...details, experienceMax: event.target.value })} /></div>
        </div>
      </details>

      {duplicateReview && (
        <div className="add-job-duplicate-review" role="alert">
          <AlertCircle size={18} />
          <div>
            <strong>Possible duplicate found</strong>
            <p>Review the matching Company or Job before deliberately creating another record.</p>
            {(duplicateReview.company_candidates || []).map((item) => <p key={item.id}>Company: {item.name}</p>)}
            {(duplicateReview.job_candidates || []).map((item) => <p key={item.id}>Job: {item.title}</p>)}
            <button type="button" onClick={() => submit(duplicateReview.confirmation)} disabled={isSubmitting}>
              Add anyway
            </button>
          </div>
        </div>
      )}
      {formError && <p className="add-job-field-error" role="alert">{formError}</p>}
      <div className="add-job-form-actions">
        {onCancel && <button type="button" className="add-job-add-company-cancel" onClick={onCancel}>Cancel</button>}
        <button type="submit" className="add-job-submit-button" disabled={isSubmitting}>
          {isSubmitting ? <><Loader size={16} className="add-job-spinner" /> Saving…</> : submitLabel}
        </button>
      </div>
    </form>
  );
}
