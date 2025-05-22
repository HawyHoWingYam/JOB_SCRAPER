// apps/backend/src/jobs/jobs.service.ts
import { Injectable, NotFoundException } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { Repository, Not, IsNull, Like, ILike, In, FindOperator, Raw } from 'typeorm';
import { Job } from './entities/job.entity';
import { CreateJobDto, UpdateJobDto } from './dto/job.dto';

@Injectable()
export class JobsService {
  constructor(
    @InjectRepository(Job)
    private jobRepository: Repository<Job>,
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

  async searchJobs(query: string, mode: 'AND' | 'OR' = 'AND'): Promise<Job[]> {
    console.log(`Searching jobs with query: ${query} (mode: ${mode})`);

    // Normalize query string by removing spaces around commas
    const normalizedQuery = query.replace(/\s*,\s*/g, '/');

    // Split the query by comma to handle multiple search terms
    const orSearchTerms = normalizedQuery.split('/').map(term => term.trim()).filter(term => term);
    const andSearchTerms = normalizedQuery.split(',').map(term => term.trim()).filter(term => term);

    if (orSearchTerms.length === 0) {
      return this.findAll();
    }

    if (mode === 'OR') {
      return this.searchJobsOr(orSearchTerms);
    } else {
      return this.searchJobsAnd(orSearchTerms);
    }
  }

  private async searchJobsAnd(searchTerms: string[]): Promise<Job[]> {
    // Start with all jobs
    let filteredJobs = await this.findAll();

    // For each term, filter the results further
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
        order: { id: 'DESC' }
      });

      // Get only IDs that match this term
      const matchingIds = termResults.map(job => job.id);

      // Keep only jobs that exist in both filteredJobs and termResults
      filteredJobs = filteredJobs.filter(job => matchingIds.includes(job.id));
    }

    console.log(`Found ${filteredJobs.length} jobs matching ALL terms`);
    return filteredJobs;
  }

  private async searchJobsOr(searchTerms: string[]): Promise<Job[]> {
    // Create where conditions for OR search - each term creates a set of conditions
    const whereConditions = searchTerms.map(term => [
      { name: ILike(`%${term}%`) },
      { description: ILike(`%${term}%`) },
      { companyName: ILike(`%${term}%`) }
    ]).flat();

    const jobs = await this.jobRepository.find({
      where: whereConditions,
      order: {
        id: 'DESC',
      }
    });

    console.log(`Found ${jobs.length} jobs matching ANY term`);
    return jobs;
  }

  async filterByTerm(jobs: Job[], term: string): Promise<Job[]> {
    if (jobs.length === 0) return jobs;
    
    const jobIds = jobs.map(job => job.id);
    
    const whereConditions = [
      { name: ILike(`%${term}%`), id: In(jobIds) },
      { description: ILike(`%${term}%`), id: In(jobIds) },
      { companyName: ILike(`%${term}%`), id: In(jobIds) }
    ];
    
    const matchingJobs = await this.jobRepository.find({
      where: whereConditions
    });
    
    return matchingJobs;
  }

  async filterByOrTerms(jobs: Job[], terms: string[]): Promise<Job[]> {
    // If input jobs array is empty, return it immediately
    if (jobs.length === 0) return jobs;
    
    // Get IDs to filter against
    const jobIds = jobs.map(job => job.id);
    
    // Build OR conditions properly with TypeORM structure
    const whereConditions = terms.map(term => [
      { name: ILike(`%${term}%`), id: In(jobIds) },
      { description: ILike(`%${term}%`), id: In(jobIds) },
      { companyName: ILike(`%${term}%`), id: In(jobIds) }
    ]).flat();
    
    // Find all jobs matching any of the terms (OR condition)
    const matchingJobs = await this.jobRepository.find({
      where: whereConditions
    });
    
    return matchingJobs;
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
}