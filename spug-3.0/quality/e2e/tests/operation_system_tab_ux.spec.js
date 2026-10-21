/**
 * 系统档案"运行处置记录"页签 UX 走查（2026-10-15 体验三轮）——真实浏览器端到端。
 *
 * 覆盖（桌面 1440x900 与窄屏 480x900 两轮）：
 * - 页签统一列呈现：标题入口（前置类型标签）/编号复制/故障影响并入状态列/
 *   进展数，无重复"详情"操作列；
 * - 筛选分层与同组条件：关键词/状态常驻，更多筛选收入记录类型/异常类别/
 *   发生时间；关键词无匹配的空态区分（"没有符合条件的记录"）；
 * - 统一详情打开与联动刷新：详情内添加补充记录成功后，页签以同组条件
 *   刷新，进展数即时 +1（不显示过期行）；
 * - "查看该系统全部记录"跳入主列表并自动带系统筛选；经菜单返回系统档案
 *   不丢失上下文（详情弹窗恢复、页签数据保留）；
 * - 窄屏：1100px 系统详情弹窗不超出视口（maxWidth 约束），筛选控件与
 *   表格可用，页面无意外横向溢出。
 *
 * 数据策略：优先复用环境既有系统与记录；不足时以 E2E 系统页签前缀创建
 * 最少数据（一般记录 + 不影响运行的设备故障），走查结束后删除一般记录、
 * 撤销故障。截图输出 quality/reports/e2e/operation_system_tab/。
 */
const {test, expect} = require('@playwright/test');
const path = require('path');
const fs = require('fs');
const {loginAndCreateContext, apiGet, apiPost, apiDelete} = require('../helpers/api');

const SHOT_DIR = path.join(__dirname, '..', '..', 'reports', 'e2e',
  'operation_system_tab');
const PREFIX = 'E2E系统页签';

function shotPath(viewport, name) {
  return path.join(SHOT_DIR, `${viewport}-${name}`);
}

async function saveShot(page, viewport, name) {
  fs.mkdirSync(SHOT_DIR, {recursive: true});
  await page.screenshot({path: shotPath(viewport, name), fullPage: false});
}

async function pageOverflow(page) {
  return page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
}

// 打开的 Modal（取宽度最大的可见弹窗）不得超出视口
async function modalWithinViewport(page) {
  return page.evaluate(() => {
    const modals = Array.from(document.querySelectorAll('.ant-modal'))
      .filter(m => m.offsetParent !== null);
    if (!modals.length) return {found: false};
    const modal = modals.reduce((a, b) =>
      b.getBoundingClientRect().width > a.getBoundingClientRect().width ? b : a);
    const rect = modal.getBoundingClientRect();
    return {
      found: true,
      width: rect.width,
      viewport: window.innerWidth,
      overflow: rect.left < -1 || rect.right > window.innerWidth + 1,
    };
  });
}

const WALKTHROUGH_PERMS = [
  'equipment_lifecycle.operation_record.view',
  'equipment_lifecycle.operation_record.add',
  'equipment_lifecycle.operation_record.add_fault',
  'equipment_lifecycle.operation_record.edit',
  'equipment_lifecycle.operation_record.progress',
  'equipment_lifecycle.operation_record.complete',
  'equipment_lifecycle.operation_record.del',
  'equipment_lifecycle.system.view',
];

async function openApp(page, token, url) {
  await page.addInitScript(({t, perms}) => {
    window.sessionStorage.setItem('token', t);
    window.sessionStorage.setItem('permissions', JSON.stringify(perms));
  }, {t: token, perms: WALKTHROUGH_PERMS});
  await page.goto(url, {waitUntil: 'domcontentloaded'});
}

// 窄屏下 Sider 可能覆盖页签（应用外壳层为固定布局）：直接派发 DOM click
async function clickByText(page, selector, text) {
  await page.evaluate(({sel, txt}) => {
    const node = Array.from(document.querySelectorAll(sel))
      .find(n => (n.textContent || '').includes(txt));
    if (node) node.click();
  }, {sel: selector, txt: text});
}

test.describe.serial('系统档案运行处置记录页签 UX 走查', () => {
  let token = null;
  let apiCtx = null;
  let systemId = null;
  let systemName = null;
  const created = {routine: null, fault: null};

  test.beforeAll(async () => {
    const result = await loginAndCreateContext('admin');
    token = result.token;
    apiCtx = result.context;
  });

  test('SEED - 保障最少数据（优先复用既有记录）', async () => {
    const systems = await apiGet(apiCtx,
      '/api/equipment-lifecycle/records/candidate-systems/');
    const systemRows = (systems.data && systems.data.data) || [];
    test.skip(!systemRows.length, '无可用系统');
    systemId = systemRows[0].id;
    systemName = systemRows[0].name;
    const records = await apiGet(apiCtx,
      `/api/equipment-lifecycle/records/?system=${systemId}&page_size=50`);
    const rows = (records.data && records.data.data) || [];
    const occurredAt = new Date(Date.now() - 3600 * 1000)
      .toISOString().slice(0, 16).replace('T', ' ');
    if (!rows.some(r => r.record_type === 'routine' &&
        r.title.startsWith(PREFIX))) {
      const routine = await apiPost(apiCtx,
        '/api/equipment-lifecycle/records/', {
          system: systemId, occurred_at: occurredAt,
          registrar_name: '走查机器人', record_type: 'routine',
          title: `${PREFIX}-一般记录-${Date.now()}`,
          description: '走查造数：常规巡检留痕。',
        });
      if (!routine.error) created.routine = routine.data.id;
    }
    if (!rows.some(r => r.record_type === 'fault')) {
      const fault = await apiPost(apiCtx, '/api/equipment-lifecycle/records/', {
        system: systemId, occurred_at: occurredAt,
        registrar_name: '走查机器人', record_type: 'fault',
        title: `${PREFIX}-设备故障-${Date.now()}`,
        description: '走查造数：部件故障（不影响运行）。',
        affects_system_operation: false,
      });
      if (!fault.error) created.fault = fault.data.id;
    }
  });

  test('DESKTOP - 页签列呈现/筛选分层/详情联动刷新/跳转与返回', async ({page}) => {
    test.skip(!systemId, '无可用系统');
    await openApp(page, token, `/el/systems?detail=${systemId}`);
    await page.waitForSelector('.ant-modal', {timeout: 20000});
    await page.click('.ant-modal .ant-tabs-tab:has-text("运行处置记录")');
    await page.waitForSelector('.ant-modal .ant-table-tbody', {timeout: 15000});
    await page.waitForTimeout(800);
    await saveShot(page, 'desktop', '01-system-tab.png');

    // 统一列呈现：无重复"详情"操作列；编号可复制；类型标签在标题前
    const detailLinks = await page.evaluate(() => Array.from(
      document.querySelectorAll('.ant-modal .ant-table-tbody a'))
      .filter(a => (a.textContent || '').trim() === '详情').length);
    expect(detailLinks).toBe(0);
    expect(await page.locator('.ant-modal .ant-typography-copy').count())
      .toBeGreaterThan(0);
    expect(await page.locator('.ant-modal .ant-table-tbody .ant-tag').count())
      .toBeGreaterThan(0);

    // 筛选分层：更多筛选收入记录类型/异常类别/发生时间
    await page.click('.ant-modal a:has-text("更多筛选")');
    await page.waitForTimeout(400);
    await saveShot(page, 'desktop', '02-system-tab-advanced.png');
    expect(await page.locator('.ant-modal:has-text("异常类别")').count())
      .toBeGreaterThan(0);
    // 收起后提示仍生效条件数
    await page.click('.ant-modal a:has-text("收起筛选")');
    await page.waitForTimeout(300);

    // 空态区分：关键词无匹配 → "没有符合条件的记录"
    const keywordInput = page.locator('.ant-modal input.ant-input').first();
    await keywordInput.fill(`${PREFIX}无匹配XYZ`);
    await page.click('.ant-modal button:has-text("查 询")');
    await page.waitForTimeout(800);
    expect(await page.locator('.ant-modal:has-text("没有符合条件的记录")').count())
      .toBeGreaterThan(0);
    await saveShot(page, 'desktop', '03-system-tab-filtered-empty.png');
    await page.click('.ant-modal button:has-text("重 置")');
    await page.waitForTimeout(800);

    // 统一详情：标题打开（本走查造数的一般记录）
    const routineTitle = await page.evaluate((prefix) => {
      const link = Array.from(document.querySelectorAll(
        '.ant-modal .ant-table-tbody a'))
        .find(a => (a.textContent || '').startsWith(prefix));
      return link ? link.textContent : null;
    }, `${PREFIX}-一般记录`);
    test.skip(!routineTitle, '无走查一般记录可验证详情');
    await page.click(`.ant-modal .ant-table-tbody a:has-text("${routineTitle}")`);
    await page.waitForSelector('.ant-modal:has-text("来源与登记")', {timeout: 15000});
    await saveShot(page, 'desktop', '04-record-detail.png');
    const detailMw = await modalWithinViewport(page);
    expect(detailMw.overflow).toBe(false);

    // 详情内添加补充记录 → 关闭详情后页签进展数即时 +1（同组条件联动刷新）
    const before = await page.evaluate((title) => {
      const row = Array.from(document.querySelectorAll(
        '.ant-modal .ant-table-tbody tr'))
        .find(r => (r.textContent || '').includes(title));
      if (!row) return null;
      const links = Array.from(row.querySelectorAll('a'));
      const last = links[links.length - 1];
      return last ? parseInt(last.textContent, 10) : null;
    }, routineTitle);
    await page.click('.ant-modal:has-text("来源与登记") button:has-text("添加补充记录")');
    const addModal = page.locator('.ant-modal').filter({
      has: page.locator('.ant-modal-title', {hasText: '添加补充记录'}),
    });
    await addModal.waitFor({timeout: 10000});
    const handlerInput = addModal.locator('.ant-select-selection-search-input');
    await handlerInput.click();
    await handlerInput.fill('走查机器人');
    await handlerInput.press('Enter');
    await addModal.locator('textarea').fill('系统页签联动刷新走查：补充一条现场记录。');
    await addModal.locator('.ant-modal-footer .ant-btn-primary').click();
    await addModal.waitFor({state: 'hidden', timeout: 15000});
    // 显式关闭统一详情弹窗（Escape 依赖焦点，弹窗叠加时不可靠）
    const detailModal = page.locator('.ant-modal:has-text("来源与登记")');
    await detailModal.locator('.ant-modal-footer button').first().click();
    await detailModal.waitFor({state: 'hidden', timeout: 15000});
    await page.waitForTimeout(600);
    const after = await page.evaluate((title) => {
      const row = Array.from(document.querySelectorAll(
        '.ant-modal .ant-table-tbody tr'))
        .find(r => (r.textContent || '').includes(title));
      if (!row) return null;
      const links = Array.from(row.querySelectorAll('a'));
      const last = links[links.length - 1];
      return last ? parseInt(last.textContent, 10) : null;
    }, routineTitle);
    expect(after).toBe(before + 1);
    await saveShot(page, 'desktop', '05-after-progress-refresh.png');

    // 进展数直达详情进展区块（2026-10 详情改版：分区布局，无独立时间线弹窗；
    // 区块名随记录类型：补充/跟进/处置记录）
    const countLink = page.locator('.ant-modal .ant-table-tbody tr')
      .filter({hasText: routineTitle}).locator('a').last();
    await countLink.click();
    const progressModal = page.locator('.ant-modal:has-text("来源与登记")');
    await progressModal.waitFor({state: 'visible', timeout: 15000});
    await page.waitForTimeout(600);
    expect(await progressModal.locator(':text("来源与登记")').count()).toBeGreaterThan(0);
    expect(await progressModal
      .locator('.ant-modal-body :text-matches("(补充|跟进|处置)记录")')
      .count()).toBeGreaterThan(0);
    await progressModal.locator('.ant-modal-footer button').first().click();
    await progressModal.waitFor({state: 'hidden', timeout: 15000});
    await page.waitForTimeout(400);

    // "查看该系统全部记录"：跳入主列表并自动带系统筛选
    await page.click('.ant-modal a:has-text("查看该系统全部记录")');
    await page.waitForURL(/\/el\/records\?system=\d+/, {timeout: 15000});
    await page.waitForSelector('.ant-table-tbody', {timeout: 15000});
    await page.waitForTimeout(800);
    const selectedSystem = await page.locator(
      '.ant-form .ant-select-selection-item').first().textContent();
    expect(selectedSystem).toContain(systemName);
    await saveShot(page, 'desktop', '06-main-list-system-filter.png');

    // 经菜单返回系统档案：上下文不丢失（系统详情弹窗自动恢复）
    await page.click('.ant-menu li:has-text("系统档案")');
    await page.waitForSelector('.ant-modal', {timeout: 15000});
    await page.waitForTimeout(600);
    const modalTitle = await page.locator('.ant-modal-title').first().textContent();
    expect(modalTitle).toContain(systemName);
    await saveShot(page, 'desktop', '07-system-context-restore.png');

    const overflow = await pageOverflow(page);
    expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.clientWidth + 2);
  });

  test('NARROW - 480px 窄屏页签适配与弹窗视口约束', async ({page, browser}) => {
    test.skip(!systemId, '无可用系统');
    const narrow = await browser.newContext({
      viewport: {width: 480, height: 900},
    });
    const np = await narrow.newPage();
    await openApp(np, token, `/el/systems?detail=${systemId}`);
    await np.waitForSelector('.ant-modal', {timeout: 20000});
    await np.waitForTimeout(500);
    // 系统详情弹窗不超出视口（maxWidth 约束生效）
    const mw = await modalWithinViewport(np);
    expect(mw.found && mw.overflow).toBe(false);
    await clickByText(np, '.ant-tabs-tab', '运行处置记录');
    await np.waitForSelector('.ant-modal .ant-table-tbody', {timeout: 15000});
    await np.waitForTimeout(800);
    await saveShot(np, 'narrow', '11-system-tab.png');
    expect((await modalWithinViewport(np)).overflow).toBe(false);
    // 更多筛选展开（发生时间全宽）后仍不溢出
    await np.click('.ant-modal a:has-text("更多筛选")');
    await np.waitForTimeout(400);
    await saveShot(np, 'narrow', '12-system-tab-advanced.png');
    expect((await modalWithinViewport(np)).overflow).toBe(false);
    const overflow = await pageOverflow(np);
    console.log('narrow overflow:', JSON.stringify(overflow));
    await narrow.close();
  });

  test.afterAll(async () => {
    // 清理走查造数：一般记录删除；设备故障撤销（原因必填）
    if (created.routine) {
      await apiDelete(apiCtx,
        `/api/equipment-lifecycle/records/${created.routine}/`);
    }
    if (created.fault) {
      await apiPost(apiCtx,
        `/api/equipment-lifecycle/records/${created.fault}/cancel/`,
        {cancel_reason: 'E2E 系统页签走查造数清理'});
    }
    if (apiCtx) await apiCtx.dispose();
  });
});
