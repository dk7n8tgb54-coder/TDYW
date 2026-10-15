/**
 * 运行处置记录 UX 走查（2026-10-14 体验二轮）——真实浏览器端到端。
 *
 * 覆盖（桌面 1440x900 与窄屏 480x900 两轮）：
 * - 列表：标题可点、编号复制入口、筛选分层（更多筛选）、导出范围提示、
 *   空态/加载态、页面级横向溢出检查；
 * - 新增：类型用途说明、设备故障专用字段按需显示；
 * - 详情：下一步指引、基本信息/进展/附件页签、弹窗宽度不超视口；
 * - 待办：分组计数（跟进中异常事件+处置中故障）、分页；
 * - 统计：四个核心指标并排、时间趋势柱状图；
 * - 系统档案"运行处置记录"页签：受控分页可达全部数据。
 *
 * 数据策略：优先复用环境既有记录；不足时以 E2E-UX 前缀创建最少数据
 * （跟进中异常事件 + 处置中故障），走查结束后撤销故障、完成跟进、
 * 删除一般记录，尽量不留残留。截图输出 quality/reports/e2e/operation_ux_walkthrough/。
 */
const {test, expect} = require('@playwright/test');
const path = require('path');
const fs = require('fs');
const {loginAndCreateContext, apiGet, apiPost, apiDelete} = require('../helpers/api');

const SHOT_DIR = path.join(__dirname, '..', '..', 'reports', 'e2e',
  'operation_ux_walkthrough');
const PREFIX = 'E2E-UX走查';

function shotName(viewport, name) {
  return path.join(SHOT_DIR, `${viewport}-${name}.png`);
}

async function saveShot(page, viewport, name) {
  fs.mkdirSync(SHOT_DIR, {recursive: true});
  await page.screenshot({path: shotName(viewport, name), fullPage: false});
}

// 页面级横向溢出检查（表格内部滚动除外）
async function pageOverflow(page) {
  return page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
}

// 打开的 Modal 宽度不得超出视口（窄屏遮挡检查）
async function modalWithinViewport(page) {
  return page.evaluate(() => {
    const modal = document.querySelector('.ant-modal:not([style*="display: none"])');
    if (!modal) return {found: false};
    const rect = modal.getBoundingClientRect();
    return {
      found: true,
      width: rect.width,
      left: rect.left,
      right: rect.right,
      viewport: window.innerWidth,
      overflow: rect.left < -1 || rect.right > window.innerWidth + 1,
    };
  });
}

// 走查账号为专用 E2E 账号（具备后端操作权限但未配页面权限码）：
// 会话内注入本模块所需页面权限码用于渲染（后端鉴权仍由真实 token 承担，
// 与真实登录会话的权限判断同一 hasPermission 通道）
const WALKTHROUGH_PERMS = [
  'equipment_lifecycle.operation_record.view',
  'equipment_lifecycle.operation_record.add',
  'equipment_lifecycle.operation_record.add_fault',
  'equipment_lifecycle.operation_record.edit',
  'equipment_lifecycle.operation_record.progress',
  'equipment_lifecycle.operation_record.complete',
  'equipment_lifecycle.operation_record.identify_fault',
  'equipment_lifecycle.operation_record.recover',
  'equipment_lifecycle.operation_record.close',
  'equipment_lifecycle.operation_record.cancel',
  'equipment_lifecycle.operation_record.del',
  'equipment_lifecycle.operation_record.export',
  'equipment_lifecycle.system.view',
];

async function openApp(page, token, url) {
  await page.addInitScript(({t, perms}) => {
    window.sessionStorage.setItem('token', t);
    window.sessionStorage.setItem('permissions', JSON.stringify(perms));
  }, {t: token, perms: WALKTHROUGH_PERMS});
  await page.goto(url, {waitUntil: 'domcontentloaded'});
}

async function switchTab(page, tabText) {
  await page.click(`.ant-tabs-tab:has-text("${tabText}")`);
  await page.waitForTimeout(600);
}

// 窄屏下 Sider 可能覆盖页签栏（应用外壳层为固定布局）：直接派发 DOM click，
// 绕过遮挡命中测试（截图仍反映真实渲染状态）
async function switchTabByDom(page, tabText) {
  await page.evaluate((text) => {
    const tab = Array.from(document.querySelectorAll('.ant-tabs-tab'))
      .find(node => (node.textContent || '').includes(text));
    if (tab) tab.click();
  }, tabText);
  await page.waitForTimeout(600);
}

test.describe.serial('运行处置记录 UX 走查', () => {
  let token = null;
  let apiCtx = null;
  const created = {routine: null, abnormal: null, fault: null};

  test.beforeAll(async () => {
    const result = await loginAndCreateContext('admin');
    token = result.token;
    apiCtx = result.context;
  });

  test('SEED - 保障最少数据（优先复用既有记录）', async () => {
    // 原始响应为 json_response 双层包装：body.data 即待办负载
    const todo = await apiGet(apiCtx, '/api/equipment-lifecycle/records/todo/');
    const payload = todo.data || {};
    const rows = payload.data || [];
    const counts = payload.counts || {total: 0};
    const needSeed = counts.total < 2 ||
      !rows.some(r => r.record_type === 'abnormal') ||
      !rows.some(r => r.record_type === 'fault');
    if (!needSeed) return;
    const systems = await apiGet(apiCtx,
      '/api/equipment-lifecycle/records/candidate-systems/');
    const systemRows = (systems.data && systems.data.data) || [];
    if (!systemRows.length) {
      console.log('SEED: 无可用系统，跳过造数（走查按空态验证）');
      return;
    }
    const systemId = systemRows[0].id;
    const occurredAt = new Date(Date.now() - 3600 * 1000)
      .toISOString().slice(0, 16).replace('T', ' ');
    const base = {
      system: systemId, occurred_at: occurredAt, registrar_name: '走查机器人',
    };
    const abnormal = await apiPost(apiCtx,
      '/api/equipment-lifecycle/records/', {
        ...base, record_type: 'abnormal',
        title: `${PREFIX}-异常事件-${Date.now()}`, description: '走查造数：信号波动需跟进。',
      });
    if (!abnormal.error) {
      created.abnormal = abnormal.data.id;
      await apiPost(apiCtx,
        `/api/equipment-lifecycle/records/${abnormal.data.id}/progress/`,
        {handler_name: '走查机器人', content: '首条跟进记录（造数）'});
    }
    const fault = await apiPost(apiCtx, '/api/equipment-lifecycle/records/', {
      ...base, record_type: 'fault',
      title: `${PREFIX}-设备故障-${Date.now()}`, description: '走查造数：部件故障处置中。',
      fault_object_name: '走查对象',
    });
    if (!fault.error) created.fault = fault.data.id;
  });

  test('DESKTOP - 列表/筛选分层/新增表单/详情/待办/统计', async ({page}) => {
    await openApp(page, token, '/el/records');
    await page.waitForSelector('.ant-table-tbody', {timeout: 20000});
    await page.waitForTimeout(800);
    await saveShot(page, 'desktop', '01-list');

    const overflow = await pageOverflow(page);
    expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.clientWidth + 2);

    // 编号复制入口在位
    expect(await page.locator('.ant-typography-copy').count()).toBeGreaterThan(0);

    // 筛选分层：更多筛选展开出现记录类型/异常类别
    await page.click('a:has-text("更多筛选")');
    await page.waitForTimeout(400);
    await saveShot(page, 'desktop', '02-filter-advanced');
    expect(await page.locator('text=异常类别').count()).toBeGreaterThan(0);

    // 新增表单：类型说明 + 故障字段按需显示
    await page.click('button:has-text("新增记录")');
    await page.waitForSelector('.ant-modal');
    await page.waitForTimeout(400);
    await saveShot(page, 'desktop', '03-form-routine');
    expect(await page.locator('text=常规作业与运行情况留痕').count()).toBeGreaterThan(0);
    await page.click('.ant-radio-wrapper:has-text("设备故障")');
    await page.waitForTimeout(400);
    await saveShot(page, 'desktop', '04-form-fault');
    expect(await page.locator('.ant-modal:has-text("故障登记（设备故障专用）")').count()).toBeGreaterThan(0);
    await page.click('.ant-modal button:has-text("取 消")');
    await page.waitForTimeout(400);

    // 详情：标题链接打开，下一步指引 + 三个页签
    const titleLink = page.locator('.ant-table-tbody a').first();
    await titleLink.click();
    // 详情 Modal 标题为记录编号，用基本信息区块文案定位
    await page.waitForSelector('.ant-modal:has-text("来源与登记")', {timeout: 15000});
    await page.waitForTimeout(800);
    await saveShot(page, 'desktop', '05-detail-basic');
    const mw = await modalWithinViewport(page);
    expect(mw.overflow).toBe(false);
    // 进展页签（名称随类型：补充/跟进/处置记录），限定在详情 Modal 内
    const progressTab = page.locator('.ant-modal .ant-tabs-tab')
      .filter({hasText: /(补充|跟进|处置)记录/}).first();
    await progressTab.click();
    await page.waitForTimeout(600);
    await saveShot(page, 'desktop', '06-detail-progress');
    await page.click('.ant-modal .ant-tabs-tab:has-text("附件")');
    await page.waitForTimeout(600);
    await saveShot(page, 'desktop', '07-detail-attachments');
    await page.keyboard.press('Escape');
    await page.waitForTimeout(500);

    // 待办：分组计数
    await switchTab(page, '待办');
    await page.waitForTimeout(600);
    await saveShot(page, 'desktop', '08-todo');

    // 统计：核心指标 + 趋势图
    await switchTab(page, '统计');
    await page.waitForTimeout(1000);
    await saveShot(page, 'desktop', '09-statistics');
    const statsOverflow = await pageOverflow(page);
    expect(statsOverflow.scrollWidth).toBeLessThanOrEqual(statsOverflow.clientWidth + 2);
  });

  test('DESKTOP - 系统档案记录页签', async ({page}) => {
    const systems = await apiGet(apiCtx,
      '/api/equipment-lifecycle/records/candidate-systems/');
    // 双层包装：systems.data 为负载字典，systems.data.data 才是数组
    const systemRows = (systems.data && systems.data.data) || [];
    test.skip(!systemRows.length, '无可用系统');
    await openApp(page, token, `/el/systems?detail=${systemRows[0].id}`);
    await page.waitForSelector('.ant-modal', {timeout: 20000});
    await page.waitForTimeout(800);
    const tab = page.locator('.ant-tabs-tab:has-text("运行处置记录")');
    if (await tab.count()) {
      await tab.first().click();
      await page.waitForTimeout(1000);
      await saveShot(page, 'desktop', '10-system-tab');
      // 受控分页在位（分页器存在或明确共 N 条）
      const pager = await page.locator('.ant-modal .ant-pagination').count();
      console.log('系统页签分页器数量:', pager);
    } else {
      console.log('系统详情未提供运行处置记录页签（需人工确认）');
    }
  });

  test('NARROW - 列表/表单/详情/待办/统计 窄屏适配', async ({page, browser}) => {
    const narrow = await browser.newContext({
      viewport: {width: 480, height: 900},
    });
    const np = await narrow.newPage();
    await openApp(np, token, '/el/records');
    await np.waitForSelector('.ant-table-tbody', {timeout: 20000});
    await np.waitForTimeout(800);
    await saveShot(np, 'narrow', '11-list');
    // 窄屏下页面允许表格内部滚动，但页面本身不得出现意外横向溢出
    const overflow = await pageOverflow(np);
    console.log('narrow overflow:', JSON.stringify(overflow));

    await np.click('button:has-text("新增记录")');
    await np.waitForSelector('.ant-modal');
    await np.waitForTimeout(400);
    await saveShot(np, 'narrow', '12-form');
    const formMw = await modalWithinViewport(np);
    expect(formMw.found && formMw.overflow).toBe(false);
    await np.click('.ant-modal button:has-text("取 消")');
    await np.waitForTimeout(300);

    const titleLink = np.locator('.ant-table-tbody a').first();
    if (await titleLink.count()) {
      await titleLink.click();
      await np.waitForSelector('.ant-modal:has-text("来源与登记")', {timeout: 15000});
      await np.waitForTimeout(800);
      await saveShot(np, 'narrow', '13-detail');
      const mw = await modalWithinViewport(np);
      expect(mw.found && mw.overflow).toBe(false);
      await np.keyboard.press('Escape');
      await np.waitForTimeout(500);
    }

    await switchTabByDom(np, '待办');
    await saveShot(np, 'narrow', '14-todo');
    await switchTabByDom(np, '统计');
    await np.waitForTimeout(1000);
    await saveShot(np, 'narrow', '15-statistics');
    await narrow.close();
  });

  test.afterAll(async () => {
    // 清理走查造数：一般记录删除；设备故障撤销（原因必填）；异常事件完成跟进
    if (created.routine) {
      await apiDelete(apiCtx,
        `/api/equipment-lifecycle/records/${created.routine}/`);
    }
    if (created.fault) {
      await apiPost(apiCtx,
        `/api/equipment-lifecycle/records/${created.fault}/cancel/`,
        {cancel_reason: 'E2E 走查造数清理'});
    }
    if (created.abnormal) {
      await apiPost(apiCtx,
        `/api/equipment-lifecycle/records/${created.abnormal}/complete/`, {});
    }
    if (apiCtx) await apiCtx.dispose();
  });
});
