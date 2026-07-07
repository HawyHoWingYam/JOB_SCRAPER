import React, { useCallback, useEffect, useRef, useState } from 'react';
import { PlusCircle, Sparkles, Search, X, Loader, CheckCircle, AlertCircle } from 'lucide-react';
import { apiPath } from '../../api/base';
import './AddJobPage.css';

function AddJobPage() {
  // Form state
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [salaryRange, setSalaryRange] = useState('');
  const [salaryMin, setSalaryMin] = useState('');
  const [salaryMax, setSalaryMax] = useState('');
  const [salaryCurrency, setSalaryCurrency] = useState('HKD');
  const [location, setLocation] = useState('');
  const [employmentType, setEmploymentType] = useState('');
  const [postedDate, setPostedDate] = useState('');
  const [experienceMin, setExperienceMin] = useState('');
  const [experienceMax, setExperienceMax] = useState('');

  // Company autocomplete state
  const [companySearch, setCompanySearch] = useState('');
  const [companySuggestions, setCompanySuggestions] = useState([]);
  const [selectedCompany, setSelectedCompany] = useState(null);
  const [isSearchingCompany, setIsSearchingCompany] = useState(false);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [showAddCompanyForm, setShowAddCompanyForm] = useState(false);
  const [showAddCompanyOption, setShowAddCompanyOption] = useState(false);
  const [newCompanyIndustry, setNewCompanyIndustry] = useState('');
  const [newCompanyLocation, setNewCompanyLocation] = useState('');
  const [isCreatingCompany, setIsCreatingCompany] = useState(false);
  const [companyCreateError, setCompanyCreateError] = useState('');
  const searchTimeoutRef = useRef(null);
  const suggestionsRef = useRef(null);

  // Submission state
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isEnriching, setIsEnriching] = useState(false);
  const [submitResult, setSubmitResult] = useState(null); // { type: 'success'|'error', message }
  const [createdJob, setCreatedJob] = useState(null);

  const mountedRef = useRef(true);

  // Debounced company search
  const searchCompany = useCallback(async (query) => {
    if (!query || query.trim().length < 1) {
      setCompanySuggestions([]);
      setShowSuggestions(false);
      return;
    }

    setIsSearchingCompany(true);
    try {
      const params = new URLSearchParams();
      params.append('q', query.trim());
      params.append('status', 'all');
      params.append('page_size', '10');
      params.append('page', '1');

      const response = await fetch(apiPath('/companies?' + params.toString()));
      if (!response.ok) {
        throw new Error('Failed to search companies');
      }

      const payload = await response.json();
      if (!mountedRef.current) return;

      const hasResults = (payload.items || []).length > 0;
      setCompanySuggestions(payload.items || []);
      setShowSuggestions(hasResults);
      setShowAddCompanyOption(!hasResults);
      setShowAddCompanyForm(false);
    } catch (err) {
      if (!mountedRef.current) return;
      setCompanySuggestions([]);
      setShowSuggestions(false);
      setShowAddCompanyOption(false);
    } finally {
      if (mountedRef.current) {
        setIsSearchingCompany(false);
      }
    }
  }, []);

  const handleCompanyInputChange = (value) => {
    setCompanySearch(value);
    // Clear selected company when user types
    if (selectedCompany) {
      setSelectedCompany(null);
    }
    setShowAddCompanyOption(false);
    setShowAddCompanyForm(false);

    // Debounce search
    if (searchTimeoutRef.current) {
      clearTimeout(searchTimeoutRef.current);
    }

    if (value.trim().length > 0) {
      searchTimeoutRef.current = setTimeout(() => {
        searchCompany(value.trim());
      }, 300);
    } else {
      setCompanySuggestions([]);
      setShowSuggestions(false);
    }
  };

  const handleSelectCompany = (company) => {
    setSelectedCompany(company);
    setCompanySearch(company.name);
    setShowSuggestions(false);
    setCompanySuggestions([]);
  };

  const handleClearCompany = () => {
    setSelectedCompany(null);
    setCompanySearch('');
    setCompanySuggestions([]);
    setShowSuggestions(false);
    setShowAddCompanyOption(false);
    setShowAddCompanyForm(false);
  };

  // Click outside to close suggestions
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (suggestionsRef.current && !suggestionsRef.current.contains(event.target)) {
        setShowSuggestions(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const handleCreateCompany = async () => {
    if (!companySearch.trim()) return;
    setIsCreatingCompany(true);
    setCompanyCreateError('');

    try {
      const response = await fetch(apiPath('/companies'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: companySearch.trim(),
          industry: newCompanyIndustry.trim() || null,
          location: newCompanyLocation.trim() || null,
        }),
      });

      const data = await response.json();
      if (!response.ok) {
        const errorMsg = data?.detail || data?.message || 'Failed to create company';
        throw new Error(typeof errorMsg === 'string' ? errorMsg : JSON.stringify(errorMsg));
      }

      // Success — auto-select the newly created company
      setSelectedCompany(data);
      setCompanySearch(data.name);
      setShowAddCompanyForm(false);
      setShowAddCompanyOption(false);
      setNewCompanyIndustry('');
      setNewCompanyLocation('');
      setCompanyCreateError('');
    } catch (err) {
      setCompanyCreateError(err.message || 'Failed to create company');
    } finally {
      setIsCreatingCompany(false);
    }
  };

  const resetForm = () => {
    setTitle('');
    setDescription('');
    setSalaryRange('');
    setSalaryMin('');
    setSalaryMax('');
    setSalaryCurrency('HKD');
    setLocation('');
    setEmploymentType('');
    setPostedDate('');
    setExperienceMin('');
    setExperienceMax('');
    setCompanySearch('');
    setSelectedCompany(null);
    setCompanySuggestions([]);
    setShowSuggestions(false);
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    setSubmitResult(null);
    setCreatedJob(null);

    // Validation
    if (!title.trim()) {
      setSubmitResult({ type: 'error', message: 'Job title is required.' });
      return;
    }

    if (!selectedCompany) {
      setSubmitResult({ type: 'error', message: 'Please select a company.' });
      return;
    }

    // Build payload matching ManualJobCreateSchema
    const payload = {
      company_id: selectedCompany.id,
      title: title.trim(),
      description: description.trim() || null,
      salary_range: salaryRange.trim() || null,
      salary_min: salaryMin.trim() ? Number(salaryMin) : null,
      salary_max: salaryMax.trim() ? Number(salaryMax) : null,
      salary_currency: salaryCurrency || 'HKD',
      location: location.trim() || null,
      employment_type: employmentType.trim() || null,
      posted_date: postedDate || null,
      experience_min_years: experienceMin.trim() ? Number(experienceMin) : null,
      experience_max_years: experienceMax.trim() ? Number(experienceMax) : null,
    };

    setIsSubmitting(true);
    setIsEnriching(false);

    try {
      const response = await fetch(apiPath('/jobs/manual'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      const data = await response.json();

      if (!response.ok) {
        const errorMsg = data?.detail || data?.message || `Request failed with status ${response.status}`;
        throw new Error(typeof errorMsg === 'string' ? errorMsg : JSON.stringify(errorMsg));
      }

      // Success — job was created and enriched
      setCreatedJob(data);
      setSubmitResult({
        type: 'success',
        message: `Job "${data.title}" created successfully with AI enrichment!`,
      });
    } catch (err) {
      setSubmitResult({
        type: 'error',
        message: err.message || 'Failed to create job. Please try again.',
      });
    } finally {
      setIsSubmitting(false);
      setIsEnriching(false);
    }
  };

  const EMPLOYMENT_TYPES = [
    'Full-time',
    'Part-time',
    'Contract',
    'Temporary',
    'Internship',
    'Freelance',
  ];

  return (
    <div className="add-job-page">
      <section className="add-job-hero glass-panel">
        <div className="add-job-hero-copy">
          <p className="add-job-eyebrow">Manual Entry</p>
          <h2>Add Job</h2>
          <p className="add-job-subtitle">
            Create a new job listing manually. AI enrichment will run automatically.
          </p>
        </div>
      </section>

      {submitResult && (
        <div className={`add-job-result glass-panel ${submitResult.type}`}>
          {submitResult.type === 'success' ? (
            <CheckCircle size={20} />
          ) : (
            <AlertCircle size={20} />
          )}
          <span>{submitResult.message}</span>
          {submitResult.type === 'success' && (
            <button
              className="add-job-reset-button"
              onClick={() => {
                resetForm();
                setSubmitResult(null);
                setCreatedJob(null);
              }}
            >
              Add another job
            </button>
          )}
        </div>
      )}

      {createdJob && submitResult?.type === 'success' && (
        <div className="add-job-summary glass-panel">
          <h3>Job Summary</h3>
          <div className="add-job-summary-grid">
            <div className="add-job-summary-field">
              <span className="add-job-summary-label">Title</span>
              <span className="add-job-summary-value">{createdJob.title}</span>
            </div>
            <div className="add-job-summary-field">
              <span className="add-job-summary-label">Company</span>
              <span className="add-job-summary-value">{createdJob.company_name || selectedCompany?.name}</span>
            </div>
            {createdJob.ai_summary && (
              <div className="add-job-summary-field add-job-summary-full">
                <span className="add-job-summary-label">AI Summary</span>
                <span className="add-job-summary-value">{createdJob.ai_summary}</span>
              </div>
            )}
            {createdJob.job_taxonomy && (
              <div className="add-job-summary-field">
                <span className="add-job-summary-label">Classification</span>
                <span className="add-job-summary-value">{createdJob.job_taxonomy.path}</span>
              </div>
            )}
            {createdJob.skills?.length > 0 && (
              <div className="add-job-summary-field add-job-summary-full">
                <span className="add-job-summary-label">Skills</span>
                <div className="add-job-summary-skills">
                  {createdJob.skills.map((skill, i) => (
                    <span key={i} className="add-job-skill-tag">{skill}</span>
                  ))}
                </div>
              </div>
            )}
            {createdJob.experience_level && (
              <div className="add-job-summary-field">
                <span className="add-job-summary-label">Experience Level</span>
                <span className="add-job-summary-value">{createdJob.experience_level}</span>
              </div>
            )}
          </div>
        </div>
      )}

      {!createdJob && (
        <form className="add-job-form glass-panel" onSubmit={handleSubmit}>
          <div className="add-job-form-section">
            <h3>Basic Information</h3>

            <div className="add-job-field">
              <label htmlFor="job-title" className="add-job-label">
                Job Title <span className="add-job-required">*</span>
              </label>
              <input
                id="job-title"
                className="add-job-input"
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="e.g. Senior Software Engineer"
                disabled={isSubmitting}
                required
              />
            </div>

            <div className="add-job-field">
              <label htmlFor="company-search-input" className="add-job-label">
                Company <span className="add-job-required">*</span>
              </label>
              <div className="add-job-company-search" ref={suggestionsRef}>
                <div className="add-job-company-input-wrapper">
                  <Search size={16} className="add-job-company-search-icon" />
                  <input
                    id="company-search-input"
                    className="add-job-input add-job-company-input"
                    type="text"
                    value={companySearch}
                    onChange={(e) => handleCompanyInputChange(e.target.value)}
                    onFocus={() => {
                      if (companySuggestions.length > 0 && !selectedCompany) {
                        setShowSuggestions(true);
                      }
                    }}
                    placeholder="Search company name..."
                    disabled={isSubmitting}
                  />
                  {isSearchingCompany && <Loader size={16} className="add-job-spinner" />}
                  {selectedCompany && (
                    <button
                      type="button"
                      className="add-job-company-clear"
                      onClick={handleClearCompany}
                      aria-label="Clear company selection"
                    >
                      <X size={16} />
                    </button>
                  )}
                </div>
                {showSuggestions && companySuggestions.length > 0 && (
                  <ul className="add-job-suggestions" role="listbox" aria-label="Company suggestions">
                    {companySuggestions.map((company) => (
                      <li
                        key={company.id}
                        className="add-job-suggestion-item"
                        role="option"
                        aria-selected={selectedCompany?.id === company.id}
                        onClick={() => handleSelectCompany(company)}
                      >
                        <div className="add-job-suggestion-name">{company.name}</div>
                        {company.industry && (
                          <div className="add-job-suggestion-industry">{company.industry}</div>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
                {showAddCompanyOption && !selectedCompany && !showAddCompanyForm && (
                  <div className="add-job-suggestions">
                    <div
                      className="add-job-add-company-option"
                      onClick={() => {
                        setShowAddCompanyForm(true);
                        setShowAddCompanyOption(false);
                      }}
                      role="button"
                      tabIndex={0}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          setShowAddCompanyForm(true);
                          setShowAddCompanyOption(false);
                        }
                      }}
                    >
                      <PlusCircle size={16} />
                      <span>Can't find "<strong>{companySearch}</strong>"? Add a new company</span>
                    </div>
                  </div>
                )}
                {showAddCompanyForm && !selectedCompany && (
                  <div className="add-job-add-company-form">
                    <h4 className="add-job-add-company-title">New Company</h4>
                    <div className="add-job-field">
                      <label className="add-job-label">Name</label>
                      <input
                        className="add-job-input"
                        type="text"
                        value={companySearch}
                        disabled
                      />
                    </div>
                    <div className="add-job-field">
                      <label className="add-job-label" htmlFor="new-company-industry">Industry</label>
                      <input
                        id="new-company-industry"
                        className="add-job-input"
                        type="text"
                        value={newCompanyIndustry}
                        onChange={(e) => setNewCompanyIndustry(e.target.value)}
                        placeholder="e.g. Information Technology"
                        disabled={isCreatingCompany}
                      />
                    </div>
                    <div className="add-job-field">
                      <label className="add-job-label" htmlFor="new-company-location">Location</label>
                      <input
                        id="new-company-location"
                        className="add-job-input"
                        type="text"
                        value={newCompanyLocation}
                        onChange={(e) => setNewCompanyLocation(e.target.value)}
                        placeholder="e.g. Hong Kong"
                        disabled={isCreatingCompany}
                      />
                    </div>
                    {companyCreateError && (
                      <p className="add-job-add-company-error">{companyCreateError}</p>
                    )}
                    <div className="add-job-add-company-actions">
                      <button
                        type="button"
                        className="add-job-add-company-submit"
                        onClick={handleCreateCompany}
                        disabled={isCreatingCompany}
                      >
                        {isCreatingCompany ? (
                          <>
                            <Loader size={14} className="add-job-spinner" />
                            <span>Creating...</span>
                          </>
                        ) : (
                          <>
                            <PlusCircle size={14} />
                            <span>Create Company</span>
                          </>
                        )}
                      </button>
                      <button
                        type="button"
                        className="add-job-add-company-cancel"
                        onClick={() => {
                          setShowAddCompanyForm(false);
                          setShowAddCompanyOption(true);
                        }}
                        disabled={isCreatingCompany}
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                )}
              </div>
              {selectedCompany && (
                <div className="add-job-selected-company">
                  <span className="add-job-selected-company-name">{selectedCompany.name}</span>
                  {selectedCompany.industry && (
                    <span className="add-job-selected-company-industry">{selectedCompany.industry}</span>
                  )}
                </div>
              )}
            </div>

            <div className="add-job-field">
              <label htmlFor="job-description" className="add-job-label">
                Description
              </label>
              <textarea
                id="job-description"
                className="add-job-textarea"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Job description text..."
                rows={6}
                disabled={isSubmitting}
              />
            </div>
          </div>

          <div className="add-job-form-section">
            <h3>Compensation & Location</h3>

            <div className="add-job-row">
              <div className="add-job-field add-job-field-sm">
                <label htmlFor="salary-min" className="add-job-label">Salary Min</label>
                <input
                  id="salary-min"
                  className="add-job-input"
                  type="number"
                  value={salaryMin}
                  onChange={(e) => setSalaryMin(e.target.value)}
                  placeholder="e.g. 30000"
                  disabled={isSubmitting}
                  min="0"
                />
              </div>
              <div className="add-job-field add-job-field-sm">
                <label htmlFor="salary-max" className="add-job-label">Salary Max</label>
                <input
                  id="salary-max"
                  className="add-job-input"
                  type="number"
                  value={salaryMax}
                  onChange={(e) => setSalaryMax(e.target.value)}
                  placeholder="e.g. 50000"
                  disabled={isSubmitting}
                  min="0"
                />
              </div>
              <div className="add-job-field add-job-field-xs">
                <label htmlFor="salary-currency" className="add-job-label">Currency</label>
                <select
                  id="salary-currency"
                  className="add-job-select"
                  value={salaryCurrency}
                  onChange={(e) => setSalaryCurrency(e.target.value)}
                  disabled={isSubmitting}
                >
                  <option value="HKD">HKD</option>
                  <option value="USD">USD</option>
                  <option value="CNY">CNY</option>
                  <option value="SGD">SGD</option>
                  <option value="TWD">TWD</option>
                </select>
              </div>
            </div>

            <div className="add-job-field">
              <label htmlFor="salary-range" className="add-job-label">
                Salary Range (display)
              </label>
              <input
                id="salary-range"
                className="add-job-input"
                type="text"
                value={salaryRange}
                onChange={(e) => setSalaryRange(e.target.value)}
                placeholder="e.g. HK$30,000 - HK$50,000 / month"
                disabled={isSubmitting}
              />
            </div>

            <div className="add-job-row">
              <div className="add-job-field add-job-field-lg">
                <label htmlFor="job-location" className="add-job-label">Location</label>
                <input
                  id="job-location"
                  className="add-job-input"
                  type="text"
                  value={location}
                  onChange={(e) => setLocation(e.target.value)}
                  placeholder="e.g. Hong Kong"
                  disabled={isSubmitting}
                />
              </div>
              <div className="add-job-field add-job-field-md">
                <label htmlFor="employment-type" className="add-job-label">Employment Type</label>
                <select
                  id="employment-type"
                  className="add-job-select"
                  value={employmentType}
                  onChange={(e) => setEmploymentType(e.target.value)}
                  disabled={isSubmitting}
                >
                  <option value="">-- Select --</option>
                  {EMPLOYMENT_TYPES.map((type) => (
                    <option key={type} value={type}>{type}</option>
                  ))}
                </select>
              </div>
            </div>
          </div>

          <div className="add-job-form-section">
            <h3>Additional Details</h3>

            <div className="add-job-row">
              <div className="add-job-field add-job-field-md">
                <label htmlFor="posted-date" className="add-job-label">Posted Date</label>
                <input
                  id="posted-date"
                  className="add-job-input"
                  type="date"
                  value={postedDate}
                  onChange={(e) => setPostedDate(e.target.value)}
                  disabled={isSubmitting}
                />
              </div>
              <div className="add-job-field add-job-field-sm">
                <label htmlFor="exp-min" className="add-job-label">Exp. Min (years)</label>
                <input
                  id="exp-min"
                  className="add-job-input"
                  type="number"
                  value={experienceMin}
                  onChange={(e) => setExperienceMin(e.target.value)}
                  placeholder="e.g. 3"
                  disabled={isSubmitting}
                  min="0"
                />
              </div>
              <div className="add-job-field add-job-field-sm">
                <label htmlFor="exp-max" className="add-job-label">Exp. Max (years)</label>
                <input
                  id="exp-max"
                  className="add-job-input"
                  type="number"
                  value={experienceMax}
                  onChange={(e) => setExperienceMax(e.target.value)}
                  placeholder="e.g. 8"
                  disabled={isSubmitting}
                  min="0"
                />
              </div>
            </div>
          </div>

          <div className="add-job-form-actions">
            <button
              type="submit"
              className="add-job-submit-button"
              disabled={isSubmitting || !title.trim() || !selectedCompany}
            >
              {isSubmitting ? (
                <>
                  <Loader size={16} className="add-job-spinner" />
                  <span>{isEnriching ? 'Running AI Enrichment...' : 'Creating Job...'}</span>
                </>
              ) : (
                <>
                  <Sparkles size={16} />
                  <span>Create Job & Enrich</span>
                </>
              )}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

export default AddJobPage;
