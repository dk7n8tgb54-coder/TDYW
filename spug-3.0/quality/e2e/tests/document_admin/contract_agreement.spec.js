/**
 * Contract Agreement - CRUD tests
 * 上线前测试（quality/reports/contract_agreement/）真实浏览器 E2E 补充用例。
 *
 * 覆盖：列表渲染/筛选/重置、新建、编辑、详情与费用联动、删除二次确认、
 *       附件上传/下载/预览/删除、到期提醒弹窗与已处理、30秒幂等与错误提示次数、
 *       首页角标一致性、窄屏布局、列表接口网络失败降级。
 *
 * 约定：仅使用测试环境（E2E_BASE_URL，默认 tdyw-test 8080）与测试账号；
 *       测试数据统一使用 E2E_CA_ 前缀，beforeAll/afterAll 只清理该前缀数据。
 */
const { test, expect } = require('../../fixtures/auth.fixture');
const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
const { loginAndCreateContext, apiGet, apiPost } = require('../../helpers/api');

const LIST_API = '/api/contract-agreement/';
const RUN_PREFIX = `E2E_CA_${Date.now()}`;

function fmtDate(offsetDays) {
  return new Date(Date.now() + offsetDays * 86400000).toISOString().slice(0, 10);
}

function buildPayload(session, overrides = {}) {
  return Object.assign({
    contract_name: `${RUN_PREFIX}_合同`,
    contract_type: 'device_purchase',
    valid_start_date: fmtDate(-30),
    valid_end_date: fmtDate(300),
    signing_party: 'E2E测试签约方',
    responsible_user_id: session.data.id,
    responsible_user_name: 'admin',
    has_fee: false,
  }, overrides);
}

async function createViaApi(overrides = {}) {
  const session = await loginAndCreateContext('admin');
  const body = await apiPost(session.context, LIST_API, buildPayload(session, overrides));
  await session.context.dispose();
  if (body.error) throw new Error(`API 创建合同失败: ${body.error}`);
  return body.data;
}

async function fetchDetail(id) {
  const session = await loginAndCreateContext('admin');
  const body = await apiGet(session.context, `${LIST_API}${id}/`);
  await session.context.dispose();
  return body;
}

async function cleanupByPrefix() {
  const session = await loginAndCreateContext('admin');
  try {
    const body = await apiGet(session.context, `${LIST_API}?page_size=100&contract_name=E2E_CA_`);
    const records = (body.data && body.data.records) || [];
    for (const r of records) {
      try {
        await session.context.delete(`${LIST_API}?id=${r.id}`);
      } catch (e) {
        console.log(`Cleanup: 删除合同 ${r.id} 失败: ${e.message}`);
      }
    }
  } finally {
    await session.context.dispose();
  }
}

async function uiLogin(page, request) {
  const session = await apiLogin(request, 'admin');
  await injectAuth(page, session);
  return session;
}

async function fillContractForm(page, modal, name) {
  await modal.getByLabel('合同名称').fill(name);
  await modal.getByLabel('合同编号').fill(`E2E-HT-${Date.now()}`);
  await modal.getByLabel('类型').click();
  await page.locator('.ant-select-item-option[title="设备采购合同"]').click();
  await modal.getByLabel('起始日期').click();
  await modal.getByLabel('起始日期').fill(fmtDate(-30));
  await page.keyboard.press('Enter');
  await modal.getByLabel('截止日期').click();
  await modal.getByLabel('截止日期').fill(fmtDate(300));
  await page.keyboard.press('Enter');
  await modal.getByLabel('责任人').click();
  await modal.getByLabel('责任人').fill('admin');
  const option = page.locator('.ant-select-item-option').filter({ hasText: 'admin' }).first();
  await expect(option).toBeVisible({ timeout: 10000 });
  await option.click();
  await modal.locator('.ant-radio-wrapper').filter({ hasText: '无' }).click();
  await modal.getByLabel('签约方').fill('E2E测试签约方');
}

test.describe('Contract Agreement - Document Admin', () => {
  test.beforeAll(async () => {
    await cleanupByPrefix();
  });

  test.afterAll(async () => {
    await cleanupByPrefix();
  });

  test('CA001 - Contract agreement list page loads', async ({ page, request }) => {
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

  test('CA005 - 列表渲染与名称筛选/重置', async ({ page, request }) => {
    // 注意：API 登录会刷新 admin 的 access_token，必须先做数据准备，再 uiLogin，
    // 否则页面会话在 goto 前已被作废、被重定向到登录页。
    const n1 = `${RUN_PREFIX}_筛选A`;
    const n2 = `${RUN_PREFIX}_筛选B`;
    await createViaApi({ contract_name: n1 });
    await createViaApi({ contract_name: n2 });
    await uiLogin(page, request);
    await page.goto('/contract-agreement');
    const rowA = page.locator('.ant-table-tbody tr').filter({ hasText: n1 });
    const rowB = page.locator('.ant-table-tbody tr').filter({ hasText: n2 });
    await expect(rowA).toBeVisible({ timeout: 20000 });
    await expect(rowB).toBeVisible();

    const search = page.getByPlaceholder('请输入合同名称');
    await search.fill(n1);
    await search.press('Enter');
    await expect(rowB).toHaveCount(0, { timeout: 15000 });
    await expect(rowA).toBeVisible();

    // antd 两字按钮会自动插入空格（“重 置”），用正则兼容
    await page.getByRole('button', { name: /重\s*置/ }).click();
    await expect(rowA).toBeVisible({ timeout: 15000 });
    await expect(rowB).toBeVisible();
  });

  test('CA006 - 新建合同（完整表单流程，服务端回填责任人姓名）', async ({ page, request }) => {
    const session = await uiLogin(page, request);
    const name = `${RUN_PREFIX}_UI新建`;
    await page.goto('/contract-agreement');
    await page.getByRole('button', { name: '新建' }).click();
    const modal = page.locator('.ant-modal').filter({ hasText: '新建合同协议' });
    await expect(modal).toBeVisible();
    await fillContractForm(page, modal, name);
    await page.locator('.ant-modal-footer .ant-btn-primary').click();

    await expect(page.locator('.ant-message-notice').filter({ hasText: '操作成功' }))
      .toBeVisible({ timeout: 20000 });
    await expect(modal).toHaveCount(0, { timeout: 10000 });
    await expect(page.locator('.ant-table-tbody tr').filter({ hasText: name }))
      .toBeVisible({ timeout: 15000 });

    // 验证落库与责任人姓名服务端回填（非空即服务端填充，客户端仅传隐藏字段）
    const s = await loginAndCreateContext('admin');
    const listBody = await apiGet(s.context, `${LIST_API}?contract_name=${encodeURIComponent(name)}`);
    await s.context.dispose();
    const rec = (listBody.data && listBody.data.records || []).find(r => r.contract_name === name);
    expect(rec).toBeTruthy();
    expect(rec.responsible_user_name).toBeTruthy();
    expect(rec.created_by_name).toBe(session.nickname || 'admin');
  });

  test('CA007 - 编辑合同（修改备注并验证落库）', async ({ page, request }) => {
    const name = `${RUN_PREFIX}_UI编辑`;
    const created = await createViaApi({ contract_name: name, remark: 'E2E编辑前备注' });
    await uiLogin(page, request);
    await page.goto('/contract-agreement');
    const row = page.locator('.ant-table-tbody tr').filter({ hasText: name });
    await expect(row).toBeVisible({ timeout: 20000 });
    await row.getByRole('button', { name: '编辑' }).click();
    const modal = page.locator('.ant-modal').filter({ hasText: '编辑合同协议' });
    await expect(modal).toBeVisible();
    await modal.getByLabel('备注').fill('E2E编辑后备注');
    await page.locator('.ant-modal-footer .ant-btn-primary').click();
    await expect(page.locator('.ant-message-notice').filter({ hasText: '操作成功' }))
      .toBeVisible({ timeout: 20000 });

    const detail = await fetchDetail(created.id);
    expect(detail.error).toBeFalsy();
    expect(detail.data.remark).toBe('E2E编辑后备注');
  });

  test('CA008 - 详情展示与费用字段联动', async ({ page, request }) => {
    const name = `${RUN_PREFIX}_费用详情`;
    await createViaApi({
      contract_name: name, has_fee: true,
      fee_amount: '8888.66', fee_detail: 'E2E分两期支付',
    });
    await uiLogin(page, request);
    await page.goto('/contract-agreement');
    const row = page.locator('.ant-table-tbody tr').filter({ hasText: name });
    await expect(row).toBeVisible({ timeout: 20000 });
    await row.getByRole('button', { name: '查看' }).click();
    const detail = page.locator('.ant-modal').filter({ hasText: '合同协议详情' });
    await expect(detail).toBeVisible();
    await expect(detail).toContainText('人民币 8888.66');
    await expect(detail).toContainText('E2E分两期支付');

    // 编辑表单费用开关联动（详情页脚部的“编 辑”为 antd 两字按钮，自动带空格）
    await detail.getByRole('button', { name: /编\s*辑/ }).click();
    const form = page.locator('.ant-modal').filter({ hasText: '编辑合同协议' });
    await expect(form).toBeVisible();
    await expect(form.getByLabel('费用金额')).toBeVisible();
    await form.locator('.ant-radio-wrapper').filter({ hasText: '无' }).click();
    await expect(form.getByLabel('费用金额')).toBeHidden();
    await form.locator('.ant-radio-wrapper').filter({ hasText: '有' }).click();
    await expect(form.getByLabel('费用金额')).toBeVisible();
    await form.locator('.ant-modal-footer button:not(.ant-btn-primary)').first().click();
  });

  test('CA009 - 删除合同（二次确认、列表移除、详情不可达）', async ({ page, request }) => {
    const name = `${RUN_PREFIX}_UI删除`;
    const created = await createViaApi({ contract_name: name });
    await uiLogin(page, request);
    await page.goto('/contract-agreement');
    const row = page.locator('.ant-table-tbody tr').filter({ hasText: name });
    await expect(row).toBeVisible({ timeout: 20000 });
    await row.getByRole('button', { name: '删除' }).click();
    const confirm = page.locator('.ant-modal-confirm');
    await expect(confirm).toContainText('删除确认');
    await expect(confirm).toContainText(name);
    await confirm.locator('.ant-btn-primary').click();
    await expect(page.locator('.ant-message-notice').filter({ hasText: '删除成功' }))
      .toBeVisible({ timeout: 15000 });
    await expect(row).toHaveCount(0, { timeout: 15000 });

    const detail = await fetchDetail(created.id);
    expect(detail.error).toBeTruthy();
  });

  test('CA010 - 附件上传/列表/下载/删除（真实文件）', async ({ page, request }) => {
    const name = `${RUN_PREFIX}_附件`;
    const created = await createViaApi({ contract_name: name });
    await uiLogin(page, request);
    await page.goto(`/contract-agreement?id=${created.id}`);
    const detail = page.locator('.ant-modal').filter({ hasText: '合同协议详情' });
    await expect(detail).toBeVisible({ timeout: 20000 });

    const fileName = `E2E附件_${Date.now()}.pdf`;
    await detail.locator('input[type="file"]').setInputFiles({
      name: fileName,
      mimeType: 'application/pdf',
      buffer: Buffer.from('%PDF-1.4 E2E attachment content'),
    });
    const attRow = detail.locator('.ant-table-tbody tr').filter({ hasText: fileName });
    await expect(attRow).toBeVisible({ timeout: 30000 });

    // 下载（真实文件流）
    const dlPromise = page.waitForEvent('download', { timeout: 15000 });
    await attRow.getByRole('button', { name: '下载' }).click();
    const dl = await dlPromise;
    expect(dl.suggestedFilename()).toContain('.pdf');

    // 删除（Popconfirm 二次确认）
    await attRow.getByRole('button', { name: '删除' }).click();
    await page.locator('.ant-popover .ant-btn-primary').click();
    await expect(attRow).toHaveCount(0, { timeout: 15000 });
  });

  test('CA011 - 附件在线预览（PDF 内联预览弹窗）', async ({ page, request }) => {
    const name = `${RUN_PREFIX}_预览`;
    const created = await createViaApi({ contract_name: name });
    await uiLogin(page, request);
    await page.goto(`/contract-agreement?id=${created.id}`);
    const detail = page.locator('.ant-modal').filter({ hasText: '合同协议详情' });
    await expect(detail).toBeVisible({ timeout: 20000 });

    const fileName = `E2E预览_${Date.now()}.pdf`;
    await detail.locator('input[type="file"]').setInputFiles({
      name: fileName,
      mimeType: 'application/pdf',
      buffer: Buffer.from('%PDF-1.4 E2E preview content'),
    });
    const attRow = detail.locator('.ant-table-tbody tr').filter({ hasText: fileName });
    await expect(attRow).toBeVisible({ timeout: 30000 });

    // 点击文件名按钮触发预览（操作列“预览”按钮与文件名按钮在 role 定位下撞名）
    await attRow.getByRole('button', { name: fileName, exact: true }).click();
    // PDF 未配置 previewRequest 时走下载接口 inline 模式，预览弹窗内为 iframe
    await expect(page.locator('.ant-modal iframe').last()).toBeVisible({ timeout: 15000 });
  });

  test('CA012 - 即将到期合同提醒弹窗与「已处理」确认', async ({ page, request }) => {
    const name = `${RUN_PREFIX}_即将到期`;
    await createViaApi({
      contract_name: name,
      valid_start_date: fmtDate(-15),
      valid_end_date: fmtDate(15),
    });
    await uiLogin(page, request);
    await page.goto('/home');
    const notif = page.locator('.ant-notification-notice').filter({ hasText: name });
    await expect(notif).toBeVisible({ timeout: 25000 });
    await expect(notif.locator('.ant-tag')).toHaveText('即将到期');

    await notif.getByRole('button', { name: '已处理' }).click();
    await expect(notif).toHaveCount(0, { timeout: 10000 });

    // 产品契约：确认处理后刷新页面不应再次弹出同一合同的提醒
    await page.reload();
    await page.waitForTimeout(8000);
    await expect(page.locator('.ant-notification-notice').filter({ hasText: name }))
      .toHaveCount(0, { timeout: 10000 });
  });

  test('CA013 - 30秒内重复提交相同合同被拒绝且错误只提示一次', async ({ page, request }) => {
    await uiLogin(page, request);
    const name = `${RUN_PREFIX}_重复提交`;
    await page.goto('/contract-agreement');

    // 第一次提交
    await page.getByRole('button', { name: '新建' }).click();
    let modal = page.locator('.ant-modal').filter({ hasText: '新建合同协议' });
    await expect(modal).toBeVisible();
    await fillContractForm(page, modal, name);
    await page.locator('.ant-modal-footer .ant-btn-primary').click();
    await expect(page.locator('.ant-message-notice').filter({ hasText: '操作成功' }))
      .toBeVisible({ timeout: 20000 });
    await expect(modal).toHaveCount(0, { timeout: 10000 });

    // 第二次提交同名合同（30 秒窗口内）
    await page.getByRole('button', { name: '新建' }).click();
    modal = page.locator('.ant-modal').filter({ hasText: '新建合同协议' });
    await expect(modal).toBeVisible();
    await fillContractForm(page, modal, name);
    await page.locator('.ant-modal-footer .ant-btn-primary').click();
    await expect(page.locator('.ant-message-notice').filter({ hasText: '操作过于频繁' }))
      .toBeVisible({ timeout: 20000 });

    // 同一个错误只允许提示一次（AGENTS.md 九.3）
    await page.waitForTimeout(1500);
    expect(await page.locator('.ant-message-notice').filter({ hasText: '操作过于频繁' }).count()).toBe(1);
    expect(await page.locator('.ant-message-notice').filter({ hasText: '操作失败，请稍后重试' }).count()).toBe(0);

    // HTTP 200 + error 必须视为失败：弹窗保持打开、无成功提示
    await expect(modal).toBeVisible();
    await expect(page.locator('.ant-message-notice').filter({ hasText: '操作成功' })).toHaveCount(0);
    await modal.locator('.ant-modal-footer button:not(.ant-btn-primary)').first().click();
  });

  test('CA014 - 首页到期提醒角标与 badge 接口一致', async ({ page, request }) => {
    await createViaApi({
      contract_name: `${RUN_PREFIX}_角标`,
      valid_start_date: fmtDate(-10),
      valid_end_date: fmtDate(30),
    });
    // 先取 badge 基准再 uiLogin：API 登录会刷新 admin token，页面加载后不得再轮换
    const s = await loginAndCreateContext('admin');
    const badge = await apiGet(s.context, '/api/contract-agreement/badge/');
    await s.context.dispose();
    expect(badge.error).toBeFalsy();

    await uiLogin(page, request);
    await page.goto('/home');
    const card = page.locator('.ant-card').filter({ hasText: '到期提醒' });
    await expect(card).toContainText('合同协议', { timeout: 20000 });
    await expect(card).toContainText(`${badge.data.expiring_count} 项`, { timeout: 10000 });
  });

  test('CA015 - 窄屏(375x667)布局不产生页面级横向溢出', async ({ page, request }) => {
    await uiLogin(page, request);
    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto('/contract-agreement');
    await expect(page.locator('.ant-table')).toBeVisible({ timeout: 20000 });
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(2);
  });

  test('CA016 - 列表接口网络失败时页面不崩溃', async ({ page, request }) => {
    await uiLogin(page, request);
    await page.route('**/api/contract-agreement/**', (route) => route.abort());
    await page.goto('/contract-agreement');
    await page.waitForTimeout(3000);
    await expect(page.locator('.ant-table')).toBeVisible();
    const bodyText = await page.locator('body').innerText();
    expect(bodyText.length).toBeGreaterThan(0);
    expect(await page.locator('.ant-table-tbody tr.ant-table-row').count()).toBe(0);
  });
});
