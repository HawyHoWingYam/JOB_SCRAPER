import React from 'react';
import { X } from 'lucide-react';
import { governanceHash } from '../jobIntelligence/governanceRoute';
import {
    formatCompanyIndustryBreadcrumb,
    getCompanyIndustryDisplay,
} from './companyIndustryDisplay';

function humanizeIndustryValue(value) {
    return value
        ? String(value).replace(/[_-]+/g, ' ').replace(/\b\w/g, (character) => character.toUpperCase())
        : 'Unknown';
}

function CompanyDetailModal({ company, statusLabel, statusClassName, descriptionText, onClose }) {
    const handleOverlayClick = (event) => {
        if (event.target.className === 'modal-overlay') {
            onClose();
        }
    };

    if (!company) {
        return null;
    }

    const industryDisplay = getCompanyIndustryDisplay(company);
    const reviewItems = Array.isArray(company.company_industries?.review_item_refs)
        ? company.company_industries.review_item_refs
        : [];

    return (
        <div className="modal-overlay" onClick={handleOverlayClick}>
            <div className="modal-content company-detail-modal" role="dialog" aria-modal="true" aria-labelledby="company-detail-title">
                <button type="button" className="modal-close" onClick={onClose} aria-label="Close company details">
                    <X size={18} />
                </button>

                <div className="modal-header">
                    <h2 id="company-detail-title">{company.name}</h2>
                    <p className="modal-company">{industryDisplay.summary}</p>
                    <p className="modal-location">{company.location || 'Location unavailable'}</p>
                </div>

                <section className="modal-section company-industry-section" aria-labelledby="company-detail-industries">
                    <h3 id="company-detail-industries">Company Industries</h3>
                    {industryDisplay.state === 'unavailable' ? (
                        <p className="company-industry-empty">
                            Unavailable ({industryDisplay.unavailableCode})
                        </p>
                    ) : industryDisplay.assignments.length > 0 ? (
                        <ul className="company-industry-list">
                            {industryDisplay.assignments.map((assignment) => (
                                <li key={assignment.id}>
                                    <strong>{formatCompanyIndustryBreadcrumb(assignment.breadcrumb)}</strong>
                                    <span>
                                        {assignment.is_primary
                                            ? 'Primary Company Industry'
                                            : 'Additional Company Industry'}
                                    </span>
                                    <span>
                                        Basis: {humanizeIndustryValue(assignment.primary_basis || assignment.method)}
                                    </span>
                                </li>
                            ))}
                        </ul>
                    ) : (
                        <p className="company-industry-empty">No governed Company Industry assignment</p>
                    )}
                    <div className="company-industry-links">
                        <a href={governanceHash('company-industries')}>
                            Open Company Industries
                        </a>
                        {reviewItems.map((review) => (
                            <a
                                key={review.id}
                                href={governanceHash('company-industries', review.id)}
                            >
                                Open Industry review item
                            </a>
                        ))}
                    </div>
                </section>

                <div className="company-detail-meta">
                    <div className="modal-section">
                        <h3>Company ID</h3>
                        <p>{company.company_id}</p>
                    </div>
                    <div className="modal-section company-detail-status">
                        <h3>Status</h3>
                        <span className={`company-status-pill ${statusClassName}`}>{statusLabel}</span>
                    </div>
                </div>

                <div className="modal-section">
                    <h3>AI Description</h3>
                    <div className="modal-description">
                        <p>{descriptionText}</p>
                    </div>
                </div>
            </div>
        </div>
    );
}

export default CompanyDetailModal;
