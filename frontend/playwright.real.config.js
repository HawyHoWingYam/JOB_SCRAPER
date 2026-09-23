import { defineConfig } from "@playwright/test";
import baseConfig from "./playwright.config.js";

export default defineConfig({
  ...baseConfig,
  testDir: "./real-e2e",
  timeout: 120_000,
  expect: { timeout: 60_000 },
  globalTeardown: "./e2e/global-teardown.js",
  use: {
    ...baseConfig.use,
    trace: "off",
  },
});
