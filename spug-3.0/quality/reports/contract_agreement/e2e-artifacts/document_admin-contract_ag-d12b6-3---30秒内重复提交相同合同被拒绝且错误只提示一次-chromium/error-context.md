# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: document_admin\contract_agreement.spec.js >> Contract Agreement - Document Admin >> CA013 - 30秒内重复提交相同合同被拒绝且错误只提示一次
- Location: tests\document_admin\contract_agreement.spec.js:331:3

# Error details

```
Error: expect(received).toBe(expected) // Object.is equality

Expected: 0
Received: 1
```

# Test source

```ts
  258 |     const created = await createViaApi({ contract_name: name });
  259 |     await uiLogin(page, request);
  260 |     await page.goto(`/contract-agreement?id=${created.id}`);
  261 |     const detail = page.locator('.ant-modal').filter({ hasText: '合同协议详情' });
  262 |     await expect(detail).toBeVisible({ timeout: 20000 });
  263 | 
  264 |     const fileName = `E2E附件_${Date.now()}.pdf`;
  265 |     await detail.locator('input[type="file"]').setInputFiles({
  266 |       name: fileName,
  267 |       mimeType: 'application/pdf',
  268 |       buffer: Buffer.from('%PDF-1.4 E2E attachment content'),
  269 |     });
  270 |     const attRow = detail.locator('.ant-table-tbody tr').filter({ hasText: fileName });
  271 |     await expect(attRow).toBeVisible({ timeout: 30000 });
  272 | 
  273 |     // 下载（真实文件流）
  274 |     const dlPromise = page.waitForEvent('download', { timeout: 15000 });
  275 |     await attRow.getByRole('button', { name: '下载' }).click();
  276 |     const dl = await dlPromise;
  277 |     expect(dl.suggestedFilename()).toContain('.pdf');
  278 | 
  279 |     // 删除（Popconfirm 二次确认）
  280 |     await attRow.getByRole('button', { name: '删除' }).click();
  281 |     await page.locator('.ant-popover .ant-btn-primary').click();
  282 |     await expect(attRow).toHaveCount(0, { timeout: 15000 });
  283 |   });
  284 | 
  285 |   test('CA011 - 附件在线预览（PDF 内联预览弹窗）', async ({ page, request }) => {
  286 |     const name = `${RUN_PREFIX}_预览`;
  287 |     const created = await createViaApi({ contract_name: name });
  288 |     await uiLogin(page, request);
  289 |     await page.goto(`/contract-agreement?id=${created.id}`);
  290 |     const detail = page.locator('.ant-modal').filter({ hasText: '合同协议详情' });
  291 |     await expect(detail).toBeVisible({ timeout: 20000 });
  292 | 
  293 |     const fileName = `E2E预览_${Date.now()}.pdf`;
  294 |     await detail.locator('input[type="file"]').setInputFiles({
  295 |       name: fileName,
  296 |       mimeType: 'application/pdf',
  297 |       buffer: Buffer.from('%PDF-1.4 E2E preview content'),
  298 |     });
  299 |     const attRow = detail.locator('.ant-table-tbody tr').filter({ hasText: fileName });
  300 |     await expect(attRow).toBeVisible({ timeout: 30000 });
  301 | 
  302 |     // 点击文件名按钮触发预览（操作列“预览”按钮与文件名按钮在 role 定位下撞名）
  303 |     await attRow.getByRole('button', { name: fileName, exact: true }).click();
  304 |     // PDF 未配置 previewRequest 时走下载接口 inline 模式，预览弹窗内为 iframe
  305 |     await expect(page.locator('.ant-modal iframe').last()).toBeVisible({ timeout: 15000 });
  306 |   });
  307 | 
  308 |   test('CA012 - 即将到期合同提醒弹窗与「已处理」确认', async ({ page, request }) => {
  309 |     const name = `${RUN_PREFIX}_即将到期`;
  310 |     await createViaApi({
  311 |       contract_name: name,
  312 |       valid_start_date: fmtDate(-15),
  313 |       valid_end_date: fmtDate(15),
  314 |     });
  315 |     await uiLogin(page, request);
  316 |     await page.goto('/home');
  317 |     const notif = page.locator('.ant-notification-notice').filter({ hasText: name });
  318 |     await expect(notif).toBeVisible({ timeout: 25000 });
  319 |     await expect(notif.locator('.ant-tag')).toHaveText('即将到期');
  320 | 
  321 |     await notif.getByRole('button', { name: '已处理' }).click();
  322 |     await expect(notif).toHaveCount(0, { timeout: 10000 });
  323 | 
  324 |     // 产品契约：确认处理后刷新页面不应再次弹出同一合同的提醒
  325 |     await page.reload();
  326 |     await page.waitForTimeout(8000);
  327 |     await expect(page.locator('.ant-notification-notice').filter({ hasText: name }))
  328 |       .toHaveCount(0, { timeout: 10000 });
  329 |   });
  330 | 
  331 |   test('CA013 - 30秒内重复提交相同合同被拒绝且错误只提示一次', async ({ page, request }) => {
  332 |     await uiLogin(page, request);
  333 |     const name = `${RUN_PREFIX}_重复提交`;
  334 |     await page.goto('/contract-agreement');
  335 | 
  336 |     // 第一次提交
  337 |     await page.getByRole('button', { name: '新建' }).click();
  338 |     let modal = page.locator('.ant-modal').filter({ hasText: '新建合同协议' });
  339 |     await expect(modal).toBeVisible();
  340 |     await fillContractForm(page, modal, name);
  341 |     await page.locator('.ant-modal-footer .ant-btn-primary').click();
  342 |     await expect(page.locator('.ant-message-notice').filter({ hasText: '操作成功' }))
  343 |       .toBeVisible({ timeout: 20000 });
  344 |     await expect(modal).toHaveCount(0, { timeout: 10000 });
  345 | 
  346 |     // 第二次提交同名合同（30 秒窗口内）
  347 |     await page.getByRole('button', { name: '新建' }).click();
  348 |     modal = page.locator('.ant-modal').filter({ hasText: '新建合同协议' });
  349 |     await expect(modal).toBeVisible();
  350 |     await fillContractForm(page, modal, name);
  351 |     await page.locator('.ant-modal-footer .ant-btn-primary').click();
  352 |     await expect(page.locator('.ant-message-notice').filter({ hasText: '操作过于频繁' }))
  353 |       .toBeVisible({ timeout: 20000 });
  354 | 
  355 |     // 同一个错误只允许提示一次（AGENTS.md 九.3）
  356 |     await page.waitForTimeout(1500);
  357 |     expect(await page.locator('.ant-message-notice').filter({ hasText: '操作过于频繁' }).count()).toBe(1);
> 358 |     expect(await page.locator('.ant-message-notice').filter({ hasText: '操作失败，请稍后重试' }).count()).toBe(0);
      |                                                                                                 ^ Error: expect(received).toBe(expected) // Object.is equality
  359 | 
  360 |     // HTTP 200 + error 必须视为失败：弹窗保持打开、无成功提示
  361 |     await expect(modal).toBeVisible();
  362 |     await expect(page.locator('.ant-message-notice').filter({ hasText: '操作成功' })).toHaveCount(0);
  363 |     await modal.locator('.ant-modal-footer button:not(.ant-btn-primary)').first().click();
  364 |   });
  365 | 
  366 |   test('CA014 - 首页到期提醒角标与 badge 接口一致', async ({ page, request }) => {
  367 |     await createViaApi({
  368 |       contract_name: `${RUN_PREFIX}_角标`,
  369 |       valid_start_date: fmtDate(-10),
  370 |       valid_end_date: fmtDate(30),
  371 |     });
  372 |     // 先取 badge 基准再 uiLogin：API 登录会刷新 admin token，页面加载后不得再轮换
  373 |     const s = await loginAndCreateContext('admin');
  374 |     const badge = await apiGet(s.context, '/api/contract-agreement/badge/');
  375 |     await s.context.dispose();
  376 |     expect(badge.error).toBeFalsy();
  377 | 
  378 |     await uiLogin(page, request);
  379 |     await page.goto('/home');
  380 |     const card = page.locator('.ant-card').filter({ hasText: '到期提醒' });
  381 |     await expect(card).toContainText('合同协议', { timeout: 20000 });
  382 |     await expect(card).toContainText(`${badge.data.expiring_count} 项`, { timeout: 10000 });
  383 |   });
  384 | 
  385 |   test('CA015 - 窄屏(375x667)布局不产生页面级横向溢出', async ({ page, request }) => {
  386 |     await uiLogin(page, request);
  387 |     await page.setViewportSize({ width: 375, height: 667 });
  388 |     await page.goto('/contract-agreement');
  389 |     await expect(page.locator('.ant-table')).toBeVisible({ timeout: 20000 });
  390 |     const overflow = await page.evaluate(
  391 |       () => document.documentElement.scrollWidth - window.innerWidth);
  392 |     expect(overflow).toBeLessThanOrEqual(2);
  393 |   });
  394 | 
  395 |   test('CA016 - 列表接口网络失败时页面不崩溃', async ({ page, request }) => {
  396 |     await uiLogin(page, request);
  397 |     await page.route('**/api/contract-agreement/**', (route) => route.abort());
  398 |     await page.goto('/contract-agreement');
  399 |     await page.waitForTimeout(3000);
  400 |     await expect(page.locator('.ant-table')).toBeVisible();
  401 |     const bodyText = await page.locator('body').innerText();
  402 |     expect(bodyText.length).toBeGreaterThan(0);
  403 |     expect(await page.locator('.ant-table-tbody tr.ant-table-row').count()).toBe(0);
  404 |   });
  405 | });
  406 | 
```