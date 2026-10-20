import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  reporter: [["junit", { outputFile: "/reports/e2e.xml" }]],
  outputDir: "/tmp/playwright-results",
  use: {
    baseURL: process.env.BASE_URL || "http://localhost:8181",
    browserName: "chromium",
    headless: true,
  },
});
