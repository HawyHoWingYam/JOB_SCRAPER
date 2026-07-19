import React from 'react';
import { getCompanyIndustryDisplay } from './companyIndustryDisplay';

function CompanySummaryCard({ company, status, statusLabel, onClick }) {
    const industryDisplay = getCompanyIndustryDisplay(company);

    return (
        <button
            type="button"
            className="company-card glass-panel"
            onClick={onClick}
            aria-label={`Open details for ${company.name}`}
        >
            <div className="company-card-header">
                <div>
                    <h3>{company.name}</h3>
                    <p className="company-card-industry">{industryDisplay.summary}</p>
                </div>
                <span className={`company-status-pill ${status}`}>{statusLabel}</span>
            </div>
        </button>
    );
}

export default CompanySummaryCard;
