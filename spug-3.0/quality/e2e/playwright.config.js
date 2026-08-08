// Playwright configuration for spug-3.0 E2E tests
const { defineConfig, devices } = require('@playwright/test');
const path = require('path');

// Load .env file if it exists
try {
  const dotenv = require('dotenv');
  dotenv.config({ path: path.join(__dirname, '.env') });
} catch (e) {
  // dotenv not installed, rely on real environment variables
}

const E2E_BASE_URL = process.env.E2E_BASE_URL || 'http://localhost:8080';
const E2E_RETRIES = parseInt(process.env.E2E_RETRIES || '1', 10);
const E2E_WORKERS = parseInt(process.env.E2E_WORKERS || '1', 10);

module.exports = defineConfig({
  testDir: path.join(__dirname, 'tests'),
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: E2E_RETRIES,
  workers: E2E_WORKERS,
  reporter: [
    ['list'],
    ['html', {
      outputFolder: path.join(__dirname, '..', 'reports', 'e2e', 'artifacts', 'html-report'),
      open: 'never',
    }],
    ['json', {
      outputFile: path.join(__dirname, '..', 'reports', 'e2e', 'artifacts', 'test-results.json'),
    }],
  ],
  outputDir: path.join(__dirname, '..', 'reports', 'e2e', 'artifacts', 'test-output'),
  screenshot: 'only-on-failure',
  trace: 'retain-on-failure',
  video: 'retain-on-failure',
  use: {
    baseURL: E2E_BASE_URL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    actionTimeout: 15000,
    navigationTimeout: 30000,
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
    ignoreHTTPSErrors: true,
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1440, height: 900 },
      },
    },
  ],
});
