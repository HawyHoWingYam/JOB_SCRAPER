// apps/frontend/src/types/job.ts
export interface Job {
    id: number;
    name: string;
    description: string;
    companyName: string;
    location: string;
    workType: string;
    salaryDescription: string;
    datePosted: string;
    dateScraped: string;
    source: string;
  }