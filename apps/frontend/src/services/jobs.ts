// apps/frontend/src/services/jobs.ts
import { Job } from '@/types/job';

// Use environment variable or fallback with proper port (3001)
const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://192.168.10.171:3001/api';

export async function fetchJobs(): Promise<Job[]> {
  try {
    // Server-side fetch (this runs on the server)
    const res = await fetch(`${API_URL}/jobs`, { 
      cache: 'no-store',  // Don't cache this request
      headers: {
        'Content-Type': 'application/json',
      },
      next: { revalidate: 0 }, // Force revalidation
    });
    
    if (!res.ok) {
      throw new Error(`Failed to fetch jobs: ${res.status}`);
    }
    
    return res.json();
  } catch (error) {
    console.error('Error fetching jobs:', error);
    return []; // Return empty array on error
  }
}

export async function fetchJobById(id: number): Promise<Job | null> {
  try {
    const res = await fetch(`${API_URL}/jobs/${id}`, { 
      cache: 'no-store',
      next: { revalidate: 0 },
    });
    
    if (!res.ok) {
      throw new Error(`Failed to fetch job with id ${id}`);
    }
    
    return res.json();
  } catch (error) {
    console.error(`Error fetching job ${id}:`, error);
    return null;
  }
}

// Export the API URL for direct use in components 
export { API_URL };