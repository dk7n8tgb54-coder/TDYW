/**
 * System Management - View and list tests
 */
const { test, expect } = require('../../fixtures/auth.fixture');
const { loginAndCreateContext, apiGet } = require('../../helpers/api');

test.describe('System Management', () => {
  test('SYS001 - Account list page loads', async ({ page, request }) => {
    const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
    const session = await apiLogin(request, 'admin');
    await injectAuth(page, session);
    await page.goto('/system/account');
    await page.waitForLoadState('networkidle');

    const bodyText = await page.locator('body').innerText();
    expect(bodyText.length).toBeGreaterThan(0);
    const hasTable = await page.locator('.ant-table').count();
    expect(hasTable).toBeGreaterThan(0);
  });

  test('SYS002 - Role list page loads', async ({ page, request }) => {
    const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
    const session = await apiLogin(request, 'admin');
    await injectAuth(page, session);
    await page.goto('/system/role');
    await page.waitForLoadState('networkidle');

    const bodyText = await page.locator('body').innerText();
    expect(bodyText.length).toBeGreaterThan(0);
  });

  test('SYS003 - Tenant list page loads', async ({ page, request }) => {
    const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
    const session = await apiLogin(request, 'admin');
    await injectAuth(page, session);
    await page.goto('/system/tenant');
    await page.waitForLoadState('networkidle');

    const bodyText = await page.locator('body').innerText();
    expect(bodyText.length).toBeGreaterThan(0);
  });

  test('SYS004 - System settings page loads', async ({ page, request }) => {
    const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
    const session = await apiLogin(request, 'admin');
    await injectAuth(page, session);
    await page.goto('/system/setting');
    await page.waitForLoadState('networkidle');

    const bodyText = await page.locator('body').innerText();
    expect(bodyText.length).toBeGreaterThan(0);
  });

  test('SYS005 - Login history page loads', async ({ page, request }) => {
    const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
    const session = await apiLogin(request, 'admin');
    await injectAuth(page, session);
    await page.goto('/system/login');
    await page.waitForLoadState('networkidle');

    const bodyText = await page.locator('body').innerText();
    expect(bodyText.length).toBeGreaterThan(0);
  });

  test('SYS006 - Audit log page loads', async ({ page, request }) => {
    const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
    const session = await apiLogin(request, 'admin');
    await injectAuth(page, session);
    await page.goto('/maintenance/audit');
    await page.waitForLoadState('networkidle');

    const bodyText = await page.locator('body').innerText();
    expect(bodyText.length).toBeGreaterThan(0);
  });

  test('SYS007 - Account API returns data', async ({}) => {
    const result = await loginAndCreateContext('admin');
    const data = await apiGet(result.context, '/api/account/user/');
    expect(data).toBeDefined();
    await result.context.dispose();
  });

  test('SYS008 - Role API returns data', async ({}) => {
    const result = await loginAndCreateContext('admin');
    const data = await apiGet(result.context, '/api/account/role/');
    expect(data).toBeDefined();
    await result.context.dispose();
  });

  test('SYS009 - Tenant API returns data', async ({}) => {
    const result = await loginAndCreateContext('admin');
    const data = await apiGet(result.context, '/api/account/tenant/');
    expect(data).toBeDefined();
    await result.context.dispose();
  });

  test('SYS010 - Audit log API returns data', async ({}) => {
    const result = await loginAndCreateContext('admin');
    const data = await apiGet(result.context, '/api/logs/audit/');
    expect(data).toBeDefined();
    await result.context.dispose();
  });

  test('SYS011 - Login history API returns data', async ({}) => {
    const result = await loginAndCreateContext('admin');
    const data = await apiGet(result.context, '/api/account/login/history/');
    expect(data).toBeDefined();
    await result.context.dispose();
  });

  test('SYS012 - Setting API returns data', async ({}) => {
    const result = await loginAndCreateContext('admin');
    const data = await apiGet(result.context, '/api/setting/');
    expect(data).toBeDefined();
    await result.context.dispose();
  });

  test('SYS013 - Announcement admin entry visible', async ({ page, request }) => {
    const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
    const session = await apiLogin(request, 'admin');
    await injectAuth(page, session);
    await page.goto('/home');
    await page.waitForLoadState('networkidle');

    // Expand 公告与提醒 submenu
    const submenu = page.locator('.ant-menu-submenu-title').filter({ hasText: '公告与提醒' });
    if (await submenu.isVisible()) {
      await submenu.click();
      await page.waitForTimeout(500);
    }

    const announceItem = page.locator('.ant-menu-item').filter({ hasText: '发布公告' });
    expect(await announceItem.count()).toBeGreaterThan(0);
  });

  test('SYS014 - Data analysis page loads', async ({ page, request }) => {
    const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
    const session = await apiLogin(request, 'admin');
    await injectAuth(page, session);
    await page.goto('/data-analysis');
    await page.waitForLoadState('networkidle');

    const bodyText = await page.locator('body').innerText();
    expect(bodyText.length).toBeGreaterThan(0);
  });
});
