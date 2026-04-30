import React from 'react';

function CompanyDetailModal({ company, statusLabel, statusClassName, descriptionText, onClose }) {
    const handleOverlayClick = (event) => {
        if (event.target.className === 'modal-overlay') {
            onClose();
        }
    };

    if (!company) {
        return null;
    }

    return (
        <div className="modal-overlay" onClick={handleOverlayClick}>
            <div className="modal-content company-detail-modal" role="dialog" aria-modal="true" aria-labelledby="company-detail-title">
                <button type="button" className="modal-close" onClick={onClose} aria-label="Close company details">
                    ×
                </button>

                <div className="modal-header">
                    <h2 id="company-detail-title">{company.name}</h2>
                    <p className="modal-company">{company.industry || 'Industry unavailable'}</p>
                    <p className="modal-location">{company.location || 'Location unavailable'}</p>
                </div>

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
