/**
 * Contract Agreement - CRUD tests
 */
const { test, expect } = require('../../fixtures/auth.fixture');
const { loginAndCreateContext, apiGet } = require('../../helpers/api');

test.describe('Contract Agreement - Document Admin', () => {
  test('CA001 - Contract agreement list page loads', async ({ page, request }) => {
    const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
    const session = await apiLogin(request, 'admin');
    await injectAuth(page, session);
    await page.goto('/contract-agreement');
    await page.waitForLoadState('networkidle');

    const bodyText = await page.locator('body').innerText();
    expect(bodyText.length).toBeGreaterThan(0);
    const hasTable = await page.locator('.ant-table').count();
    expect(hasTable).toBeGreaterThan(0);
  });

  test('CA002 - Contract agreement API returns data', async ({}) => {
    const result = await loginAndCreateContext('admin');
    const data = await apiGet(result.context, '/api/contract-agreement/');
    expect(data).toBeDefined();
    await result.context.dispose();
  });

  test('CA003 - Responsible users API works', async ({}) => {
    const result = await loginAndCreateContext('admin');
    const data = await apiGet(result.context, '/api/contract-agreement/responsible-users/');
    expect(data).toBeDefined();
    await result.context.dispose();
  });

  test('CA004 - Contract badge API works', async ({}) => {
    const result = await loginAndCreateContext('admin');
    const data = await apiGet(result.context, '/api/contract-agreement/badge/');
    expect(data).toBeDefined();
    await result.context.dispose();
  });
});
