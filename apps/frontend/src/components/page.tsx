// apps/frontend/src/app/jobs/page.tsx
import React from 'react';
import { fetchJobs } from '@/services/jobs';
import JobCard from '@/components/JobCard';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export default async function JobsPage() {
  const jobs = await fetchJobs();
  
  return (
    <div className="max-w-4xl mx-auto p-4">
      <h1 className="text-2xl font-bold mb-6">Job Listings</h1>
      
      {jobs.length === 0 ? (
        <div className="text-center py-10">
          <p className="text-gray-500">No job listings found.</p>
        </div>
      ) : (
        <div>
          <p className="text-gray-500 mb-4">Found {jobs.length} job listings</p>
          <div className="space-y-4">
            {jobs.map((job) => (
              <JobCard key={job.id} job={job} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}