// apps/backend/src/jobs/dto/job.dto.ts
export class JobDto {
    id: number;
    name: string;
    description: string;
    companyName: string;
    location: string;
    workType: string;
    salaryDescription: string;
    datePosted: string;
    dateScraped: Date;
    source: string;
  }
  
  export class CreateJobDto {
    name?: string;
    description?: string;
    companyName?: string;
    location?: string;
    workType?: string;
    salaryDescription?: string;
    datePosted?: string;
    source?: string;
    jobClass?: string;
    jobSubclass?: string;
    other?: string;
    remark?: string;
  }
  
  export class UpdateJobDto extends CreateJobDto {}