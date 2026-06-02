import React, { useEffect, useId, useState } from 'react';

function PaginationControl({
    page,
    totalPages,
    totalItems,
    summaryText,
    isLoading,
    onPageChange,
    hideWhenSinglePage = false,
}) {
    const [draftPage, setDraftPage] = useState(String(page));
    const inputId = useId();

    useEffect(() => {
        setDraftPage(String(page));
    }, [page]);

    const safeTotalPages = Math.max(totalPages || 1, 1);
    const resolvedSummaryText =
        summaryText ?? `Page ${page} of ${safeTotalPages} (${totalItems ?? 0} items)`;

    const submitDraftPage = () => {
        const trimmedDraftPage = draftPage.trim();

        if (!trimmedDraftPage) {
            return;
        }

        const nextPage = Number.parseInt(trimmedDraftPage, 10);

        if (Number.isNaN(nextPage)) {
            return;
        }

        const clampedPage = Math.min(Math.max(nextPage, 1), safeTotalPages);

        setDraftPage(String(clampedPage));

        if (clampedPage === page) {
            return;
        }

        onPageChange(clampedPage);
    };

    const handlePreviousPage = () => {
        if (page <= 1 || isLoading) {
            return;
        }

        onPageChange(page - 1);
    };

    const handleNextPage = () => {
        if (page >= safeTotalPages || isLoading) {
            return;
        }

        onPageChange(page + 1);
    };

    const handleDraftPageKeyDown = (event) => {
        if (event.key !== 'Enter') {
            return;
        }

        event.preventDefault();
        submitDraftPage();
    };

    if (hideWhenSinglePage && safeTotalPages <= 1) {
        return null;
    }

    return (
        <div className="pagination">
            <span className="pagination-info">{resolvedSummaryText}</span>
            <div className="pagination-controls">
                <button
                    type="button"
                    onClick={handlePreviousPage}
                    disabled={page <= 1 || isLoading}
                >
                    Previous
                </button>
                <div className="pagination-jump">
                    <label className="pagination-jump-label" htmlFor={inputId}>
                        Jump to page
                    </label>
                    <input
                        id={inputId}
                        type="number"
                        min="1"
                        max={safeTotalPages}
                        inputMode="numeric"
                        value={draftPage}
                        onChange={(event) => setDraftPage(event.target.value)}
                        onKeyDown={handleDraftPageKeyDown}
                        disabled={isLoading}
                    />
                    <button
                        type="button"
                        onClick={submitDraftPage}
                        disabled={isLoading}
                    >
                        Go
                    </button>
                </div>
                <button
                    type="button"
                    onClick={handleNextPage}
                    disabled={page >= safeTotalPages || isLoading}
                >
                    Next
                </button>
            </div>
        </div>
    );
}

export default PaginationControl;
