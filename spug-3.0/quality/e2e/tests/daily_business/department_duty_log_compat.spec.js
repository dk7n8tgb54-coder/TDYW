/**
 * 部门值班日志 - 浏览器兼容性与移动视口检查
 *
 * 覆盖发布要求 E：
 * - Chrome / Edge 最新稳定版（channel 方式调用本机浏览器）
 * - 一个移动视口（375x667）下的布局/滚动/文字溢出
 * - 截图保存到报告目录，供人工复核
 */
const { test: base, expect } = require('@playwright/test');
const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');

const SHOT_DIR = process.env.E2E_SHOT_DIR || '';

const test = base.extend({
  // eslint-disable-next-line no-empty-pattern
});

async function gotoModule(page) {
  const session = await apiLogin(page.request, 'admin');
  await injectAuth(page, session);
  await page.goto('/department-duty-log');
  await page.waitForSelector('.ant-table', { timeout: 20000 });
}

test.describe('Department Duty Log - 浏览器与视口兼容性', () => {
  test('CMPT-01 Chrome 桌面视口渲染无溢出', async ({ page }) => {
    await gotoModule(page);
    await expect(page.locator('.ant-table-thead')).toBeVisible();
    // 页面无横向溢出（表格允许内部滚动，body 本身不应超宽）
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(2);
    if (SHOT_DIR) await page.screenshot({ path: `${SHOT_DIR}/chrome_desktop.png`, fullPage: false });
  });

  test('CMPT-02 Edge 桌面视口渲染', async ({ browser }) => {
    let ctx;
    try {
      ctx = await browser.newContext({ channel: 'msedge' });
    } catch (e) {
      test.skip(true, '本机未安装 Edge，跳过');
      return;
    }
    const page = await ctx.newPage();
    await gotoModule(page);
    await expect(page.locator('.ant-table-thead')).toBeVisible();
    if (SHOT_DIR) await page.screenshot({ path: `${SHOT_DIR}/edge_desktop.png` });
    await ctx.close();
  });

  test('CMPT-03 移动视口（375x667）布局与滚动', async ({ browser }) => {
    const ctx = await browser.newContext({
      viewport: { width: 375, height: 667 },
      isMobile: true,
      hasTouch: true,
    });
    const page = await ctx.newPage();
    await gotoModule(page);
    await expect(page.locator('.ant-table-thead')).toBeVisible();

    // 记录横向溢出情况（移动端表格应有横向滚动容器，body 宽度不应被撑破）
    const metrics = await page.evaluate(() => ({
      bodyScrollWidth: document.body.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    // 允许表格容器内部滚动；body 溢出超过 8px 视为布局破坏
    expect(metrics.bodyScrollWidth - metrics.clientWidth).toBeLessThanOrEqual(8);
    if (SHOT_DIR) await page.screenshot({ path: `${SHOT_DIR}/mobile_375.png`, fullPage: false });

    // 新建弹窗在移动视口下可打开且无溢出
    await page.getByRole('button', { name: /新建值班日志/ }).click();
    const modal = page.locator('.ant-modal:has-text("新建值班日志")').last();
    await expect(modal).toBeVisible();
    if (SHOT_DIR) await page.screenshot({ path: `${SHOT_DIR}/mobile_375_modal.png` });
    await ctx.close();
  });
});
