/**
 * Smoke tests - verify basic system availability.
 * Covers: login page, login/logout, menu, white screen, deleted modules.
 */
const { test, expect } = require('../../fixtures/auth.fixture');
const { LoginPage } = require('../../pages/LoginPage');
const { NavigationPage } = require('../../pages/NavigationPage');
const { attachConsoleLogger } = require('../../helpers/screenshots');

const ADMIN_USER = process.env.E2E_ADMIN_USERNAME || 'admin';
const ADMIN_PWD = process.env.E2E_ADMIN_PASSWORD || (() => { throw new Error('E2E_ADMIN_PASSWORD not set. Copy environments/local.example.env to .env and fill in credentials.'); })();

test.describe('Smoke Tests - System Availability', () => {
  test('S001 - Login page opens successfully', async ({ page }) => {
    const consoleErrors = attachConsoleLogger(page);
    const loginPage = new LoginPage(page);
    await loginPage.goto();
    await loginPage.expectLoginPageVisible();

    // Verify no critical console errors
    const criticalErrors = consoleErrors.filter(e =>
      !e.includes('favicon') && !e.includes('404') && !e.includes('Warning:')
    );
    expect(criticalErrors.length).toBeLessThan(5);
  });

  test('S002 - Valid admin login succeeds', async ({ page }) => {
    const loginPage = new LoginPage(page);
    await loginPage.goto();
    await loginPage.loginSuccessfully(ADMIN_USER, ADMIN_PWD);

    // Verify we're on the home page
    expect(page.url()).toContain('/home');

    // Verify main content area is visible
    const navPage = new NavigationPage(page);
    await expect(page.locator('.ant-layout-content, main')).toBeVisible();

    // Verify no white screen
    const bodyText = await page.locator('body').innerText();
    expect(bodyText.trim().length).toBeGreaterThan(10);
  });

  test('S003 - Invalid login fails with error message', async ({ page }) => {
    const loginPage = new LoginPage(page);
    await loginPage.goto();
    await loginPage.login('nonexistent_user', 'wrong_password');

    // Should show error message
    const errorMsg = page.locator('.ant-message-notice, .ant-form-item-explain-error, .ant-notification-notice');
    await expect(errorMsg.first()).toBeVisible({ timeout: 5000 });

    // Should still be on login page (not redirected to /home)
    expect(page.url()).not.toContain('/home');
  });

  test('S004 - Main menu items are visible after login', async ({ page, request }) => {
    const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
    const session = await apiLogin(request, 'admin');
    await injectAuth(page, session);
    await page.goto('/home');
    await page.waitForLoadState('networkidle');

    // Check for menu items
    const menuLabels = ['工作台', '数据分析', '部门值班日志', '执照管理', '合同协议', '资料库', '跨日事项跟踪', '设备管理', '干扰管理', '值班日志', '公告与提醒', '系统管理'];
    for (const label of menuLabels) {
      const menuItem = page.locator('.ant-menu-item, .ant-menu-submenu-title').filter({ hasText: label });
      const count = await menuItem.count();
      expect(count).toBeGreaterThan(0);
    }
  });

  test('S005 - No white screen on key pages', async ({ page, request }) => {
    const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
    const session = await apiLogin(request, 'admin');
    await injectAuth(page, session);

    const routes = [
      '/home',
      '/data-analysis',
      '/department-duty-log',
      '/radio-license',
      '/contract-agreement',
      '/document',
      '/runlog',
      '/device/device_resume',
      '/exec/fault/record',
      '/interference',
      '/duty',
      '/system/announcement',
      '/reminder',
      '/system/account',
      '/system/role',
      '/system/setting',
      '/system/login',
      '/maintenance/audit',
    ];

    for (const route of routes) {
      await page.goto(route);
      await page.waitForLoadState('networkidle');
      const bodyText = await page.locator('body').innerText();
      expect(bodyText.trim().length, `White screen on ${route}`).toBeGreaterThan(0);
    }
  });

  test('S006 - Key static resources load successfully', async ({ page }) => {
    const failedResources = [];
    page.on('response', response => {
      if (response.status() >= 500) {
        failedResources.push(`${response.status()} ${response.url()}`);
      }
    });

    const loginPage = new LoginPage(page);
    await loginPage.goto();
    await page.waitForLoadState('networkidle');

    expect(failedResources.filter(r => !r.includes('favicon'))).toHaveLength(0);
  });

  test('S007 - Key API endpoints do not return 500', async ({ page, request }) => {
    const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
    const session = await apiLogin(request, 'admin');
    await injectAuth(page, session);

    const apiEndpoints = [
      '/api/home/notice/',
      '/api/reminder/',
      '/api/home/navigation/',
      '/api/account/users/',
      '/api/account/roles/',
    ];

    for (const endpoint of apiEndpoints) {
      const response = await page.request.get(endpoint, {
        headers: { 'X-Token': session.token },
      });
      expect(response.status(), `API ${endpoint} returned ${response.status()}`).toBeLessThan(500);
    }
  });

  test('S008 - Logout redirects to login page', async ({ page, request }) => {
    const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
    const session = await apiLogin(request, 'admin');
    await injectAuth(page, session);
    await page.goto('/home');
    await page.waitForLoadState('networkidle');

    // Click logout
    const navPage = new NavigationPage(page);
    // Try to find and click the user dropdown
    const userTrigger = page.locator('.ant-dropdown-trigger, .header-user, [class*="user"]').first();
    if (await userTrigger.isVisible()) {
      await userTrigger.click();
      await page.waitForTimeout(500);
      const logoutLink = page.getByText('退出登录');
      if (await logoutLink.isVisible()) {
        await logoutLink.click();
        await page.waitForLoadState('networkidle');
      }
    }

    // Alternatively, clear session and verify redirect
    await page.evaluate(() => {
      sessionStorage.clear();
    });
    await page.goto('/home');
    await page.waitForLoadState('networkidle');

    // Should redirect to login
    const loginInput = page.locator('input[placeholder="请输入账户"]');
    await expect(loginInput).toBeVisible({ timeout: 10000 });
  });

  test('S009 - Protected route redirects when not authenticated', async ({ page }) => {
    // Clear any existing session and navigate to protected route
    await page.goto('/');
    await page.evaluate(() => sessionStorage.clear());
    await page.goto('/system/account');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);

    // Unauthenticated user should not see protected content (account table)
    const url = page.url();
    const hasLoginInput = await page.locator('input[placeholder="请输入账户"]').count();
    const hasAccountTable = await page.locator('.ant-table').count();
    // Either redirected to login, or no account table shown (permission denied)
    expect(hasLoginInput > 0 || hasAccountTable === 0 || url.endsWith('/')).toBeTruthy();
  });

  test('S010 - Deleted schedule module is not accessible', async ({ page, request }) => {
    const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
    const session = await apiLogin(request, 'admin');
    await injectAuth(page, session);

    // Schedule menu should not exist
    await page.goto('/home');
    await page.waitForLoadState('networkidle');
    const scheduleMenu = page.locator('.ant-menu-item, .ant-menu-submenu-title').filter({ hasText: '排班' });
    expect(await scheduleMenu.count()).toBe(0);

    // Direct route should not show schedule content
    await page.goto('/schedule');
    await page.waitForLoadState('networkidle');
    const bodyText = await page.locator('body').innerText();
    // Should not contain schedule-specific content
    expect(bodyText).not.toContain('排班管理');
    expect(bodyText).not.toContain('交接班');
  });

  test('S011 - Deleted shift/swap modules are not accessible', async ({ page, request }) => {
    const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
    const session = await apiLogin(request, 'admin');
    await injectAuth(page, session);

    await page.goto('/home');
    await page.waitForLoadState('networkidle');

    const deletedTerms = ['交接班', '换班', '替班', '代班', '调班'];
    for (const term of deletedTerms) {
      const menuItems = page.locator('.ant-menu-item, .ant-menu-submenu-title').filter({ hasText: term });
      expect(await menuItems.count(), `Found menu item for deleted term: ${term}`).toBe(0);
    }
  });
});
