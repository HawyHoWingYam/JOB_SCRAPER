// apps/backend/src/health/health.service.ts
import { Injectable, Logger } from '@nestjs/common';
import { InjectConnection } from '@nestjs/typeorm';
import { Connection } from 'typeorm';
import { ConfigService } from '@nestjs/config';

@Injectable()
export class HealthService {
  private readonly logger = new Logger(HealthService.name);

  constructor(
    @InjectConnection()
    private connection: Connection,
    private configService: ConfigService,
  ) {}

  async check() {
    try {
      // Log connection details
      this.logger.log('Database connection details:');
      this.logger.log(`Host: ${this.configService.get('DATABASE_HOST')}`);
      this.logger.log(`Port: ${this.configService.get('DATABASE_PORT')}`);
      this.logger.log(`Username: ${this.configService.get('DATABASE_USER')}`);
      this.logger.log(`Database: ${this.configService.get('DATABASE_NAME')}`);
      // Don't log the full password, just a hint
      const password = this.configService.get('DATABASE_PASSWORD');
      this.logger.log(`Password: ${password ? `${password.substring(0, 1)}...` : 'not set'}`);
      
      // Test database connection
      const dbConnected = this.connection.isConnected;
      
      return {
        status: 'ok',
        database: {
          connected: dbConnected,
          config: {
            host: this.configService.get('DATABASE_HOST'),
            port: this.configService.get('DATABASE_PORT'),
            username: this.configService.get('DATABASE_USER'),
            database: this.configService.get('DATABASE_NAME'),
          }
        },
        timestamp: new Date().toISOString(),
      };
    } catch (error) {
      this.logger.error(`Database connection error: ${error.message}`);
      
      return {
        status: 'error',
        database: {
          connected: false,
          message: error.message,
          config: {
            host: this.configService.get('DATABASE_HOST'),
            port: this.configService.get('DATABASE_PORT'),
            username: this.configService.get('DATABASE_USER'),
            database: this.configService.get('DATABASE_NAME'),
          }
        },
        timestamp: new Date().toISOString(),
      };
    }
  }
}