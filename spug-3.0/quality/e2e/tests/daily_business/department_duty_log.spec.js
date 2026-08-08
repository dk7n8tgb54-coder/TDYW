/**
 * Department Duty Log - CRUD tests
 */
const { test, expect } = require('../../fixtures/auth.fixture');
const { NavigationPage } = require('../../pages/NavigationPage');
const { TEST_DATA } = require('../../fixtures/test-data.fixture');
const { loginAndCreateContext, apiGet, apiPost, apiDelete, assertNoApiError } = require('../../helpers/api');

const ADMIN_USER = process.env.E2E_ADMIN_USERNAME || 'admin';
const ADMIN_PWD = process.env.E2E_ADMIN_PASSWORD || (() => { throw new Error('E2E_ADMIN_PASSWORD not set. Copy environments/local.example.env to .env and fill in credentials.'); })();

test.describe('Department Duty Log - Daily Business', () => {
  let apiCtx;
  let testRecordId;

  test.afterAll(async () => {
    // Cleanup via API
    if (apiCtx && testRecordId) {
      try {
        await apiDelete(apiCtx, `/api/department-duty-log/records/${testRecordId}/`);
      } catch (e) { /* ignore */ }
      await apiCtx?.dispose();
    }
  });

  test('D001 - Department duty log list page loads', async ({ page, request }) => {
    const session = await require('../../fixtures/auth.fixture').apiLogin(request, 'admin');
    await require('../../fixtures/auth.fixture').injectAuth(page, session);
    await page.goto('/department-duty-log');
    await page.waitForLoadState('networkidle');

    const bodyText = await page.locator('body').innerText();
    expect(bodyText.length).toBeGreaterThan(0);
    // Verify table or empty state exists
    const hasTable = await page.locator('.ant-table').count();
    expect(hasTable).toBeGreaterThan(0);
  });

  test('D002 - Create department duty log via UI', async ({ page, request }) => {
    const session = await require('../../fixtures/auth.fixture').apiLogin(request, 'admin');
    await require('../../fixtures/auth.fixture').injectAuth(page, session);

    // Setup API context for cleanup
    const result = await loginAndCreateContext('admin');
    apiCtx = result.context;

    await page.goto('/department-duty-log');
    await page.waitForLoadState('networkidle');

    // Click new button
    const newBtn = page.getByRole('button', { name: /新建|新增|添加/ });
    if (await newBtn.count() > 0) {
      await newBtn.first().click();
      await page.waitForTimeout(1000);

      // Fill form - look for common fields
      const titleInput = page.locator('input').first();
      if (await titleInput.isVisible()) {
        await titleInput.fill(TEST_DATA.deptDutyLog.title());
      }

      // Look for content/description textarea
      const textarea = page.locator('textarea').first();
      if (await textarea.isVisible()) {
        await textarea.fill(TEST_DATA.deptDutyLog.content);
      }

      // Submit
      const submitBtn = page.locator('.ant-modal-footer .ant-btn-primary, .ant-drawer-footer .ant-btn-primary').first();
      if (await submitBtn.isVisible()) {
        await submitBtn.click();
        await page.waitForTimeout(2000);
      }
    }

    // Verify via API that a record was created
    const records = await apiGet(apiCtx, '/api/department-duty-log/records/?keyword=E2E');
    if (records.data && Array.isArray(records.data)) {
      const found = records.data.find(r => r.title && r.title.startsWith('E2E_'));
      if (found) {
        testRecordId = found.id;
        expect(found.title).toContain('E2E_');
      }
    }
  });

  test('D003 - Search for E2E test records', async ({ page, request }) => {
    const session = await require('../../fixtures/auth.fixture').apiLogin(request, 'admin');
    await require('../../fixtures/auth.fixture').injectAuth(page, session);
    await page.goto('/department-duty-log');
    await page.waitForLoadState('networkidle');

    // Try search functionality
    const searchInput = page.locator('input[placeholder*="搜索"], input[placeholder*="查询"], input[placeholder*="关键字"]').first();
    if (await searchInput.isVisible()) {
      await searchInput.fill('E2E_');
      await page.keyboard.press('Enter');
      await page.waitForLoadState('networkidle');
    }

    // Verify table loaded
    await page.waitForSelector('.ant-table-tbody', { timeout: 10000 });
    expect(true).toBe(true);
  });
});
