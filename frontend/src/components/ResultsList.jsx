import React, { useState } from 'react';

function ResultsList({ results }) {
    const [currentPage, setCurrentPage] = useState(1);
    const pageSize = 20;

    if (!results) return null;

    if (results.length === 0) {
        return (
            <div className="results-container">
                <p className="no-results">No jobs found. Try different keywords.</p>
            </div>
        );
    }

    // Calculate pagination
    const totalPages = Math.ceil(results.length / pageSize);
    const startIndex = (currentPage - 1) * pageSize;
    const endIndex = startIndex + pageSize;
    const currentJobs = results.slice(startIndex, endIndex);

    const handlePrevPage = () => {
        if (currentPage > 1) setCurrentPage(currentPage - 1);
    };

    const handleNextPage = () => {
        if (currentPage < totalPages) setCurrentPage(currentPage + 1);
    };

    return (
        <div className="results-container">
            <h3>Found {results.length} Jobs (Showing {startIndex + 1}-{Math.min(endIndex, results.length)})</h3>
            <div className="jobs-list">
                {currentJobs.map((job) => (
                    <div key={job.external_id} className="job-card">
                        <div className="job-header">
                            <h4 className="job-title">
                                <a href={job.job_url} target="_blank" rel="noopener noreferrer">
                                    {job.title}
                                </a>
                            </h4>
                            <span className="job-company">{job.company_name}</span>
                        </div>

                        <div className="job-meta">
                            {job.location && (
                                <span className="job-location">{job.location}</span>
                            )}
                            {job.salary_label && (
                                <span className="job-salary">{job.salary_label}</span>
                            )}
                        </div>

                        {job.work_types && job.work_types.length > 0 && (
                            <div className="job-tags">
                                {job.work_types.map((type, idx) => (
                                    <span key={idx} className="job-tag">{type}</span>
                                ))}
                                {job.work_arrangements && (
                                    <span className="job-tag">{job.work_arrangements}</span>
                                )}
                            </div>
                        )}

                        {job.teaser && (
                            <p className="job-teaser">{job.teaser}</p>
                        )}

                        {job.listing_date && (
                            <span className="job-date">
                                Posted: {new Date(job.listing_date).toLocaleDateString()}
                            </span>
                        )}
                    </div>
                ))}
            </div>

            {totalPages > 1 && (
                <div className="pagination">
                    <span className="pagination-info">
                        Page {currentPage} of {totalPages}
                    </span>
                    <div className="pagination-controls">
                        <button onClick={handlePrevPage} disabled={currentPage <= 1}>
                            Previous
                        </button>
                        <button onClick={handleNextPage} disabled={currentPage >= totalPages}>
                            Next
                        </button>
                    </div>
                </div>
            )}
        </div>
    );
}

export default ResultsList;
