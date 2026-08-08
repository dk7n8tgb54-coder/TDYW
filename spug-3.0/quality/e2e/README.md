# Playwright E2E Regression Tests for spug-3.0

## Overview

This directory contains Playwright end-to-end regression tests for the spug-3.0 system. Tests simulate real user behavior through a browser, verifying that frontend pages, APIs, backend business logic, permissions, file operations, and cross-module integrations work correctly.

## Directory Structure

```
quality/e2e/
├── README.md                 # This file
├── package.json              # Self-contained Playwright dependency
├── playwright.config.js      # Playwright configuration
├── environments/             # Environment variable templates
│   ├── local.example.env     # Local dev environment template
│   └── test.example.env      # Test server environment template
├── fixtures/                 # Test fixtures
│   ├── auth.fixture.js       # Authentication and user roles
│   └── test-data.fixture.js  # Unique test data generation
├── helpers/                  # Test helper utilities
│   ├── api.js                # API request helpers
│   ├── assertions.js         # Custom assertion helpers
│   ├── cleanup.js            # Test data cleanup
│   └── screenshots.js        # Screenshot and debugging helpers
├── pages/                    # Page Object Models
│   ├── LoginPage.js          # Login page interactions
│   └── NavigationPage.js     # Menu navigation and common UI
├── tests/                    # Test files organized by domain
│   ├── smoke/                # Smoke tests (login, menu, white screen)
│   ├── daily_business/       # Daily business modules
│   ├── document_admin/       # Document and admin modules
│   ├── technical_operations/ # Technical operations modules
│   ├── system_management/    # System management modules
│   ├── permissions/          # Permission and access control
│   └── cross_module/         # Cross-module integration
└── test-data/                # Safe test data files
    └── safe_samples/         # Small, non-sensitive test files
```

## Setup

### 1. Install Dependencies

```bash
cd quality/e2e
npm install
npx playwright install chromium
```

### 2. Configure Environment

Copy the example env file and fill in credentials:

```bash
cp environments/local.example.env .env
# Edit .env with real test credentials
```

**IMPORTANT:** Never commit the `.env` file. Credentials must be passed via environment variables.

### 3. Run Tests

```bash
# Run all tests
npm test

# Run only smoke tests
npm run test:smoke

# Run with specific browser
npm run test:chromium

# Run a specific test file
npx playwright test tests/smoke/smoke.spec.js

# Run with debug mode
npx playwright test --debug

# View HTML report
npm run report
```

## Test Data Strategy

- All test data is prefixed with `E2E_` for easy identification
- Each test creates its own data with unique timestamps
- Tests clean up after themselves via API calls
- No test depends on data from a previous test
- Existing data is never deleted

## Security

- No passwords, tokens, or cookies are committed to the repository
- Credentials are read from environment variables
- `storageState` files are never committed
- Test data files contain only safe, non-sensitive content

## Reports

Test reports are generated in `quality/reports/e2e/`:

- HTML report: `artifacts/html-report/`
- Screenshots: `artifacts/screenshots/`
- Traces: `artifacts/traces/`
- Videos: `artifacts/videos/`
- JSON results: `artifacts/test-results.json`

## Browser Coverage

- Primary: Chromium (desktop, 1440x900 viewport)
- Optional: Firefox, WebKit, mobile viewport (if environment supports)

## Running Against Different Environments

Set the `E2E_BASE_URL` environment variable to target different environments:

```bash
E2E_BASE_URL=http://test-server:8080 npm test
```

**WARNING:** Never run tests against a production system.
