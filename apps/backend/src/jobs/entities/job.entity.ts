// apps/backend/src/jobs/entities/job.entity.ts
import { Entity, Column, PrimaryGeneratedColumn, CreateDateColumn, UpdateDateColumn } from 'typeorm';

@Entity('jobs')
export class Job {
  @PrimaryGeneratedColumn()
  id: number;

  @Column({ type: 'varchar', length: 255, nullable: true })
  name: string; // Job title

  @Column({ type: 'text', nullable: true })
  description: string;

  @Column({ name: 'company_name', type: 'varchar', length: 255, nullable: true })
  companyName: string;

  @Column({ type: 'varchar', length: 255, nullable: true })
  location: string;

  @Column({ name: 'work_type', type: 'varchar', length: 100, nullable: true })
  workType: string;

  @Column({ name: 'salary_description', type: 'varchar', length: 255, nullable: true })
  salaryDescription: string;

  @Column({ name: 'date_posted', type: 'varchar', length: 100, nullable: true })
  datePosted: string;

  @Column({ name: 'date_scraped', type: 'timestamp', default: () => 'CURRENT_TIMESTAMP' })
  dateScraped: Date;

  @Column({ type: 'varchar', length: 100, nullable: true })
  source: string; // e.g., "Indeed", "LinkedIn"

  @Column({ name: 'job_class', type: 'varchar', length: 100, nullable: true })
  jobClass: string;

  @Column({ name: 'job_subclass', type: 'varchar', length: 100, nullable: true })
  jobSubclass: string;

  @Column({ type: 'text', nullable: true })
  other: string;

  @Column({ type: 'text', nullable: true })
  remark: string;

  @Column({ name: 'company_id', type: 'int', nullable: true })
  companyId: number;

  @Column({ name: 'source_id', type: 'int', nullable: true })
  sourceId: number;

  @Column({ name: 'job_class_id', type: 'int', nullable: true })
  jobClassId: number;

  @Column({ name: 'job_subclass_id', type: 'int', nullable: true })
  jobSubclassId: number;

  @Column({ name: 'internal_id', type: 'int', nullable: true })
  internalId: number;

  // @CreateDateColumn({ name: 'created_at' })
  // createdAt: Date;

  // @UpdateDateColumn({ name: 'updated_at' })
  // updatedAt: Date;
}