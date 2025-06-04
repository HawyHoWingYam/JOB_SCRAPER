// apps/backend/src/jobs/jobs.service.ts
import { Injectable, NotFoundException } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { Repository, Not, IsNull, Like, ILike, In, FindOperator, Raw } from 'typeorm';
import { Job } from './entities/job.entity';
import { CreateJobDto, UpdateJobDto } from './dto/job.dto';
import { PaginatedResponse } from './types/pagination.types';
import { DataSource } from 'typeorm';

@Injectable()
export class JobsService {
  constructor(
    @InjectRepository(Job)
    private jobRepository: Repository<Job>,
    private dataSource: DataSource
  ) { }

  async findAll(): Promise<Job[]> {
    return this.jobRepository.find({
      where: [
        { description: Not('N/A') }
      ],
      order: {
        id: 'DESC',
      }
    });
  }

  async findAllPaginated(page = 1, limit = 20, jobClass?: string, source?: string): Promise<PaginatedResponse<Job>> {
    // Build where conditions
    const whereConditions: any[] = [{ description: Not('N/A') }];
    
    // Add job class filter if provided
    if (jobClass) {
      whereConditions[0].jobClass = jobClass;
    }
    
    // Add source filter if provided
    if (source) {
      whereConditions[0].source = source;
    }

    const [items, total] = await this.jobRepository.findAndCount({
      where: whereConditions,
      order: {
        id: 'DESC',
      },
      skip: (page - 1) * limit,
      take: limit,
    });

    return {
      items,
      total,
      page,
      limit,
      totalPages: Math.ceil(total / limit),
    };
  }

  async searchJobsPaginated(
    query: string, 
    mode: 'AND' | 'OR' = 'AND',
    page = 1,
    limit = 20,
    jobClass?: string,
    source?: string
  ): Promise<PaginatedResponse<Job>> {
    console.log(`Searching jobs with query: ${query} (mode: ${mode}, page: ${page}, limit: ${limit})`);

    // Normalize query string by removing spaces around commas
    const normalizedQuery = query.replace(/\s*,\s*/g, '/');

    // Split the query by comma to handle multiple search terms
    const orSearchTerms = normalizedQuery.split('/').map(term => term.trim()).filter(term => term);
    const andSearchTerms = normalizedQuery.split(',').map(term => term.trim()).filter(term => term);

    if (orSearchTerms.length === 0) {
      return this.findAllPaginated(page, limit, jobClass, source);
    }

    if (mode === 'OR') {
      return this.searchJobsOrPaginated(orSearchTerms, page, limit, jobClass, source);
    } else {
      return this.searchJobsAndPaginated(orSearchTerms, page, limit, jobClass, source);
    }
  }

  private async searchJobsAndPaginated(
    searchTerms: string[],
    page = 1,
    limit = 20,
    jobClass?: string,
    source?: string
  ): Promise<PaginatedResponse<Job>> {
    // Create where conditions for AND search - each term must match at least one field
    // This is more complex and might need to be customized based on your database engine
    
    // For simplicity, we'll do a two-step process:
    // 1. First, find all matching job IDs
    // 2. Then do a paginated query with those IDs
    
    // Start with all jobs
    const allJobs = await this.findAll();
    
    // For each term, filter the results further
    let filteredJobs = allJobs;
    for (const term of searchTerms) {
      // Create a condition that matches this term in any field
      const termCondition = [
        { name: ILike(`%${term}%`) },
        { description: ILike(`%${term}%`) },
        { companyName: ILike(`%${term}%`) }
      ];

      // Filter current results against this term
      const termResults = await this.jobRepository.find({
        where: termCondition,
      });

      // Get only IDs that match this term
      const matchingIds = termResults.map(job => job.id);

      // Keep only jobs that exist in both filteredJobs and termResults
      filteredJobs = filteredJobs.filter(job => matchingIds.includes(job.id));
    }
    
    // Get total count
    const total = filteredJobs.length;
    
    // Apply pagination
    const paginatedItems = filteredJobs.slice((page - 1) * limit, page * limit);
    
    return {
      items: paginatedItems,
      total,
      page,
      limit,
      totalPages: Math.ceil(total / limit),
    };
  }

  private async searchJobsOrPaginated(
    searchTerms: string[],
    page = 1,
    limit = 20,
    jobClass?: string,
    source?: string
  ): Promise<PaginatedResponse<Job>> {
    // Create where conditions for OR search - each term creates a set of conditions
    const whereConditions = searchTerms.map(term => [
      { name: ILike(`%${term}%`) },
      { description: ILike(`%${term}%`) },
      { companyName: ILike(`%${term}%`) }
    ]).flat();

    const [items, total] = await this.jobRepository.findAndCount({
      where: whereConditions,
      order: {
        id: 'DESC',
      },
      skip: (page - 1) * limit,
      take: limit,
    });

    return {
      items,
      total,
      page,
      limit,
      totalPages: Math.ceil(total / limit),
    };
  }

  async searchWithTermsPaginated(
    includeTerms: string[],
    excludeTerms: string[],
    exactTerms: string[],
    exactExcludeTerms: string[],
    page = 1,
    limit = 20,
    jobClass?: string,
    source?: string
  ): Promise<PaginatedResponse<Job>> {
    // Start with all jobs
    let resultSet = await this.findAll();
    
    // Apply filters for job class and source
    if (jobClass) {
      resultSet = resultSet.filter(job => job.jobClass === jobClass);
    }
    
    if (source) {
      resultSet = resultSet.filter(job => job.source === source);
    }
    
    // Apply regular include terms (partial matches)
    for (const term of includeTerms) {
      if (term.includes('/')) {
        // Handle OR logic: term1/term2/term3
        const orTerms = term.split('/').map(t => t.trim()).filter(t => t);
        console.log(`Processing OR terms: ${orTerms.join(' OR ')}`);
        resultSet = await this.filterByOrTerms(resultSet, orTerms);
      } else {
        // Handle single term as filter
        console.log(`Filtering by include term: ${term}`);
        resultSet = await this.filterByTerm(resultSet, term);
      }
    }
    
    // Apply exact include terms
    for (const term of exactTerms) {
      console.log(`Filtering by exact include term: "${term}"`);
      // For exact matches, we need to use exact comparison
      resultSet = resultSet.filter(job => {
        const jobText = `${job.name} ${job.companyName} ${job.description}`;
        return jobText.includes(term); // Exact substring match
      });
    }
    
    // Apply regular exclude terms
    for (const term of excludeTerms) {
      console.log(`Filtering by exclude term: ${term}`);
      // Exclude any job that contains the term
      const matchingJobs = await this.filterByTerm(resultSet, term);
      const matchingIds = new Set(matchingJobs.map(job => job.id));
      // Keep only jobs that don't match the exclude term
      resultSet = resultSet.filter(job => !matchingIds.has(job.id));
    }
    
    // Apply exact exclude terms
    for (const term of exactExcludeTerms) {
      console.log(`Filtering by exact exclude term: "${term}"`);
      // Exclude jobs that contain the exact term
      resultSet = resultSet.filter(job => {
        const jobText = `${job.name} ${job.companyName} ${job.description}`;
        return !jobText.includes(term); // Exclude exact matches
      });
    }
    
    // Get total count
    const total = resultSet.length;
    
    // Apply pagination
    const paginatedItems = resultSet.slice((page - 1) * limit, page * limit);
    
    return {
      items: paginatedItems,
      total,
      page,
      limit,
      totalPages: Math.ceil(total / limit),
    };
  }

  async filterByTerm(jobs: Job[], term: string): Promise<Job[]> {
    if (jobs.length === 0) return jobs;
    
    // Too many job IDs can cause PostgreSQL parameter limit error
    // Instead of using IN clause with all IDs, we'll search without the ID filter
    // and then intersect the results with our job list in JavaScript
    
    const whereConditions = [
      { name: ILike(`%${term}%`) },
      { description: ILike(`%${term}%`) },
      { companyName: ILike(`%${term}%`) }
    ];
    
    // Get all jobs matching the search term
    const matchingJobs = await this.jobRepository.find({
      where: whereConditions
    });
    
    // Get the IDs of matching jobs
    const matchingJobIds = new Set(matchingJobs.map(job => job.id));
    
    // Filter the input jobs to only include those that match
    return jobs.filter(job => matchingJobIds.has(job.id));
  }

  async filterByOrTerms(jobs: Job[], terms: string[]): Promise<Job[]> {
    // If input jobs array is empty, return it immediately
    if (jobs.length === 0) return jobs;
    
    // Same approach - search without ID filter, then intersect in memory
    const whereConditions = terms.map(term => [
      { name: ILike(`%${term}%`) },
      { description: ILike(`%${term}%`) },
      { companyName: ILike(`%${term}%`) }
    ]).flat();
    
    // Find all jobs matching any of the terms (OR condition)
    const matchingJobs = await this.jobRepository.find({
      where: whereConditions
    });
    
    // Create a set of matching job IDs
    const matchingJobIds = new Set(matchingJobs.map(job => job.id));
    
    // Filter the input jobs to only include those that match
    return jobs.filter(job => matchingJobIds.has(job.id));
  }

  async findOne(id: number): Promise<Job> {
    const job = await this.jobRepository.findOne({ where: { id } });
    if (!job) {
      throw new NotFoundException(`Job with ID ${id} not found`);
    }
    return job;
  }

  async create(createJobDto: CreateJobDto): Promise<Job> {
    const job = this.jobRepository.create(createJobDto);
    return this.jobRepository.save(job);
  }

  async update(id: number, updateJobDto: UpdateJobDto): Promise<Job> {
    const job = await this.findOne(id);
    const updatedJob = this.jobRepository.merge(job, updateJobDto);
    return this.jobRepository.save(updatedJob);
  }

  async remove(id: number): Promise<void> {
    const job = await this.findOne(id);
    await this.jobRepository.remove(job);
  }

  async getJobClasses(): Promise<string[]> {
    // Assuming you have a JobClass entity/table
    try {
      // Option 1: If you have a dedicated job_class table with a name column
      const jobClasses = await this.dataSource.query(`
        SELECT name FROM job_class ORDER BY name ASC
      `);
      return jobClasses.map(jc => jc.name);
      
      // Option 2: If job_class is just a column in your jobs table
      // const result = await this.jobRepository
      //   .createQueryBuilder('job')
      //   .select('DISTINCT job.job_class', 'jobClass')
      //   .where('job.job_class IS NOT NULL')
      //   .orderBy('job.job_class', 'ASC')
      //   .getRawMany();
      // return result.map(r => r.jobClass).filter(Boolean);
    } catch (error) {
      console.error('Error fetching job classes:', error);
      return [];
    }
  }

  async getSourcePlatforms(): Promise<string[]> {
    try {
      // Query the source_platform table if it exists
      const sources = await this.dataSource.query(`
        SELECT name FROM source_platform ORDER BY name ASC
      `);
      return sources.map(s => s.name);
      
      // Alternative if you don't have a separate table but have sources in the jobs table
      // const result = await this.jobRepository
      //   .createQueryBuilder('job')
      //   .select('DISTINCT job.source', 'source')
      //   .where('job.source IS NOT NULL')
      //   .orderBy('job.source', 'ASC')
      //   .getRawMany();
      // return result.map(r => r.source).filter(Boolean);
    } catch (error) {
      console.error('Error fetching source platforms:', error);
      return [];
    }
  }
}