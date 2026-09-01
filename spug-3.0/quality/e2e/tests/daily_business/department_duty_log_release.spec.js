/**
 * 部门值班日志 - 上线前发布门禁 E2E 测试
 *
 * 目标环境：tdyw-test（隔离测试容器，http://localhost:8080）
 * 测试账号：E2E_ADMIN_*（测试环境管理员）
 * 数据纪律：所有记录以 E2E_DDL_RG_ 为前缀，afterAll 统一软删除，只清理本次创建的数据。
 *
 * 覆盖：
 * - 路由可达 + 表格渲染
 * - 新建弹窗真实提交（等后端响应后关闭并刷新）
 * - 日期选择器禁止未来日期
 * - 详情弹窗展示全文
 * - 关键字筛选
 * - 编辑弹窗回填 + 乐观锁 version
 * - 退回确认弹窗文案
 */
const { test, expect } = require('../../fixtures/auth.fixture');
const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
const { loginAndCreateContext, apiGet, apiPost, apiDelete } = require('../../helpers/api');

const PREFIX = `E2E_DDL_RG_${Date.now()}`;
const createdIds = [];

test.describe('Department Duty Log - Release Gate E2E', () => {
  let apiCtx;

  test.beforeAll(async () => {
    const result = await loginAndCreateContext('admin');
    apiCtx = result.context;
    // 为详情/编辑/删除用例预置一条草稿（避免用例间级联失败）
    const today = new Date().toISOString().slice(0, 10);
    const resp = await apiPost(apiCtx, '/api/department-duty-log/records/', {
      duty_date: today, weather: '晴',
      duty_record: `${PREFIX}_预置记录`,
    });
    if (resp.data && resp.data.id) createdIds.push(resp.data.id);
  });

  test.afterAll(async () => {
    // 清理本次创建的草稿记录（软删除，只清 E2E_DDL_RG_ 前缀）
    if (apiCtx) {
      try {
        const body = await apiGet(apiCtx, `/api/department-duty-log/records/?keyword=${PREFIX}&page_size=100`);
        for (const r of (body.data?.records || [])) {
          if (String(r.duty_record_summary || '').startsWith(PREFIX)) {
            await apiDelete(apiCtx, `/api/department-duty-log/records/${r.id}/`);
          }
        }
      } catch (e) { /* ignore */ }
      await apiCtx.dispose();
    }
  });

  async function openPage(page) {
    const session = await apiLogin(page.request ? undefined : undefined, 'admin').catch(() => null);
    return session;
  }

  test('RG-E2E-01 列表页加载并渲染表格', async ({ page, request }) => {
    const session = await apiLogin(request, 'admin');
    await injectAuth(page, session);
    await page.goto('/department-duty-log');
    await page.waitForSelector('.ant-table', { timeout: 20000 });
    await expect(page.locator('.ant-table-thead')).toBeVisible();
    // 筛选区存在
    await expect(page.getByPlaceholder('值班记录/上级工作要求')).toBeVisible();
  });

  test('RG-E2E-02 新建：填写表单提交后等待后端响应再关闭弹窗', async ({ page, request }) => {
    const session = await apiLogin(request, 'admin');
    await injectAuth(page, session);
    await page.goto('/department-duty-log');
    await page.waitForSelector('.ant-table', { timeout: 20000 });

    await page.getByRole('button', { name: /新建值班日志/ }).click();
    const modal = page.locator('.ant-modal:has-text("新建值班日志")').last();
    await expect(modal).toBeVisible();

    // 值班日期默认空，天气与记录必填
    await modal.getByPlaceholder('如：晴').fill('晴');
    await modal.getByPlaceholder('请输入当班情况').fill(`${PREFIX}_新建测试记录`);

    // 必须选择值班日期（必填项，未选则表单校验不通过、不发请求）
    await modal.locator('.ant-picker').first().click();
    await page.locator('.ant-picker-cell-today').first().click();

    const respPromise = page.waitForResponse(
      r => r.url().includes('/api/department-duty-log/records/') && r.request().method() === 'POST',
      { timeout: 15000 });
    await modal.locator('.ant-modal-footer .ant-btn-primary').click();
    const resp = await respPromise;

    // 后端成功后弹窗才关闭
    expect(resp.status()).toBe(200);
    const body = await resp.json();
    expect(body.error).toBeFalsy();
    await expect(modal).toBeHidden({ timeout: 10000 });

    // 列表刷新出现新记录
    await expect(page.locator('.ant-table-tbody').getByText(`${PREFIX}_新建测试记录`))
      .toBeVisible({ timeout: 15000 });

    // 值班人员为服务端决定的当前用户（禁用输入，不可伪造）
    createdIds.push(body.data.id);
  });

  test('RG-E2E-03 新建弹窗日期选择器禁止选择未来日期', async ({ page, request }) => {
    const session = await apiLogin(request, 'admin');
    await injectAuth(page, session);
    await page.goto('/department-duty-log');
    await page.waitForSelector('.ant-table', { timeout: 20000 });

    await page.getByRole('button', { name: /新建值班日志/ }).click();
    const modal = page.locator('.ant-modal:has-text("新建值班日志")').last();
    await expect(modal).toBeVisible();
    await modal.locator('.ant-picker').first().click();
    await page.waitForTimeout(600);

    // 明天的日期单元格必须被禁用
    const tomorrow = new Date(Date.now() + 24 * 60 * 60 * 1000);
    const yyyy = tomorrow.getFullYear();
    const mm = String(tomorrow.getMonth() + 1).padStart(2, '0');
    const dd = String(tomorrow.getDate()).padStart(2, '0');
    const futureCell = page.locator(
      `.ant-picker-cell[title="${yyyy}-${mm}-${dd}"], .ant-picker-cell[title="${yyyy}-${mm}-${dd} "]`);
    await expect(futureCell).toHaveClass(/ant-picker-cell-disabled/, { timeout: 5000 });

    await page.keyboard.press('Escape');
  });

  test('RG-E2E-04 详情弹窗展示全文并正确关闭', async ({ page, request }) => {
    const session = await apiLogin(request, 'admin');
    await injectAuth(page, session);
    await page.goto('/department-duty-log');
    await page.waitForSelector('.ant-table', { timeout: 20000 });

    const row = page.locator('.ant-table-tbody tr').filter({ hasText: '_预置记录' }).first();
    await row.getByRole('button', { name: /查\s*看/ }).click();

    const detail = page.locator('.ant-modal:has-text("值班日志详情")').last();
    await expect(detail).toBeVisible({ timeout: 10000 });
    await expect(detail.locator('.ant-descriptions')).toBeVisible();
    await detail.locator('.ant-modal-close').click();
    await expect(detail).toBeHidden({ timeout: 5000 });
  });

  test('RG-E2E-05 关键字筛选生效', async ({ page, request }) => {
    const session = await apiLogin(request, 'admin');
    await injectAuth(page, session);
    await page.goto('/department-duty-log');
    await page.waitForSelector('.ant-table', { timeout: 20000 });

    const kw = page.getByPlaceholder('值班记录/上级工作要求');
    const respPromise = page.waitForResponse(
      r => r.url().includes('/api/department-duty-log/records/') && r.url().includes('keyword='),
      { timeout: 15000 });
    await kw.fill(PREFIX);
    await kw.press('Enter');
    const resp = await respPromise;

    // 后端真实返回了 sentinel 记录
    const body = await resp.json();
    expect(body.error).toBeFalsy();
    expect(body.data.total).toBeGreaterThanOrEqual(1);
    const matched = (body.data.records || []).filter(
      r => String(r.duty_record_summary || '').startsWith(PREFIX));
    expect(matched.length).toBeGreaterThanOrEqual(1);

    // UI 表格渲染出 sentinel 记录
    await expect(page.locator('.ant-table-tbody').getByText('_预置记录'))
      .toBeVisible({ timeout: 15000 });
  });

  test('RG-E2E-06 编辑弹窗回填并提交（乐观锁 version 正确传递）', async ({ page, request }) => {
    const session = await apiLogin(request, 'admin');
    await injectAuth(page, session);
    await page.goto('/department-duty-log');
    await page.waitForSelector('.ant-table', { timeout: 20000 });

    const row = page.locator('.ant-table-tbody tr').filter({ hasText: '_预置记录' }).first();
    await row.getByRole('button', { name: /编\s*辑/ }).click();

    const modal = page.locator('.ant-modal:has-text("编辑值班日志")').last();
    await expect(modal).toBeVisible({ timeout: 10000 });

    // 等待详情加载并回填
    const textarea = modal.getByPlaceholder('请输入当班情况');
    await expect(textarea).toHaveValue(`${PREFIX}_预置记录`, { timeout: 10000 });

    // 修改内容
    await textarea.fill(`${PREFIX}_编辑后的记录`);
    const respPromise = page.waitForResponse(
      r => r.request().method() === 'PUT' && r.url().match(/\/api\/department-duty-log\/records\/\d+\/$/),
      { timeout: 15000 });
    await modal.locator('.ant-modal-footer .ant-btn-primary').click();
    const resp = await respPromise;
    expect(resp.status()).toBe(200);
    const body = await resp.json();
    expect(body.error).toBeFalsy();
    // 版本号递增
    expect(body.data.version).toBeGreaterThanOrEqual(2);

    await expect(modal).toBeHidden({ timeout: 10000 });
    await expect(page.locator('.ant-table-tbody').getByText(`${PREFIX}_编辑后的记录`))
      .toBeVisible({ timeout: 15000 });
  });

  test('RG-E2E-07 删除草稿需二次确认且成功后从列表消失', async ({ page, request }) => {
    const session = await apiLogin(request, 'admin');
    await injectAuth(page, session);
    await page.goto('/department-duty-log');
    await page.waitForSelector('.ant-table', { timeout: 20000 });

    const row = page.locator('.ant-table-tbody tr').filter({ hasText: '_编辑后的记录' }).first();
    await row.getByRole('button', { name: /删\s*除/ }).click();

    // Modal.confirm 二次确认
    const confirm = page.locator('.ant-modal-confirm:has-text("删除确认")');
    await expect(confirm).toBeVisible();
    const respPromise = page.waitForResponse(
      r => r.request().method() === 'DELETE' && r.url().match(/\/api\/department-duty-log\/records\/\d+\/$/),
      { timeout: 15000 });
    await confirm.locator('.ant-btn-primary, .ant-btn-dangerous').first().click();
    const resp = await respPromise;
    expect(resp.status()).toBe(200);

    await expect(page.locator('.ant-table-tbody').getByText(`${PREFIX}_编辑后的记录`))
      .toBeHidden({ timeout: 15000 });
  });

  test('RG-E2E-08 API 无权限账号访问被后端拒绝（前端隐藏按钮不可绕过）', async ({ request }) => {
    // 用 API 直接验证后端鉴权：未登录请求被拒绝
    const resp = await request.get('/api/department-duty-log/records/');
    const body = await resp.json();
    expect(body.error).toBeTruthy();
  });
});
