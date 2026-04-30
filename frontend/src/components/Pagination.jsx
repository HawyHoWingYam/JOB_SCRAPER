import React from 'react';

function Pagination({ page, totalPages, total, onPageChange, isLoading }) {
    const handlePrev = () => {
        if (page > 1) onPageChange(page - 1);
    };

    const handleNext = () => {
        if (page < totalPages) onPageChange(page + 1);
    };

    if (totalPages <= 1) return null;

    return (
        <div className="pagination">
            <span className="pagination-info">
                Page {page} of {totalPages} ({total} jobs)
            </span>
            <div className="pagination-controls">
                <button
                    onClick={handlePrev}
                    disabled={page <= 1 || isLoading}
                >
                    Previous
                </button>
                <button
                    onClick={handleNext}
                    disabled={page >= totalPages || isLoading}
                >
                    Next
                </button>
            </div>
        </div>
    );
}

export default Pagination;
