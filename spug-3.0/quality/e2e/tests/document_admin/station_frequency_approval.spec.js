/**
 * Station Frequency Approval - CRUD tests
 */
const { test, expect } = require('../../fixtures/auth.fixture');
const { loginAndCreateContext, apiGet } = require('../../helpers/api');

test.describe('Station Frequency Approval - Document Admin', () => {
  test('SF001 - Station frequency approval list page loads', async ({ page, request }) => {
    const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
    const session = await apiLogin(request, 'admin');
    await injectAuth(page, session);
    await page.goto('/station-frequency-approval');
    await page.waitForLoadState('networkidle');

    const bodyText = await page.locator('body').innerText();
    expect(bodyText.length).toBeGreaterThan(0);
    const hasTable = await page.locator('.ant-table').count();
    expect(hasTable).toBeGreaterThan(0);
  });

  test('SF002 - Station frequency approval API returns data', async ({}) => {
    const result = await loginAndCreateContext('admin');
    const data = await apiGet(result.context, '/api/radio-license/approvals/');
    expect(data).toBeDefined();
    await result.context.dispose();
  });

  test('SF003 - Responsible users API works', async ({}) => {
    const result = await loginAndCreateContext('admin');
    const data = await apiGet(result.context, '/api/radio-license/approvals/responsible-users/');
    expect(data).toBeDefined();
    await result.context.dispose();
  });

  test('SF004 - Approval badge API works', async ({}) => {
    const result = await loginAndCreateContext('admin');
    const data = await apiGet(result.context, '/api/radio-license/approvals/badge/');
    expect(data).toBeDefined();
    await result.context.dispose();
  });
});
