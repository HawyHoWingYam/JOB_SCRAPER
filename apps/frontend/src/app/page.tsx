// apps/frontend/src/app/page.tsx
import React from 'react';
import { fetchJobs } from '@/services/jobs';
import JobsTable from '@/components/JobsTable';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export default async function Page() {
  const jobs = await fetchJobs();
  
  return (
    <div className="max-w-7xl mx-auto p-4">
      <h1 className="text-2xl font-bold mb-6">Job Management Dashboard</h1>
      <JobsTable initialJobs={jobs} />
    </div>
  );
}