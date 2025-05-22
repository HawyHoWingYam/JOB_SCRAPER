// apps/backend/src/jobs/jobs.controller.ts
import { Controller, Get, Post, Body, Patch, Param, Delete, Query } from '@nestjs/common';
import { JobsService } from './jobs.service';
import { CreateJobDto, UpdateJobDto } from './dto/job.dto';
import { Job } from './entities/job.entity';

@Controller('jobs')
export class JobsController {
  constructor(private readonly jobsService: JobsService) { }

  @Get()
  async findAll(
    @Query('query') query?: string,
    @Query('mode') mode?: 'AND' | 'OR'
  ): Promise<Job[]> {
    // Auto-detect slash-separated queries and use OR mode unless explicitly specified
    const hasSlash = query?.includes('/');
    const effectiveMode = mode || (hasSlash ? 'OR' : 'AND');

    console.log(`GET /api/jobs endpoint called${query ? ` with search query: ${query}` : ''} 
      (mode: ${effectiveMode})`);

    try {
      const jobs = query
        ? await this.jobsService.searchJobs(query, effectiveMode)
        : await this.jobsService.findAll();

      console.log(`Found ${jobs.length} jobs`);
      return jobs;
    } catch (error) {
      console.error('Error in findAll:', error);
      throw error;
    }
  }


  @Post('search')
  async searchJobs(
    @Body() searchParams: { query: string[] | string }
  ): Promise<Job[]> {
    console.log('Search params received:', searchParams);

    // Handle both string and array formats
    let searchTerms: string[] = [];
    if (typeof searchParams.query === 'string') {
      searchTerms = [searchParams.query];
    } else if (Array.isArray(searchParams.query)) {
      searchTerms = searchParams.query;
    }

    if (searchTerms.length === 0) {
      return this.jobsService.findAll();
    }

    console.log(`POST /api/jobs/search with terms:`, searchTerms);

    try {
      // Start with all jobs as the initial result set
      let resultSet = await this.jobsService.findAll();

      // Process each term sequentially
      for (const term of searchTerms) {
        if (term.includes('/')) {
          // Handle OR logic: term1/term2/term3
          const orTerms = term.split('/').map(t => t.trim()).filter(t => t);
          console.log(`Processing OR terms: ${orTerms.join(' OR ')}`);
          resultSet = await this.jobsService.filterByOrTerms(resultSet, orTerms);
        } else {
          // Handle single term as filter
          console.log(`Filtering by term: ${term}`);
          resultSet = await this.jobsService.filterByTerm(resultSet, term);
        }
      }

      console.log(`Final result set contains ${resultSet.length} jobs`);
      return resultSet;
    } catch (error) {
      console.error('Error in searchJobs:', error);
      throw error;
    }
  }

  @Get(':id')
  async findOne(@Param('id') id: string): Promise<Job> {
    return this.jobsService.findOne(+id);
  }

  @Post()
  async create(@Body() createJobDto: CreateJobDto): Promise<Job> {
    return this.jobsService.create(createJobDto);
  }

  @Patch(':id')
  async update(
    @Param('id') id: string,
    @Body() updateJobDto: UpdateJobDto,
  ): Promise<Job> {
    return this.jobsService.update(+id, updateJobDto);
  }

  @Delete(':id')
  async remove(@Param('id') id: string): Promise<void> {
    return this.jobsService.remove(+id);
  }
}