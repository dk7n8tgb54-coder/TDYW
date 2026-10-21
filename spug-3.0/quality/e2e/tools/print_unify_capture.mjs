/**
 * 统一打印布局网页截图（2026-10-21）。
 *
 * 用法（quality/e2e 目录下，依赖已安装的 playwright chromium）：
 *   node tools/print_unify_capture.mjs
 *
 * 走真实 UI 链路：登录页真实登录 → 周月维护台账列表深链
 * （?detail=<ID>&source=excel 直达 Excel 详情）→ 截「填写」两种显示
 * 模式与「打印预览」页签。
 */
import {chromium, request} from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const BASE_URL = process.env.E2E_BASE_URL || 'http://localhost:8080';
const USERNAME = process.env.E2E_ADMIN_USERNAME || 'admin';
const PASSWORD = process.env.E2E_ADMIN_PASSWORD || 'Admin888..';
const OUT = path.resolve(path.dirname(fileURLToPath(import.meta.url)),
  '../../reports/excel_print_unify_20261021');

const CASES = [
  {case: 'wide-landscape', template: '统一打印-wide-landscape'},
  {case: 'long-portrait', template: '统一打印-long-portrait'},
];

async function loginToken() {
  const ctx = await request.newContext({baseURL: BASE_URL});
  const response = await ctx.post('/api/account/login/', {
    data: {username: USERNAME, password: PASSWORD, type: 'default'},
  });
  const body = await response.json();
  if (body.error) throw new Error('登录失败: ' + body.error);
  await ctx.dispose();
  return body.data.access_token;
}

async function findLedger(token, templateName) {
  const ctx = await request.newContext({
    baseURL: BASE_URL,
    extraHTTPHeaders: {'X-Token': token, 'Content-Type': 'application/json'},
  });
  // 逐页找模板名匹配的最新 Excel 台账
  for (let page = 1; page <= 10; page++) {
    const response = await ctx.get(
      `/api/equipment-lifecycle/excel-ledgers/?page=${page}&page_size=50`);
    const body = await response.json();
    const payload = body.data && body.data.data ? body.data : body;
    for (const item of payload.data || []) {
      if ((item.excel && item.excel.template_name) === templateName) {
        await ctx.dispose();
        return item;
      }
    }
    if (!payload.total || (payload.data || []).length < 50) break;
  }
  await ctx.dispose();
  return null;
}

const browser = await chromium.launch();
const page = await browser.newPage({viewport: {width: 1440, height: 900}});
// 真实 UI 登录（sessionStorage 只注入 token 缺 permissions 上下文，路由 404）
await page.goto(BASE_URL + '/', {waitUntil: 'networkidle'});
await page.locator('input[placeholder="请输入账户"]').fill(USERNAME);
await page.locator('input[placeholder="请输入密码"]').fill(PASSWORD);
await page.getByRole('button', {name: /登\s*录/}).click();
await page.waitForURL('**/home**', {timeout: 20000});

// 同一会话内复用 UI 登录的 token（再次 API 登录会顶掉前一个 token）
const token = await page.evaluate(() => sessionStorage.getItem('token'));
for (const item of CASES) {
  const ledger = await findLedger(token, item.template);
  if (!ledger) {
    console.error('未找到台账：', item.template);
    continue;
  }
  console.log('打开台账', ledger.ledger_no, ledger.id);
  await page.goto(`${BASE_URL}/el/week-month-ledgers?detail=${ledger.id}&source=excel`);
  await page.waitForSelector('[data-testid="fill-workspace"]', {timeout: 30000});
  await page.waitForTimeout(1500);
  await page.screenshot({
    path: path.join(OUT, `${item.case}-web-fill-fitwidth.png`), fullPage: false});
  await page.waitForTimeout(1000);
  await page.click('[data-testid="fill-display-mode"] .ant-radio-button-wrapper:has-text("原始")');
  await page.waitForTimeout(800);
  await page.screenshot({
    path: path.join(OUT, `${item.case}-web-fill-original.png`), fullPage: false});
  // 打印预览页签（antd 两字按钮会插空格，统一用组内文本定位）
  await page.click('[data-testid="ledger-view-mode"] .ant-radio-button-wrapper:has-text("打印预览")');
  await page.waitForTimeout(400);
  await page.click('[data-testid="preview-refresh"]');
  await page.waitForSelector('[data-testid="preview-iframe"]', {timeout: 60000});
  await page.waitForTimeout(5000);
  await page.screenshot({
    path: path.join(OUT, `${item.case}-web-preview.png`), fullPage: false});
}

await browser.close();
console.log('截图完成 →', OUT);
