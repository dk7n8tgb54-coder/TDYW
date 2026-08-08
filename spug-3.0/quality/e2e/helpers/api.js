/**
 * API helper - provides utilities for making API calls during tests.
 * Used for setup, teardown, and verification of test data.
 */
const { request } = require('@playwright/test');

const BASE_URL = process.env.E2E_BASE_URL || 'http://localhost:8080';

/**
 * Create an authenticated API context.
 */
async function createApiContext(token) {
  return request.newContext({
    baseURL: BASE_URL,
    extraHTTPHeaders: {
      'X-Token': token,
      'Content-Type': 'application/json',
    },
  });
}

/**
 * Login via API and return an authenticated context + token.
 */
async function loginAndCreateContext(role = 'admin') {
  const creds = {
    admin: {
      username: process.env.E2E_ADMIN_USERNAME || 'admin',
      password: process.env.E2E_ADMIN_PASSWORD || (() => { throw new Error('E2E_ADMIN_PASSWORD not set. Copy environments/local.example.env to .env and fill in credentials.'); })(),
    },
    tester: {
      username: process.env.E2E_TEST_USERNAME || 'e2e_tester',
      password: process.env.E2E_TEST_PASSWORD || (() => { throw new Error('E2E_TEST_PASSWORD not set. Copy environments/local.example.env to .env and fill in credentials.'); })(),
    },
  };

  const c = creds[role] || creds.admin;
  const ctx = await request.newContext({ baseURL: BASE_URL });
  const response = await ctx.post('/api/account/login/', {
    data: { username: c.username, password: c.password, type: 'default' },
  });
  const body = await response.json();

  if (body.error) {
    throw new Error(`Login failed: ${body.error}`);
  }

  const token = body.data.access_token;
  await ctx.dispose();

  const authedCtx = await createApiContext(token);
  return { context: authedCtx, token, data: body.data };
}

/**
 * Make an authenticated API request.
 */
async function apiGet(ctx, path) {
  const response = await ctx.get(path);
  return response.json();
}

async function apiPost(ctx, path, data) {
  const response = await ctx.post(path, { data });
  return response.json();
}

async function apiPatch(ctx, path, data) {
  const response = await ctx.patch(path, { data });
  return response.json();
}

async function apiDelete(ctx, path, data) {
  const response = await ctx.delete(path, { data });
  return response.json();
}

/**
 * Verify API response doesn't contain an error.
 * Throws if HTTP 200 + {"error": "..."} pattern is detected.
 */
function assertNoApiError(result, context = '') {
  if (result && result.error) {
    throw new Error(`API error${context ? ` (${context})` : ''}: ${result.error}`);
  }
}

/**
 * Find a test record by its E2E_ prefix in API response data.
 */
function findTestRecord(data, prefix = 'E2E_', field = 'title') {
  if (!data || !Array.isArray(data)) return null;
  return data.find(item => item[field] && String(item[field]).startsWith(prefix));
}

module.exports = {
  createApiContext,
  loginAndCreateContext,
  apiGet,
  apiPost,
  apiPatch,
  apiDelete,
  assertNoApiError,
  findTestRecord,
};
