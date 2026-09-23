import React, { useState } from 'react';
import { CheckCircle } from 'lucide-react';

import ManualJobForm from './ManualJobForm';
import './AddJobPage.css';

export default function AddJobPage() {
  const [createdJob, setCreatedJob] = useState(null);

  return (
    <div className="add-job-page">
      <section className="add-job-hero glass-panel">
        <div className="add-job-hero-copy">
          <p className="add-job-eyebrow">Manual Entry</p>
          <h2>Add Job</h2>
          <p className="add-job-subtitle">
            Enter a job and its company details. After saving, you can enrich it from the AI Enrichment page.
          </p>
        </div>
      </section>

      {createdJob ? (
        <div className="add-job-result glass-panel success" role="status">
          <CheckCircle size={20} />
          <span>Job “{createdJob.title}” was added successfully.</span>
          <button type="button" className="add-job-reset-button" onClick={() => setCreatedJob(null)}>
            Add another Job
          </button>
          <a href="#ai">Open AI Enrichment</a>
          <a href="#jobs">Browse jobs</a>
        </div>
      ) : (
        <ManualJobForm onSuccess={setCreatedJob} />
      )}
    </div>
  );
}
