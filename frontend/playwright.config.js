import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: "line",
  use: {
    baseURL: "http://127.0.0.1:5174",
    trace: "retain-on-failure",
  },
  webServer: {
    command: "VITE_API_URL=http://127.0.0.1:8000 npm run dev -- --host 127.0.0.1 --port 5174",
    url: "http://127.0.0.1:5174",
    timeout: 120_000,
    reuseExistingServer: false,
  },
});
