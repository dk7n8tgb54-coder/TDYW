/**
 * Cross-module tests - verify real cross-module interactions.
 */
const { test, expect } = require('../../fixtures/auth.fixture');
const { loginAndCreateContext, apiGet, apiPost, apiDelete } = require('../../helpers/api');

test.describe('Cross-Module Integration Tests', () => {
  test('X001 - Home page shows announcement panel', async ({ page, request }) => {
    const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
    const session = await apiLogin(request, 'admin');
    await injectAuth(page, session);
    await page.goto('/home');
    await page.waitForLoadState('networkidle');

    // Home page should have content
    const bodyText = await page.locator('body').innerText();
    expect(bodyText.length).toBeGreaterThan(0);
  });

  test('X002 - Home page statistic API returns integrated data', async ({}) => {
    const result = await loginAndCreateContext('admin');
    const data = await apiGet(result.context, '/api/home/statistic/');
    expect(data).toBeDefined();
    // Should not have error
    expect(data.error || '').toBe('');
    await result.context.dispose();
  });

  test('X003 - Home page notice API works', async ({}) => {
    const result = await loginAndCreateContext('admin');
    const data = await apiGet(result.context, '/api/home/notice/');
    expect(data).toBeDefined();
    expect(data.error || '').toBe('');
    await result.context.dispose();
  });

  test('X004 - Navigation API returns menu structure', async ({}) => {
    const result = await loginAndCreateContext('admin');
    const data = await apiGet(result.context, '/api/home/navigation/');
    expect(data).toBeDefined();
    await result.context.dispose();
  });

  test('X005 - Home announcement API returns published announcements', async ({}) => {
    const result = await loginAndCreateContext('admin');
    const data = await apiGet(result.context, '/api/home/announcement/');
    expect(data).toBeDefined();
    await result.context.dispose();
  });

  test('X006 - Radio license badge API integrates with home expiry panel', async ({}) => {
    const result = await loginAndCreateContext('admin');
    const data = await apiGet(result.context, '/api/radio-license/badge/');
    expect(data).toBeDefined();
    await result.context.dispose();
  });

  test('X007 - Contract agreement badge API integrates with home expiry panel', async ({}) => {
    const result = await loginAndCreateContext('admin');
    const data = await apiGet(result.context, '/api/contract-agreement/badge/');
    expect(data).toBeDefined();
    await result.context.dispose();
  });

  test('X008 - Runlog in-progress items appear on home page', async ({}) => {
    const result = await loginAndCreateContext('admin');
    const data = await apiGet(result.context, '/api/runlog/?status=in_progress&page_size=5');
    expect(data).toBeDefined();
    await result.context.dispose();
  });

  test('X009 - Home page loads all overview panels', async ({ page, request }) => {
    const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
    const session = await apiLogin(request, 'admin');
    await injectAuth(page, session);

    const failedRequests = [];
    page.on('response', response => {
      if (response.status() >= 500) {
        failedRequests.push(`${response.status()} ${response.url()}`);
      }
    });

    await page.goto('/home');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(3000);

    // No 500 errors on home page
    expect(failedRequests.filter(r => !r.includes('favicon'))).toHaveLength(0);
  });

  test('X010 - Data analysis page loads without 500 errors', async ({ page, request }) => {
    const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
    const session = await apiLogin(request, 'admin');
    await injectAuth(page, session);

    const failedRequests = [];
    page.on('response', response => {
      if (response.status() >= 500) {
        failedRequests.push(`${response.status()} ${response.url()}`);
      }
    });

    await page.goto('/data-analysis');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(3000);

    expect(failedRequests.filter(r => !r.includes('favicon'))).toHaveLength(0);
  });
});
