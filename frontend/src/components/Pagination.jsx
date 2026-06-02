import React from 'react';
import PaginationControl from './PaginationControl';

function Pagination({ page, totalPages, total, onPageChange, isLoading }) {
    return (
        <PaginationControl
            page={page}
            totalPages={totalPages}
            totalItems={total}
            isLoading={isLoading}
            onPageChange={onPageChange}
            summaryText={`Page ${page} of ${totalPages} (${total} jobs)`}
            hideWhenSinglePage
        />
    );
}

export default Pagination;
