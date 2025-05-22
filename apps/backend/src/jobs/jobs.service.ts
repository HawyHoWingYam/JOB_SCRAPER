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

  async searchJobs(query: string): Promise<Job[]> {
    console.log(`Searching jobs with query: ${query}`);

    // Split the query by comma to handle multiple search terms
    const searchTerms = query.split(',').map(term => term.trim()).filter(term => term);

    if (searchTerms.length === 0) {
      return this.findAll();
    }

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

    console.log(`Found ${filteredJobs.length} jobs matching all terms in: ${query}`);
    return filteredJobs;
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