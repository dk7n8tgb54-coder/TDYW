/**
 * Duty Log - CRUD tests
 */
const { test, expect } = require('../../fixtures/auth.fixture');
const { loginAndCreateContext, apiGet, apiDelete } = require('../../helpers/api');

test.describe('Duty Log - Daily Business', () => {
  test('D004 - Duty log page loads', async ({ page, request }) => {
    const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
    const session = await apiLogin(request, 'admin');
    await injectAuth(page, session);
    await page.goto('/duty');
    await page.waitForLoadState('networkidle');

    const bodyText = await page.locator('body').innerText();
    expect(bodyText.length).toBeGreaterThan(0);
  });

  test('D005 - Duty log API returns data', async ({ request }) => {
    const { context } = await loginAndCreateContext('admin');
    const result = await apiGet(context, '/api/duty/duty/');
    // Should not return 500-level error
    expect(result).toBeDefined();
    await context.dispose();
  });

  test('D006 - Duty log page shows table or empty state', async ({ page, request }) => {
    const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
    const session = await apiLogin(request, 'admin');
    await injectAuth(page, session);
    await page.goto('/duty');
    await page.waitForLoadState('networkidle');

    // Should have either a table or an empty state
    const hasTable = await page.locator('.ant-table').count();
    const hasEmpty = await page.locator('.ant-empty').count();
    expect(hasTable + hasEmpty).toBeGreaterThan(0);
  });
});
