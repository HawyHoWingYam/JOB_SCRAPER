import { defineConfig } from '@playwright/test';

// Every API request is intercepted by the Scheduler fixtures. No backend/database.
export default defineConfig({
  testDir: './e2e/scheduler',
  outputDir: '/tmp/job-scraper-scheduler-playwright',
  timeout: 30000,
  workers: 1,
  reporter: 'line',
  use: { baseURL: 'http://127.0.0.1:5176', trace: 'retain-on-failure' },
  webServer: {
    command: 'VITE_API_URL=http://127.0.0.1:5176 npm run dev -- --host 127.0.0.1 --port 5176 --strictPort',
    url: 'http://127.0.0.1:5176',
    reuseExistingServer: false,
  },
});
