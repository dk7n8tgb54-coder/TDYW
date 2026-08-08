/**
 * Auth fixture - handles login, session management, and user roles.
 * Credentials are read from environment variables, never hardcoded.
 */
const { test: base, expect } = require('@playwright/test');

const E2E_BASE_URL = process.env.E2E_BASE_URL || 'http://localhost:8080';

// Read credentials from environment
const CREDENTIALS = {
  admin: {
    username: process.env.E2E_ADMIN_USERNAME || 'admin',
    password: process.env.E2E_ADMIN_PASSWORD || (() => { throw new Error('E2E_ADMIN_PASSWORD not set. Copy environments/local.example.env to .env and fill in credentials.'); })(),
  },
  tester: {
    username: process.env.E2E_TEST_USERNAME || 'e2e_tester',
    password: process.env.E2E_TEST_PASSWORD || (() => { throw new Error('E2E_TEST_PASSWORD not set. Copy environments/local.example.env to .env and fill in credentials.'); })(),
  },
  user: {
    username: process.env.E2E_USER_USERNAME || '',
    password: process.env.E2E_USER_PASSWORD || '',
  },
  no_doc: {
    username: process.env.E2E_NO_DOC_USERNAME || '',
    password: process.env.E2E_NO_DOC_PASSWORD || '',
  },
  tenant_a: {
    username: process.env.E2E_TENANT_A_USERNAME || '',
    password: process.env.E2E_TENANT_A_PASSWORD || '',
  },
  tenant_b: {
    username: process.env.E2E_TENANT_B_USERNAME || '',
    password: process.env.E2E_TENANT_B_PASSWORD || '',
  },
};

/**
 * Perform API login and return session data.
 * Uses the real login endpoint, stores token in sessionStorage.
 */
async function apiLogin(request, role = 'admin') {
  const creds = CREDENTIALS[role];
  if (!creds.username || !creds.password) {
    throw new Error(`No credentials configured for role: ${role}. Set E2E_${role.toUpperCase().replace('-', '_')}_USERNAME and E2E_${role.toUpperCase().replace('-', '_')}_PASSWORD environment variables.`);
  }

  const response = await request.post('/api/account/login/', {
    data: {
      username: creds.username,
      password: creds.password,
      type: 'default',
    },
  });

  const body = await response.json();

  if (body.error) {
    throw new Error(`Login failed for role ${role} (${creds.username}): ${body.error}`);
  }

  return {
    token: body.data.access_token,
    id: body.data.id,
    nickname: body.data.nickname,
    is_supper: body.data.is_supper,
    tenant_id: body.data.tenant_id,
  };
}

/**
 * Perform browser login via UI - fills the login form and clicks submit.
 * Verifies successful navigation to the main app.
 */
async function uiLogin(page, role = 'admin') {
  const creds = CREDENTIALS[role];
  if (!creds.username || !creds.password) {
    throw new Error(`No credentials configured for role: ${role}`);
  }

  await page.goto('/');
  await page.waitForLoadState('networkidle');

  // Fill username
  const usernameInput = page.locator('input[placeholder="请输入账户"]');
  await usernameInput.fill(creds.username);

  // Fill password
  const passwordInput = page.locator('input[placeholder="请输入密码"]');
  await passwordInput.fill(creds.password);

  // Click login button (antd adds spaces between Chinese chars)
  const loginButton = page.getByRole('button', { name: /登\s*录/ });
  await loginButton.click();

  // Wait for navigation to home page
  await page.waitForURL('**/home**', { timeout: 15000 });
  await page.waitForLoadState('networkidle');
}

/**
 * Inject auth state into a page context (for API-based session setup).
 * Stores token and user info in sessionStorage to match frontend expectations.
 */
async function injectAuth(page, sessionData) {
  await page.addInitScript((data) => {
    sessionStorage.setItem('token', data.token);
    sessionStorage.setItem('id', String(data.id));
    sessionStorage.setItem('nickname', data.nickname);
    sessionStorage.setItem('is_supper', String(data.is_supper));
    sessionStorage.setItem('tenant_id', data.tenant_id || 'admin');
    // permissions are fetched from API, so we set an empty string for now
  }, sessionData);
}

/**
 * Extended test fixture with auth support.
 */
const test = base.extend({
  // Provides an authenticated page for admin role
  adminPage: async ({ page, request }, use) => {
    const session = await apiLogin(request, 'admin');
    await injectAuth(page, session);
    await page.goto('/home');
    await page.waitForLoadState('networkidle');
    await use(page);
  },

  // Provides an authenticated page for tester role (super user)
  testerPage: async ({ page, request }, use) => {
    const session = await apiLogin(request, 'tester');
    await injectAuth(page, session);
    await page.goto('/home');
    await page.waitForLoadState('networkidle');
    await use(page);
  },
});

module.exports = {
  test,
  expect,
  apiLogin,
  uiLogin,
  injectAuth,
  CREDENTIALS,
};
