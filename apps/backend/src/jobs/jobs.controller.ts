// apps/backend/src/jobs/jobs.controller.ts
import { Controller, Get, Post, Body, Patch, Param, Delete, Query } from '@nestjs/common';
import { JobsService } from './jobs.service';
import { CreateJobDto, UpdateJobDto } from './dto/job.dto';
import { Job } from './entities/job.entity';
import { PaginatedResponse } from './types/pagination.types';

@Controller('jobs')
export class JobsController {
  constructor(private readonly jobsService: JobsService) { }

  @Get()
  async findAll(
    @Query('query') query?: string,
    @Query('mode') mode?: 'AND' | 'OR',
    @Query('page') page?: string,
    @Query('limit') limit?: string
  ): Promise<PaginatedResponse<Job>> {
    // Auto-detect slash-separated queries and use OR mode unless explicitly specified
    const hasSlash = query?.includes('/');
    const effectiveMode = mode || (hasSlash ? 'OR' : 'AND');
    
    // Parse pagination params
    const pageNum = page ? parseInt(page, 10) : 1;
    const limitNum = limit ? parseInt(limit, 10) : 20;

    console.log(`GET /api/jobs endpoint called${query ? ` with search query: ${query}` : ''} 
      (mode: ${effectiveMode}, page: ${pageNum}, limit: ${limitNum})`);

    try {
      if (query) {
        return this.jobsService.searchJobsPaginated(query, effectiveMode, pageNum, limitNum);
      } else {
        return this.jobsService.findAllPaginated(pageNum, limitNum);
      }
    } catch (error) {
      console.error('Error in findAll:', error);
      throw error;
    }
  }

  @Post('search')
  async searchJobs(
    @Body() searchParams: { query: string[] | string, page?: number, limit?: number }
  ): Promise<PaginatedResponse<Job>> {
    console.log('Search params received:', searchParams);

    // Handle pagination params
    const page = searchParams.page || 1;
    const limit = searchParams.limit || 20;

    // Handle both string and array formats
    let searchTerms: string[] = [];
    if (typeof searchParams.query === 'string') {
      searchTerms = [searchParams.query];
    } else if (Array.isArray(searchParams.query)) {
      searchTerms = searchParams.query;
    }

    console.log(`POST /api/jobs/search with terms:`, searchTerms, `page: ${page}, limit: ${limit}`);

    try {
      if (searchTerms.length === 0) {
        return this.jobsService.findAllPaginated(page, limit);
      }
      
      return this.jobsService.searchWithTermsPaginated(searchTerms, page, limit);
    } catch (error) {
      console.error('Error in searchJobs:', error);
      throw error;
    }
  }

  @Get('job-classes')
  async getJobClasses() {
    return this.jobsService.getJobClasses();
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