// apps/frontend/src/components/JobsTable.tsx
'use client';

import { useState } from 'react';
import Link from 'next/link';
import { Job } from '@/types/job';

interface JobsTableProps {
  initialJobs: Job[];
}

export default function JobsTable({ initialJobs }: JobsTableProps) {
  const [selectedJob, setSelectedJob] = useState<Job | null>(
    initialJobs.length > 0 ? initialJobs[0] : null
  );
  
  // Pagination state
  const [currentPage, setCurrentPage] = useState(1);
  const jobsPerPage = 20;
  
  const handleSelectJob = (job: Job) => {
    setSelectedJob(job);
  };
  
  // Calculate pagination values
  const indexOfLastJob = currentPage * jobsPerPage;
  const indexOfFirstJob = indexOfLastJob - jobsPerPage;
  const currentJobs = initialJobs.slice(indexOfFirstJob, indexOfLastJob);
  const totalPages = Math.ceil(initialJobs.length / jobsPerPage);
  
  // Page navigation handlers
  const goToNextPage = () => {
    if (currentPage < totalPages) {
      setCurrentPage(currentPage + 1);
    }
  };
  
  const goToPreviousPage = () => {
    if (currentPage > 1) {
      setCurrentPage(currentPage - 1);
    }
  };

  return (
    <div className="flex flex-col md:flex-row gap-2">
      {/* Left side - Jobs Table */}
      <div className="w-full md:w-3/10">
        <div className="bg-white rounded-lg shadow-md overflow-hidden">
          <div className="bg-gray-50 px-4 py-3 border-b flex justify-between items-center">
            <h2 className="text-lg font-semibold">Jobs List</h2>
            <span className="text-sm text-gray-500">
              {initialJobs.length} jobs found
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Job Title</th>
                  {/* <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Company</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Location</th> */}
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {currentJobs.length === 0 ? (
                  <tr>
                    <td colSpan={3} className="px-6 py-4 text-center text-gray-500">
                      No jobs found
                    </td>
                  </tr>
                ) : (
                  currentJobs.map((job) => (
                    <tr 
                      key={job.id} 
                      onClick={() => handleSelectJob(job)}
                      className={`hover:bg-gray-50 cursor-pointer ${selectedJob?.id === job.id ? 'bg-blue-50' : ''}`}
                    >
                      <td className="px-6 py-6 whitespace-normal">
                        <div className="text-sm font-medium text-gray-900 break-words">{job.name || 'Unnamed Position'}</div>
                      </td>
                      {/* <td className="px-6 py-4 whitespace-nowrap">
                        <div className="text-sm text-gray-500">{job.companyName || 'Unknown Company'}</div>
                      </td> */}
                      {/* <td className="px-6 py-4 whitespace-nowrap">
                        <div className="text-sm text-gray-500">{job.location || 'Remote/Unspecified'}</div>
                      </td> */}
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
          
          {/* Pagination controls */}
          {initialJobs.length > 0 && (
            <div className="px-4 py-3 bg-gray-50 border-t border-gray-200 flex items-center justify-between">
              <div className="flex-1 flex justify-between sm:hidden">
                <button
                  onClick={goToPreviousPage}
                  disabled={currentPage === 1}
                  className={`relative inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md ${
                    currentPage === 1 ? 'bg-gray-100 text-gray-400' : 'bg-white text-gray-700 hover:bg-gray-50'
                  }`}
                >
                  Previous
                </button>
                <button
                  onClick={goToNextPage}
                  disabled={currentPage === totalPages}
                  className={`ml-3 relative inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md ${
                    currentPage === totalPages ? 'bg-gray-100 text-gray-400' : 'bg-white text-gray-700 hover:bg-gray-50'
                  }`}
                >
                  Next
                </button>
              </div>
              <div className="hidden sm:flex-1 sm:flex sm:items-center sm:justify-between">
                <div>
                  <p className="text-sm text-gray-700">
                    Showing <span className="font-medium">{indexOfFirstJob + 1}</span> to{' '}
                    <span className="font-medium">
                      {Math.min(indexOfLastJob, initialJobs.length)}
                    </span>{' '}
                    of <span className="font-medium">{initialJobs.length}</span> results
                  </p>
                </div>
                <div>
                  <nav className="relative z-0 inline-flex rounded-md shadow-sm -space-x-px" aria-label="Pagination">
                    <button
                      onClick={goToPreviousPage}
                      disabled={currentPage === 1}
                      className={`relative inline-flex items-center px-2 py-2 rounded-l-md border border-gray-300 text-sm font-medium ${
                        currentPage === 1 ? 'bg-gray-100 text-gray-400' : 'bg-white text-gray-500 hover:bg-gray-50'
                      }`}
                    >
                      <span className="sr-only">Previous</span>
                      &laquo;
                    </button>
                    <span className="relative inline-flex items-center px-4 py-2 border border-gray-300 bg-white text-sm font-medium text-gray-700">
                      Page {currentPage} of {totalPages}
                    </span>
                    <button
                      onClick={goToNextPage}
                      disabled={currentPage === totalPages}
                      className={`relative inline-flex items-center px-2 py-2 rounded-r-md border border-gray-300 text-sm font-medium ${
                        currentPage === totalPages ? 'bg-gray-100 text-gray-400' : 'bg-white text-gray-500 hover:bg-gray-50'
                      }`}
                    >
                      <span className="sr-only">Next</span>
                      &raquo;
                    </button>
                  </nav>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
      
      {/* Right side - Job Form */}
      <div className="w-full md:w-7/10">
        {selectedJob ? (
          <div className="bg-white rounded-lg shadow-md p-6">
            <h2 className="text-lg font-semibold mb-4">{selectedJob.id || 'N/A'}</h2>
            <form className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700">Job Title</label>
                <div className="mt-1 p-2 bg-gray-50 border border-gray-300 rounded-md">
                  {selectedJob.name || 'N/A'}
                </div>
              </div>
              
              <div>
                <label className="block text-sm font-medium text-gray-700">Company</label>
                <div className="mt-1 p-2 bg-gray-50 border border-gray-300 rounded-md">
                  {selectedJob.companyName || 'N/A'}
                </div>
              </div>
              
              <div>
                <label className="block text-sm font-medium text-gray-700">Location</label>
                <div className="mt-1 p-2 bg-gray-50 border border-gray-300 rounded-md">
                  {selectedJob.location || 'N/A'}
                </div>
              </div>
              
              <div>
                <label className="block text-sm font-medium text-gray-700">Work Type</label>
                <div className="mt-1 p-2 bg-gray-50 border border-gray-300 rounded-md">
                  {selectedJob.workType || 'N/A'}
                </div>
              </div>
              
              <div>
                <label className="block text-sm font-medium text-gray-700">Salary</label>
                <div className="mt-1 p-2 bg-gray-50 border border-gray-300 rounded-md">
                  {selectedJob.salaryDescription || 'N/A'}
                </div>
              </div>
              
              <div>
                <label className="block text-sm font-medium text-gray-700">Date Posted</label>
                <div className="mt-1 p-2 bg-gray-50 border border-gray-300 rounded-md">
                  {selectedJob.datePosted || 'N/A'}
                </div>
              </div>
              
              <div>
                <label className="block text-sm font-medium text-gray-700">Description</label>
                <div className="mt-1 p-2 bg-gray-50 border border-gray-300 rounded-md h-32 overflow-y-auto">
                  {selectedJob.description || 'No description available'}
                </div>
              </div>
              
              <div className="pt-2">
                <Link href={`/jobs/${selectedJob.id}`} className="inline-flex items-center px-4 py-2 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500">
                  View Full Details
                </Link>
              </div>
            </form>
          </div>
        ) : (
          <div className="bg-white rounded-lg shadow-md p-6 flex items-center justify-center h-full">
            <p className="text-gray-500">Select a job to view details</p>
          </div>
        )}
      </div>
    </div>
  );
}