// apps/frontend/src/app/jobs/[id]/page.tsx
import React from 'react';
import Link from 'next/link';
import { fetchJobById } from '@/services/jobs';
import { notFound } from 'next/navigation';

// Define the params type correctly for Next.js App Router
type Params = {
  id: string;
};

// Define the component props correctly
type PageProps = {
  params: Params;
  searchParams: { [key: string]: string | string[] | undefined };
};

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export default async function JobDetailPage({ params }: PageProps) {
  const jobId = parseInt(params.id, 10);
  
  // Fetch the job
  const job = await fetchJobById(jobId);
  
  // Handle job not found
  if (!job) {
    notFound();
  }

  return (
    <div className="max-w-4xl mx-auto p-4">
      <nav className="mb-6">
        <Link href="/jobs" className="text-blue-600 hover:underline">
          ← Back to jobs
        </Link>
      </nav>

      <div className="bg-white rounded-lg shadow-md p-6">
        <h1 className="text-2xl font-bold mb-2">{job.name || 'Unnamed Position'}</h1>
        <p className="text-xl text-gray-700 font-medium mb-2">{job.companyName || 'Unknown Company'}</p>
        
        <div className="flex flex-wrap gap-3 mb-4 text-sm">
          {job.location && (
            <span className="bg-gray-100 px-3 py-1 rounded-full">
              📍 {job.location}
            </span>
          )}
          {job.workType && (
            <span className="bg-gray-100 px-3 py-1 rounded-full">
              💼 {job.workType}
            </span>
          )}
          {job.datePosted && (
            <span className="bg-gray-100 px-3 py-1 rounded-full">
              📅 Posted: {job.datePosted}
            </span>
          )}
          {job.source && (
            <span className="bg-gray-100 px-3 py-1 rounded-full">
              🔍 Source: {job.source}
            </span>
          )}
        </div>

        {job.salaryDescription && (
          <div className="bg-green-50 border border-green-100 rounded-md p-3 mb-6">
            <p className="text-green-700 font-medium">
              💰 {job.salaryDescription}
            </p>
          </div>
        )}

        <div className="mt-6">
          <h2 className="text-xl font-semibold mb-3">Job Description</h2>
          <div className="prose prose-sm max-w-none">
            {job.description ? (
              <p className="whitespace-pre-line">{job.description}</p>
            ) : (
              <p className="text-gray-500 italic">No description available</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}