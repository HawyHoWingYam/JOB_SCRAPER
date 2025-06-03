// apps/frontend/src/components/JobCard.tsx
import React from 'react';
import { Job } from '@/types/job';
import Link from 'next/link';

interface JobCardProps {
  job: Job;
}

const JobCard: React.FC<JobCardProps> = ({ job }) => {
  return (
    <div className="border rounded-lg p-4 shadow-sm hover:shadow-md transition-shadow bg-white mb-4">
      <Link href={`/jobs/${job.id}`} className="block">
        <h2 className="text-lg font-semibold text-blue-700 mb-1">{job.name || 'Unnamed Position'}</h2>
        <p className="text-gray-700 font-medium mb-1">{job.companyName || 'Unknown Company'}</p>
        <div className="flex items-center text-gray-500 text-sm mb-2">
          {job.location && (
            <span className="mr-3">
              📍 {job.location}
            </span>
          )}
          {job.workType && (
            <span className="mr-3">
              💼 {job.workType}
            </span>
          )}
          {job.datePosted && (
            <span>
              📅 Posted: {job.datePosted}
            </span>
          )}
        </div>
        {job.salaryDescription && (
          <p className="text-green-600 text-sm font-medium">
            💰 {job.salaryDescription}
          </p>
        )}
      </Link>
    </div>
  );
};

export default JobCard;