/**
 * Regulation - CRUD tests
 */
const { test, expect } = require('../../fixtures/auth.fixture');
const { loginAndCreateContext, apiGet } = require('../../helpers/api');

test.describe('Regulation - Document Admin', () => {
  test('REG001 - Regulation list page loads', async ({ page, request }) => {
    const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
    const session = await apiLogin(request, 'admin');
    await injectAuth(page, session);
    await page.goto('/regulation');
    await page.waitForLoadState('networkidle');

    const bodyText = await page.locator('body').innerText();
    expect(bodyText.length).toBeGreaterThan(0);
  });

  test('REG002 - Regulation API returns data', async ({}) => {
    const result = await loginAndCreateContext('admin');
    const data = await apiGet(result.context, '/api/regulation/');
    expect(data).toBeDefined();
    await result.context.dispose();
  });

  test('REG003 - Regulation categories tree API works', async ({}) => {
    const result = await loginAndCreateContext('admin');
    const data = await apiGet(result.context, '/api/regulation/categories/tree/');
    expect(data).toBeDefined();
    await result.context.dispose();
  });
});
