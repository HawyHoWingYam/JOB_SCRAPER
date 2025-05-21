// apps/backend/src/main.ts
import { NestFactory } from '@nestjs/core';
import { AppModule } from './app.module';

async function bootstrap() {
  const app = await NestFactory.create(AppModule);
  
  // Enable CORS - add http://192.168.10.171:3000 as an allowed origin
  app.enableCors({
    origin: ['http://localhost:3001', 'http://192.168.10.171:3001', 'http://192.168.10.171:3000', 'http://localhost:3000'],
    methods: 'GET,HEAD,PUT,PATCH,POST,DELETE',
    credentials: true,
  });
  
  app.setGlobalPrefix('api');
  // Listen on all network interfaces
  await app.listen(3001, '0.0.0.0');
}
bootstrap();