// Check your database.module.ts file
import { Module } from '@nestjs/common';
import { TypeOrmModule } from '@nestjs/typeorm';
import { ConfigModule, ConfigService } from '@nestjs/config';

@Module({
  imports: [
    TypeOrmModule.forRootAsync({
      imports: [ConfigModule],
      inject: [ConfigService],
      useFactory: (configService: ConfigService) => ({
        type: 'postgres',
        host: configService.get('DATABASE_HOST', 'localhost'),
        port: configService.get('DATABASE_PORT', 5432),
        username: configService.get('DATABASE_USER', 'postgres'),
        password: configService.get('DATABASE_PASSWORD', 'admin'),  // Double-check this is loading correctly
        database: configService.get('DATABASE_NAME', 'job_scraper'),
        entities: [__dirname + '/../**/*.entity{.ts,.js}'],
        synchronize: false, // Change to false temporarily
        // synchronize: configService.get('NODE_ENV', 'development') !== 'production',
      }),
    }),
  ],
})
export class DatabaseModule {}