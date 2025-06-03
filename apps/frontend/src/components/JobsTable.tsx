// apps/frontend/src/components/JobsTable.tsx
'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { Job } from '@/types/job';
import { API_URL } from '@/services/jobs';
import * as XLSX from 'xlsx';

interface JobsTableProps {
  initialJobs: Job[];
}

interface PaginatedResponse {
  items: Job[];
  total: number;
  page: number;
  limit: number;
  totalPages: number;
}

export default function JobsTable({ initialJobs }: JobsTableProps) {
  const [jobs, setJobs] = useState<Job[]>(initialJobs || []);
  const [selectedJob, setSelectedJob] = useState<Job | null>(
    initialJobs.length > 0 ? initialJobs[0] : null
  );
  const [searchTerms, setSearchTerms] = useState<string[]>([]);
  const [currentSearchTerm, setCurrentSearchTerm] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  // Pagination state
  const [currentPage, setCurrentPage] = useState(1);
  const jobsPerPage = 20;
  const [totalJobs, setTotalJobs] = useState(initialJobs.length);
  const [totalPages, setTotalPages] = useState(Math.ceil(initialJobs.length / jobsPerPage));

  // Go to specific page state
  const [goToPage, setGoToPage] = useState<number | ''>('');

  // Load jobs when page changes
  useEffect(() => {
    if (searchTerms.length > 0) {
      // If we're searching, use the search with pagination
      performSearch(searchTerms);
    } else {
      // Otherwise, fetch all jobs with pagination
      fetchJobs();
    }
  }, [currentPage]);

  const fetchJobs = async () => {
    setIsLoading(true);
    try {
      const response = await fetch(`${API_URL}/jobs?page=${currentPage}&limit=${jobsPerPage}`);
      
      if (!response.ok) {
        throw new Error('Failed to fetch jobs');
      }
      
      const data = await response.json();
      console.log('Response data:', data);
      setJobs(Array.isArray(data.items) ? data.items : []);
      setTotalJobs(data.total || 0);
      setTotalPages(data.totalPages || 1);
      
      if (data.items && data.items.length > 0 && !selectedJob) {
        setSelectedJob(data.items[0]);
      }
    } catch (error) {
      console.error('Error fetching jobs:', error);
      setJobs([]);
    } finally {
      setIsLoading(false);
    }
  };

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

    // Reset to page 1 when adding a search term
    setCurrentPage(1);

    // Perform the cascading search
    await performSearch(newSearchTerms);
  };

  const handleRemoveSearchTerm = async (termToRemove: string) => {
    const newSearchTerms = searchTerms.filter(term => term !== termToRemove);
    setSearchTerms(newSearchTerms);

    // Reset to page 1 when removing a search term
    setCurrentPage(1);

    // If no search terms left, reset to initial jobs with pagination
    if (newSearchTerms.length === 0) {
      fetchJobs();
    } else {
      // Otherwise perform search with remaining terms
      await performSearch(newSearchTerms);
    }
  };

  const performSearch = async (terms: string[]) => {
    setIsLoading(true);
    try {
      const response = await fetch(`${API_URL}/jobs/search`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          query: terms,
          page: currentPage,
          limit: jobsPerPage
        }),
      });

      if (!response.ok) {
        throw new Error('Search failed');
      }

      const data = await response.json();
      console.log('API response:', data);
      setJobs(data.items || []);
      setTotalJobs(data.total || 0);
      setTotalPages(data.totalPages || 1);

      if (data.items && data.items.length > 0) {
        setSelectedJob(data.items[0]);
      } else {
        setSelectedJob(null);
      }
    } catch (error) {
      console.error('Error searching jobs:', error);
      setJobs([]);
    } finally {
      setIsLoading(false);
    }
  };

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

  const downloadExcel = async () => {
    setIsLoading(true);
    
    try {
      // Array to hold all job results
      let allJobs: Job[] = [];
      
      // If we have search terms, use search endpoint
      if (searchTerms.length > 0) {
        // Fetch all pages one by one
        for (let page = 1; page <= totalPages; page++) {
          const response = await fetch(`${API_URL}/jobs/search`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({
              query: searchTerms,
              page: page,
              limit: jobsPerPage
            }),
          });
          
          if (!response.ok) {
            throw new Error('Failed to fetch search results');
          }
          
          const data = await response.json();
          if (Array.isArray(data.items)) {
            allJobs = [...allJobs, ...data.items];
          }
        }
      } else {
        // Fetch all regular jobs
        for (let page = 1; page <= totalPages; page++) {
          const response = await fetch(`${API_URL}/jobs?page=${page}&limit=${jobsPerPage}`);
          
          if (!response.ok) {
            throw new Error('Failed to fetch jobs');
          }
          
          const data = await response.json();
          if (Array.isArray(data.items)) {
            allJobs = [...allJobs, ...data.items];
          }
        }
      }
      
      // Create a worksheet from all collected jobs
      const worksheet = XLSX.utils.json_to_sheet(allJobs.map(job => ({
        'ID': job.id,
        'Job Title': job.name,
        'Company': job.companyName,
        'Location': job.location,
        'Work Type': job.workType,
        'Salary': job.salaryDescription,
        'Date Posted': job.datePosted,
        'Source': job.source,
        'Category': job.jobClass || 'N/A',
        'Description': job.description
      })));

      // Create a workbook and add the worksheet
      const workbook = XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(workbook, worksheet, 'Jobs');

      // Generate excel file and download
      const searchTermText = searchTerms.length > 0 ? 
        `_${searchTerms.join('_')}` : '';
      const fileName = `job_search${searchTermText}_${new Date().toISOString().split('T')[0]}.xlsx`;
      
      // Update the button text to show the total number of exported jobs
      console.log(`Exporting ${allJobs.length} jobs to Excel`);
      
      XLSX.writeFile(workbook, fileName);
    } catch (error) {
      console.error('Error generating Excel file:', error);
      alert('Failed to generate Excel file. Please try again.');
    } finally {
      setIsLoading(false);
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
            className="flex-1 p-2 border border-gray-300 rounded-md focus:ring-blue-500 focus:border-blue-500 text-black"
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
                  setCurrentPage(1);
                  fetchJobs();
                }}
                className="text-xs text-blue-600 hover:text-blue-800 font-medium"
              >
                Clear All
              </button>
            )}
            
            {/* Add download button */}
            <button
              onClick={downloadExcel}
              disabled={jobs.length === 0 || isLoading}
              className={`ml-auto px-4 py-1 text-sm rounded-md text-white ${jobs.length === 0 || isLoading ? 'bg-gray-400' : 'bg-green-600 hover:bg-green-700'}`}
            >
              <div className="flex items-center">
                <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4 mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                </svg>
                {isLoading ? 'Preparing Excel...' : `Download Excel (all ${totalJobs} jobs)`}
              </div>
            </button>
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
                {totalJobs} jobs found
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
                  {Array.isArray(jobs) && jobs.length === 0 ? (
                    <tr>
                      <td colSpan={3} className="px-6 py-4 text-center text-gray-500">
                        No jobs found
                      </td>
                    </tr>
                  ) : (
                    Array.isArray(jobs) && jobs.map((job) => (
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
                      Showing <span className="font-medium">{((currentPage - 1) * jobsPerPage) + 1}</span> to{' '}
                      <span className="font-medium">
                        {Math.min(currentPage * jobsPerPage, totalJobs)}
                      </span>{' '}
                      of <span className="font-medium">{totalJobs}</span> results
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
                    
                    {/* Go to specific page */}
                    <div className="mt-3 flex items-center">
                      <span className="text-sm text-gray-700 mr-2">Go to page:</span>
                      <input
                        type="number"
                        min="1"
                        max={totalPages}
                        value={goToPage || ''}
                        onChange={(e) => setGoToPage(parseInt(e.target.value) || '')}
                        className="text-black w-16 rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 text-sm"
                      />
                      <button
                        onClick={() => {
                          if (goToPage && goToPage >= 1 && goToPage <= totalPages) {
                            setCurrentPage(goToPage);
                          }
                        }}
                        disabled={!goToPage || goToPage < 1 || goToPage > totalPages}
                        className="ml-2 inline-flex items-center px-3 py-1 border border-gray-300 text-sm font-medium rounded-md bg-white text-gray-700 hover:bg-gray-50 disabled:bg-gray-100 disabled:text-gray-400"
                      >
                        Go
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Right side - Job Details */}
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
                      {selectedJob.jobClass || 'N/A'}
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