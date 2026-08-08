/**
 * Permission tests - verify access control works correctly.
 */
const { test, expect } = require('../../fixtures/auth.fixture');
const { loginAndCreateContext, apiGet } = require('../../helpers/api');

const ADMIN_USER = process.env.E2E_ADMIN_USERNAME || 'admin';
const ADMIN_PWD = process.env.E2E_ADMIN_PASSWORD || (() => { throw new Error('E2E_ADMIN_PASSWORD not set. Copy environments/local.example.env to .env and fill in credentials.'); })();

test.describe('Permission Tests', () => {
  test('P001 - Admin can see all menu items', async ({ page, request }) => {
    const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
    const session = await apiLogin(request, 'admin');
    await injectAuth(page, session);
    await page.goto('/home');
    await page.waitForLoadState('networkidle');

    // Admin (is_supper) should see system management
    const submenu = page.locator('.ant-menu-submenu-title').filter({ hasText: '系统管理' });
    expect(await submenu.count()).toBeGreaterThan(0);
  });

  test('P002 - Unauthenticated user cannot access protected API', async ({ request }) => {
    // Try to access API without token
    const response = await request.get('/api/account/user/');
    const body = await response.json();

    // Should return error (not authenticated)
    expect(body.error || response.status() >= 400).toBeTruthy();
  });

  test('P003 - Unauthenticated user cannot access document API', async ({ request }) => {
    const response = await request.get('/api/document/folder/');
    const body = await response.json();
    expect(body.error || response.status() >= 400).toBeTruthy();
  });

  test('P004 - Protected route requires authentication', async ({ page }) => {
    await page.goto('/');
    await page.evaluate(() => sessionStorage.clear());
    await page.goto('/system/account');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);

    // Unauthenticated user should not see protected content
    const hasLoginInput = await page.locator('input[placeholder="请输入账户"]').count();
    const hasAccountTable = await page.locator('.ant-table').count();
    expect(hasLoginInput > 0 || hasAccountTable === 0).toBeTruthy();
  });

  test('P005 - System management route requires auth', async ({ page }) => {
    await page.goto('/');
    await page.evaluate(() => sessionStorage.clear());
    await page.goto('/system/role');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);

    const hasLoginInput = await page.locator('input[placeholder="请输入账户"]').count();
    const hasRoleTable = await page.locator('.ant-table').count();
    expect(hasLoginInput > 0 || hasRoleTable === 0).toBeTruthy();
  });

  test('P006 - Document route requires auth', async ({ page }) => {
    await page.goto('/');
    await page.evaluate(() => sessionStorage.clear());
    await page.goto('/document');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);

    const hasLoginInput = await page.locator('input[placeholder="请输入账户"]').count();
    // Document page should not show file/folder content without auth
    const hasFileList = await page.locator('.ant-table, .file-list, .folder-list').count();
    expect(hasLoginInput > 0 || hasFileList === 0).toBeTruthy();
  });

  test('P007 - Invalid token is rejected', async ({ request }) => {
    const response = await request.get('/api/account/user/', {
      headers: { 'X-Token': 'invalid_token_12345' },
    });
    const body = await response.json();
    expect(body.error || response.status() >= 400).toBeTruthy();
  });

  test('P008 - Home page statistic API requires auth', async ({ request }) => {
    const response = await request.get('/api/home/statistic/');
    const body = await response.json();
    expect(body.error || response.status() >= 400).toBeTruthy();
  });

  test('P009 - Audit log API requires auth', async ({ request }) => {
    const response = await request.get('/api/logs/audit/');
    const body = await response.json();
    expect(body.error || response.status() >= 400).toBeTruthy();
  });

  test('P010 - Deleted schedule API returns 404 or error', async ({ request }) => {
    const { loginAndCreateContext } = require('../../helpers/api');
    const result = await loginAndCreateContext('admin');
    const response = await result.context.get('/api/schedule/');
    // Should return 404 or error (module deleted)
    expect(response.status() === 404 || response.status() === 405).toBeTruthy();
    await result.context.dispose();
  });
});
