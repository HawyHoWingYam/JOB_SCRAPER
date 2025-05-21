// apps/backend/src/jobs/jobs.controller.ts
import { Controller, Get, Post, Body, Patch, Param, Delete, Query } from '@nestjs/common';
import { JobsService } from './jobs.service';
import { CreateJobDto, UpdateJobDto } from './dto/job.dto';
import { Job } from './entities/job.entity';

@Controller('jobs')
export class JobsController {
  constructor(private readonly jobsService: JobsService) {}

  @Get()
  async findAll(@Query('query') query?: string): Promise<Job[]> {
    console.log(`GET /api/jobs endpoint called${query ? ` with search query: ${query}` : ''}`);
    try {
      const jobs = query 
        ? await this.jobsService.searchJobs(query)
        : await this.jobsService.findAll();
      
      console.log(`Found ${jobs.length} jobs`);
      return jobs;
    } catch (error) {
      console.error('Error in findAll:', error);
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