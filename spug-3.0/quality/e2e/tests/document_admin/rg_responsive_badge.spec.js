/**
 * 无线电执照上线门禁 E2E 补充：响应式布局 + 工作台徽标跳转（真实浏览器）。
 *
 * 覆盖：
 * - 桌面端（1440x900）与窄屏（375x667）下执照/批复页面表格渲染、无横向溢出
 * - 弹窗打开后内容不溢出视口
 * - 工作台到期提醒卡片跳转到正确页面
 */
const { test, expect, apiLogin, injectAuth, uiLogin } = require('../../fixtures/auth.fixture');


async function login(page, request) {
  const session = await apiLogin(request, 'admin');
  await injectAuth(page, session);
}


test.describe('Radio License release gate - responsive layout', () => {
  for (const viewport of [
    {name: 'desktop', width: 1440, height: 900},
    {name: 'narrow', width: 375, height: 667},
  ]) {
    test(`执照列表在${viewport.name}视口渲染且无横向溢出`, async ({page, request}) => {
      await login(page, request);
      await page.setViewportSize({width: viewport.width, height: viewport.height});
      await page.goto('/radio-license');
      await page.waitForSelector('.ant-table', {timeout: 15000});
      // 表格渲染出表头
      await expect(page.locator('.ant-table-thead')).toBeVisible();
      // 页面无不可控横向溢出（jsdom 无法验证，真实浏览器检查 body 滚动宽度）
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow).toBeLessThanOrEqual(2);
    });

    test(`批复列表在${viewport.name}视口渲染且无横向溢出`, async ({page, request}) => {
      await login(page, request);
      await page.setViewportSize({width: viewport.width, height: viewport.height});
      await page.goto('/station-frequency-approval');
      await page.waitForSelector('.ant-table', {timeout: 15000});
      await expect(page.locator('.ant-table-thead')).toBeVisible();
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow).toBeLessThanOrEqual(2);
    });
  }

  test('执照详情弹窗内容不溢出视口', async ({page, request}) => {
    await login(page, request);
    await page.setViewportSize({width: 375, height: 667});
    await page.goto('/radio-license');
    // 排除 rc-table 测量行，只等真实数据行
    await page.waitForSelector('tr.ant-table-row', {timeout: 15000});
    await page.locator('tr.ant-table-row').first().dblclick();
    await page.waitForSelector('.ant-modal', {timeout: 10000});
    await expect(page.locator('.ant-modal')).toBeVisible();
    const overflow = await page.evaluate(() => {
      const modal = document.querySelector('.ant-modal');
      return modal ? modal.scrollWidth - modal.clientWidth : 0;
    });
    expect(overflow).toBeLessThanOrEqual(2);
  });
});


test.describe('Radio License release gate - workbench badge navigation', () => {
  test('工作台到期提醒卡片可跳转执照页面', async ({page}) => {
    // 用 UI 登录（最真实路径，规避 apiLogin+injectAuth 的间歇性失败）
    await uiLogin(page, 'admin');
    await page.setViewportSize({width: 1440, height: 900});
    // 登录后已在工作台：到期提醒卡片存在（admin 有执照查看权限）
    const card = page.locator('.ant-card').filter({hasText: '到期提醒'});
    await expect(card.first()).toBeVisible({timeout: 20000});
    // 点击执照行 → /radio-license
    await card.locator('span').filter({hasText: '无线电台执照'}).first().click();
    await page.waitForURL('**/radio-license**', {timeout: 10000});
    await expect(page.locator('.ant-table')).toBeVisible();
  });
});
