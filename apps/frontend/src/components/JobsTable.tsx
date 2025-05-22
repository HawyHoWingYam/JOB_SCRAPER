// apps/frontend/src/components/JobsTable.tsx
'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { Job } from '@/types/job';
import { API_URL } from '@/services/jobs';


interface JobsTableProps {
  initialJobs: Job[];
}

export default function JobsTable({ initialJobs }: JobsTableProps) {
  const [jobs, setJobs] = useState<Job[]>(initialJobs);
  const [selectedJob, setSelectedJob] = useState<Job | null>(
    initialJobs.length > 0 ? initialJobs[0] : null
  );
  const [searchTerms, setSearchTerms] = useState<string[]>([]);
  const [currentSearchTerm, setCurrentSearchTerm] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  // Pagination state
  const [currentPage, setCurrentPage] = useState(1);
  const jobsPerPage = 20;

  const handleSelectJob = (job: Job) => {
    setSelectedJob(job);
  };

  const handleAddSearchTerm = async () => {
    if (!currentSearchTerm.trim()) return;

    // Add the current term to the search terms array
    const newSearchTerms = [...searchTerms, currentSearchTerm.trim()];
    setSearchTerms(newSearchTerms);

    // Clear the input field
    setCurrentSearchTerm('');

    // Perform the cascading search
    await performSearch(newSearchTerms);
  };

  const handleRemoveSearchTerm = async (termToRemove: string) => {
    const newSearchTerms = searchTerms.filter(term => term !== termToRemove);
    setSearchTerms(newSearchTerms);

    // If no search terms left, reset to initial jobs
    if (newSearchTerms.length === 0) {
      setJobs(initialJobs);
      if (initialJobs.length > 0) {
        setSelectedJob(initialJobs[0]);
      } else {
        setSelectedJob(null);
      }
    } else {
      // Otherwise perform search with remaining terms
      await performSearch(newSearchTerms);
    }
  };

  const performSearch = async (terms: string[]) => {
    setIsLoading(true);
    try {
      // Send search terms as an array directly
      const response = await fetch(`${API_URL}/jobs/search`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          query: terms // Send as array instead of joining with commas
        }),
      });

      if (!response.ok) {
        throw new Error('Search failed');
      }

      const data = await response.json();
      setJobs(data);
      setCurrentPage(1);

      if (data.length > 0) {
        setSelectedJob(data[0]);
      } else {
        setSelectedJob(null);
      }
    } catch (error) {
      console.error('Error searching jobs:', error);
    } finally {
      setIsLoading(false);
    }
  };


  // Calculate pagination values
  const indexOfLastJob = currentPage * jobsPerPage;
  const indexOfFirstJob = indexOfLastJob - jobsPerPage;
  const currentJobs = jobs.slice(indexOfFirstJob, indexOfLastJob);
  const totalPages = Math.ceil(jobs.length / jobsPerPage);

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
    <div className="flex flex-col space-y-4">
      {/* Search box */}
      <div className="flex flex-col space-y-2">
        <div className="flex items-center space-x-2">
          <input
            type="text"
            value={currentSearchTerm}
            onChange={(e) => setCurrentSearchTerm(e.target.value)}
            placeholder="Search jobs by title, company, or description..."
            className="flex-1 p-2 border border-gray-300 rounded-md focus:ring-blue-500 focus:border-blue-500"
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                handleAddSearchTerm();
              }
            }}
          />
          <button
            onClick={handleAddSearchTerm}
            disabled={isLoading || !currentSearchTerm.trim()}
            className={`px-4 py-2 text-white rounded-md ${isLoading || !currentSearchTerm.trim() ? 'bg-blue-400' : 'bg-blue-600 hover:bg-blue-700'
              }`}
          >
            {isLoading ? 'Searching...' : 'Add Search'}
          </button>
        </div>

        {/* Search terms pills/tags */}
        {searchTerms.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {searchTerms.map((term, index) => (
              <span
                key={`${term}-${index}`}
                className="inline-flex items-center px-3 py-1 rounded-full text-sm font-medium bg-blue-100 text-blue-800"
              >
                {term}
                <button
                  onClick={() => handleRemoveSearchTerm(term)}
                  className="ml-1.5 inline-flex items-center justify-center h-4 w-4 rounded-full hover:bg-blue-200"
                >
                  <span className="sr-only">Remove search term</span>
                  <svg className="h-3 w-3 text-blue-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </span>
            ))}
            {searchTerms.length > 0 && (
              <button
                onClick={() => {
                  setSearchTerms([]);
                  setJobs(initialJobs);
                  if (initialJobs.length > 0) {
                    setSelectedJob(initialJobs[0]);
                  }
                }}
                className="text-xs text-blue-600 hover:text-blue-800 font-medium"
              >
                Clear All
              </button>
            )}
          </div>
        )}
      </div>

      <div className="flex flex-col md:flex-row gap-2">
        {/* Left side - Jobs Table */}
        <div className="w-full md:w-3/10">
          <div className="bg-white rounded-lg shadow-md overflow-hidden">
            <div className="bg-gray-50 px-4 py-3 border-b flex justify-between items-center">
              <h2 className="text-lg font-semibold">Jobs List</h2>
              <span className="text-sm text-gray-500">
                {jobs.length} jobs found
              </span>
            </div>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Job Title</th>
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
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            {/* Pagination controls */}
            {jobs.length > 0 && (
              <div className="px-4 py-3 bg-gray-50 border-t border-gray-200 flex items-center justify-between">
                <div className="flex-1 flex justify-between sm:hidden">
                  <button
                    onClick={goToPreviousPage}
                    disabled={currentPage === 1}
                    className={`relative inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md ${currentPage === 1 ? 'bg-gray-100 text-gray-400' : 'bg-white text-gray-700 hover:bg-gray-50'
                      }`}
                  >
                    Previous
                  </button>
                  <button
                    onClick={goToNextPage}
                    disabled={currentPage === totalPages}
                    className={`ml-3 relative inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md ${currentPage === totalPages ? 'bg-gray-100 text-gray-400' : 'bg-white text-gray-700 hover:bg-gray-50'
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
                        {Math.min(indexOfLastJob, jobs.length)}
                      </span>{' '}
                      of <span className="font-medium">{jobs.length}</span> results
                    </p>
                  </div>
                  <div>
                    <nav className="relative z-0 inline-flex rounded-md shadow-sm -space-x-px" aria-label="Pagination">
                      <button
                        onClick={goToPreviousPage}
                        disabled={currentPage === 1}
                        className={`relative inline-flex items-center px-2 py-2 rounded-l-md border border-gray-300 text-sm font-medium ${currentPage === 1 ? 'bg-gray-100 text-gray-400' : 'bg-white text-gray-500 hover:bg-gray-50'
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
                        className={`relative inline-flex items-center px-2 py-2 rounded-r-md border border-gray-300 text-sm font-medium ${currentPage === totalPages ? 'bg-gray-100 text-gray-400' : 'bg-white text-gray-500 hover:bg-gray-50'
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
              <h2 className="text-lg font-semibold mb-4 text-black">{selectedJob.id || 'N/A'}</h2>
              <form className="space-y-4">
                {/* Grid layout for the form fields */}
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700">Job Title</label>
                    <div className="mt-1 p-2 bg-gray-50 border border-gray-300 rounded-md text-black">
                      {selectedJob.name || 'N/A'}
                    </div>
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-gray-700">Company</label>
                    <div className="mt-1 p-2 bg-gray-50 border border-gray-300 rounded-md text-black">
                      {selectedJob.companyName || 'N/A'}
                    </div>
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-gray-700">Location</label>
                    <div className="mt-1 p-2 bg-gray-50 border border-gray-300 rounded-md text-black">
                      {selectedJob.location || 'N/A'}
                    </div>
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-gray-700">Work Type</label>
                    <div className="mt-1 p-2 bg-gray-50 border border-gray-300 rounded-md text-black">
                      {selectedJob.workType || 'N/A'}
                    </div>
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-gray-700">Salary</label>
                    <div className="mt-1 p-2 bg-gray-50 border border-gray-300 rounded-md text-black">
                      {selectedJob.salaryDescription || 'N/A'}
                    </div>
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-gray-700">Date Posted</label>
                    <div className="mt-1 p-2 bg-gray-50 border border-gray-300 rounded-md text-black">
                      {selectedJob.datePosted || 'N/A'}
                    </div>
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-gray-700">Source</label>
                    <div className="mt-1 p-2 bg-gray-50 border border-gray-300 rounded-md text-black">
                      {selectedJob.source || 'N/A'}
                    </div>
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-gray-700">Category</label>
                    <div className="mt-1 p-2 bg-gray-50 border border-gray-300 rounded-md text-black">
                      {'N/A'}
                    </div>
                  </div>
                </div>

                {/* Description field takes full width */}
                <div className="col-span-2">
                  <label className="block text-sm font-medium text-gray-700">Description</label>
                  <div className="mt-1 p-2 bg-gray-50 border border-gray-300 rounded-md h-100 overflow-y-auto text-black">
                    {selectedJob.description ? (
                      /<[a-z][\s\S]*>/i.test(selectedJob.description) ? (
                        <div dangerouslySetInnerHTML={{ __html: selectedJob.description }} />
                      ) : (
                        selectedJob.description
                      )
                    ) : (
                      'No description available'
                    )}
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
    </div>
  );
}