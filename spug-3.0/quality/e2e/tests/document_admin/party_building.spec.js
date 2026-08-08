/**
 * Party Building Documents - Access and isolation tests
 */
const { test, expect } = require('../../fixtures/auth.fixture');

test.describe('Party Building Documents - Document Admin', () => {
  test('PB001 - Party building documents page loads', async ({ page, request }) => {
    const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
    const session = await apiLogin(request, 'admin');
    await injectAuth(page, session);
    await page.goto('/document/party-building-documents');
    await page.waitForLoadState('networkidle');

    const bodyText = await page.locator('body').innerText();
    expect(bodyText.length).toBeGreaterThan(0);
  });

  test('PB002 - Party building documents menu is visible for admin', async ({ page, request }) => {
    const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
    const session = await apiLogin(request, 'admin');
    await injectAuth(page, session);
    await page.goto('/home');
    await page.waitForLoadState('networkidle');

    // Expand 资料库 submenu
    const submenu = page.locator('.ant-menu-submenu-title').filter({ hasText: '资料库' });
    if (await submenu.isVisible()) {
      await submenu.click();
      await page.waitForTimeout(500);
    }

    // Check for 党建工作 menu item
    const partyItem = page.locator('.ant-menu-item').filter({ hasText: '党建工作' });
    const isVisible = await partyItem.count() > 0;
    expect(isVisible).toBe(true);
  });
});
