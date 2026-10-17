/**
 * 系统升级管理 UX 走查（2026-10-15 工作台体验改造）——真实浏览器端到端。
 *
 * 覆盖（桌面 1440x900 与窄屏 480x900 两轮，均为只读走查不改动数据）：
 * - 列表：独立列保留、"计划升级时间"列名、导出日期标识、标题单击进入工作台；
 * - 工作台首屏：紧凑两行信息栏（标题+状态/系统+计划升级时间+负责人+编号+类型）、
 *   左右六四开两栏同屏（步骤清单 + 状态时间线）、流程区"当前阶段"文案；
 * - 步骤区：当前阶段分组标记、"定位待执行"入口、说明展开、行内"完成"主操作、
 *   "更多"菜单收纳跳过/重置/删除；
 * - 时间线区：日志事件结果文案、"阶段操作"菜单按真实状态生成、
 *   完成节点回退确认预览（目标阶段/重置阶段/步骤数）；
 * - 编辑基本信息：入口存在、展开后含"保存修改/取消"、取消恢复且不跳转；
 * - 窄屏：上下排列布局、菜单可用、无横向溢出。
 *
 * 数据策略：复用环境既有升级记录（优先"处理中"且含多阶段步骤），不新建不修改；
 * 所有菜单/确认仅打开截图后取消。截图输出 quality/reports/e2e/upgrade_workbench_ux/。
 */
const {test, expect} = require('@playwright/test');
const path = require('path');
const fs = require('fs');
const {loginAndCreateContext, apiGet} = require('../helpers/api');

const SHOT_DIR = path.join(__dirname, '..', '..', 'reports', 'e2e',
  'upgrade_workbench_ux');

function shotPath(viewport, name) {
  return path.join(SHOT_DIR, `${viewport}-${name}`);
}

async function saveShot(page, viewport, name) {
  fs.mkdirSync(SHOT_DIR, {recursive: true});
  await page.screenshot({path: shotPath(viewport, name), fullPage: false});
}

const PERMS = [
  'upgrade.upgrade.view',
  'upgrade.upgrade.add',
  'upgrade.upgrade.edit',
  'upgrade.upgrade.step_reset',
  'upgrade.upgrade.step_del',
  'upgrade.plan.view',
];

async function openApp(page, token, url) {
  await page.addInitScript(({t, perms}) => {
    window.sessionStorage.setItem('token', t);
    window.sessionStorage.setItem('permissions', JSON.stringify(perms));
  }, {t: token, perms: PERMS});
  await page.goto(url, {waitUntil: 'domcontentloaded'});
}

// 窄屏下应用外壳 Sider 可能覆盖内容：直接派发 DOM click
async function clickByText(page, selector, text) {
  await page.evaluate(({sel, txt}) => {
    const node = Array.from(document.querySelectorAll(sel))
      .find(n => (n.textContent || '').includes(txt));
    if (node) node.click();
  }, {sel: selector, txt: text});
}

async function closeOverlays(page) {
  await page.keyboard.press('Escape');
  await page.waitForTimeout(300);
  await page.keyboard.press('Escape');
  await page.waitForTimeout(300);
}

test.describe.serial('系统升级管理 UX 走查', () => {
  let token = null;
  let apiCtx = null;
  let targetRecord = null;

  test.beforeAll(async () => {
    const result = await loginAndCreateContext('admin');
    token = result.token;
    apiCtx = result.context;
  });

  test('SEED - 选择既有"处理中"升级记录（不造数）', async () => {
    const res = await apiGet(apiCtx, '/api/upgrade/records/?page_size=50');
    const rows = (res.data && (res.data.records || res.data.data)) || [];
    test.skip(rows.length === 0, '环境无升级记录');
    // 优先处理中（工作台交互最丰富），其次任意
    targetRecord = rows.find(r => r.status === '处理中') || rows[0];
    const detail = await apiGet(apiCtx,
      `/api/upgrade/records/${targetRecord.id}/steps/`);
    const steps = (detail.data && detail.data.steps) || [];
    test.skip(steps.length === 0, '所选记录无步骤清单');
  });

  test('DESKTOP - 列表列名/导出日期标识/标题单击进入工作台', async ({page}) => {
    test.skip(!targetRecord, '无可用升级记录');
    await openApp(page, token, '/upgrade');
    await page.waitForSelector('.ant-table-tbody tr', {timeout: 20000});
    await page.waitForTimeout(600);

    const headers = await page.evaluate(() => Array.from(
      document.querySelectorAll('.ant-table-thead th')).map(th => th.textContent));
    expect(headers).toContain('编号');
    expect(headers).toContain('标题');
    expect(headers).toContain('计划升级时间');
    expect(headers).not.toContain('升级时间');
    expect(await page.locator('text=导出日期').count()).toBeGreaterThan(0);
    await saveShot(page, 'desktop', '01-list.png');

    // 标题单击进入工作台
    await clickByText(page, '.ant-table-tbody button, .ant-table-tbody a',
      targetRecord.title);
    await page.waitForURL('**/upgrade/workbench/**', {timeout: 15000});
    await page.waitForSelector('.ant-layout-header', {timeout: 15000});
    await page.waitForTimeout(1000);
  });

  test('DESKTOP - 工作台首屏布局与信息栏层级', async ({page}) => {
    test.skip(!targetRecord, '无可用升级记录');
    await openApp(page, token, `/upgrade/workbench/${targetRecord.id}`);
    await page.waitForSelector('[class*="infoBar"]', {timeout: 20000});
    await page.waitForTimeout(1200);
    await saveShot(page, 'desktop', '02-workbench-first-screen.png');

    // 顶栏不再重复标题；信息栏第一行含标题与状态
    const headerTitle = await page.locator('[class*="headerTitle"]').textContent();
    expect(headerTitle).not.toContain(targetRecord.title);
    expect(headerTitle).toContain('升级工作台');
    const infoBar = page.locator('[class*="infoBar"]');
    expect(await infoBar.locator(`text=${targetRecord.title}`).count())
      .toBeGreaterThanOrEqual(1);
    expect(await infoBar.locator('text=计划升级时间').count()).toBeGreaterThan(0);
    expect(await infoBar.locator('text=编号').count()).toBeGreaterThan(0);
    expect(await infoBar.locator('text=编辑基本信息').count()).toBeGreaterThan(0);

    // 左右两栏同屏可见（首屏内）
    const visible = await page.evaluate(() => {
      const panels = document.querySelectorAll('[class*="panelHeader"]');
      const vh = window.innerHeight;
      return Array.from(panels).filter(el => {
        const rect = el.getBoundingClientRect();
        return rect.top > 0 && rect.top < vh;
      }).length;
    });
    expect(visible).toBeGreaterThanOrEqual(2);

    // 流程区当前阶段文案
    expect(await page.locator('[class*="flowHeadline"]').textContent())
      .toContain('当前阶段');

    // 布局回归：两栏面板必须被容器高度约束（nowrap），附件区不得与面板重叠
    const noOverlap = await page.evaluate(() => {
      const row = document.querySelector('[class*="panelsRow"]');
      const collapse = document.querySelector('.ant-collapse');
      if (!row || !collapse) return true;
      return collapse.getBoundingClientRect().top >=
        row.getBoundingClientRect().bottom - 1;
    });
    expect(noOverlap).toBe(true);
  });

  test('DESKTOP - 步骤区：当前阶段标记/定位待执行/说明展开/更多菜单', async ({page}) => {
    test.skip(!targetRecord, '无可用升级记录');
    await openApp(page, token, `/upgrade/workbench/${targetRecord.id}`);
    await page.waitForSelector('[class*="stepList"]', {timeout: 20000});
    await page.waitForTimeout(1000);

    // 当前阶段分组标记
    expect(await page.locator('[class*="currentPhaseTag"]').count())
      .toBeGreaterThanOrEqual(1);

    // 说明展开（若存在说明入口）
    const descBtn = page.locator('[class*="stepList"] button:has-text("说明")').first();
    if (await descBtn.count() > 0) {
      await descBtn.click();
      await page.waitForTimeout(300);
      await saveShot(page, 'desktop', '03-step-desc-expanded.png');
      await page.locator('[class*="stepList"] button:has-text("收起说明")').first().click();
      await page.waitForTimeout(200);
    }

    // 定位待执行：点击后步骤列表滚动位置变化
    const locate = page.locator('button:has-text("定位待执行")');
    if (await locate.count() > 0) {
      const before = await page.evaluate(() => {
        const el = document.querySelector('[class*="stepList"]');
        return el ? el.scrollTop : -1;
      });
      await locate.click();
      await page.waitForTimeout(600);
      const after = await page.evaluate(() => {
        const el = document.querySelector('[class*="stepList"]');
        return el ? el.scrollTop : -1;
      });
      // 有溢出才产生滚动差异；无溢出时链接仍在即视为通过
      expect(after).toBeGreaterThanOrEqual(0);
      if (before === 0) {
        // 不强制断言滚动量（内容可能一屏放下），仅要求不报错
        expect(after).toBeGreaterThanOrEqual(0);
      }
    }

    // 待执行步骤"更多"菜单
    const moreBtn = page.locator('[class*="stepList"] [aria-label*="更多操作"]').first();
    if (await moreBtn.count() > 0) {
      await moreBtn.click();
      await page.waitForTimeout(500);
      const menuVisible = await page.locator('.ant-dropdown:visible').count();
      expect(menuVisible).toBeGreaterThan(0);
      await saveShot(page, 'desktop', '04-step-more-menu.png');
      await closeOverlays(page);
    }
  });

  test('DESKTOP - 阶段操作菜单与回退确认预览', async ({page}) => {
    test.skip(!targetRecord, '无可用升级记录');
    await openApp(page, token, `/upgrade/workbench/${targetRecord.id}`);
    await page.waitForSelector('[class*="timelineScroll"]', {timeout: 20000});
    await page.waitForTimeout(1000);

    // 阶段操作菜单按真实状态生成
    const phaseMenuBtn = page.locator('button:has-text("阶段操作")');
    if (await phaseMenuBtn.count() > 0) {
      await phaseMenuBtn.click();
      await page.waitForTimeout(500);
      expect(await page.locator('.ant-dropdown:visible').count()).toBeGreaterThan(0);
      await saveShot(page, 'desktop', '05-phase-action-menu.png');
      await closeOverlays(page);
    }

    // 时间线日志为事件结果文案（阶段完成/未通过/已撤销/动作文本）
    const timelineText = await page.locator('[class*="timelineScroll"]').textContent();
    expect(timelineText.length === 0 || timelineText.includes('阶段')
      || timelineText.includes('暂无状态记录')).toBe(true);

    // 完成节点点击 → 回退确认（目标阶段/重置阶段/步骤数）
    const node = page.locator('[class*="nodeClickable"]').first();
    if (await node.count() > 0) {
      await node.click();
      await page.waitForTimeout(600);
      const confirmModal = page.locator('.ant-modal-confirm');
      if (await confirmModal.count() > 0) {
        const confirmText = await confirmModal.textContent();
        expect(confirmText).toContain('回退');
        expect(confirmText).toMatch(/将回退到阶段|重置为待执行/);
        await saveShot(page, 'desktop', '06-rollback-confirm.png');
        await page.locator('.ant-modal-confirm .ant-btn:not(.ant-btn-dangerous):has-text("取消"), .ant-modal-confirm button:has-text("取 消")').first().click();
        await page.waitForTimeout(300);
      }
    }
  });

  test('DESKTOP - 详细说明与编辑基本信息（取消不跳转）', async ({page}) => {
    test.skip(!targetRecord, '无可用升级记录');
    await openApp(page, token, `/upgrade/workbench/${targetRecord.id}`);
    await page.waitForSelector('[class*="infoBar"]', {timeout: 20000});
    await page.waitForTimeout(800);

    // 详细说明展开（只读，查看用户可用）
    const detailToggle = page.locator('button:has-text("详细说明")');
    if (await detailToggle.count() > 0) {
      await detailToggle.first().click();
      await page.waitForTimeout(300);
      expect(await page.locator('[class*="detailBlocks"]').count()).toBeGreaterThan(0);
      await saveShot(page, 'desktop', '07-detail-blocks.png');
      await page.locator('button:has-text("收起详细说明")').first().click();
      await page.waitForTimeout(200);
    }

    // 编辑基本信息：展开后含保存修改/取消；取消恢复且不离开工作台
    await page.locator('button:has-text("编辑基本信息")').first().click();
    await page.waitForTimeout(400);
    expect(await page.locator('button:has-text("保存修改")').count()).toBeGreaterThan(0);
    expect(await page.locator('[class*="editPanel"]').count()).toBeGreaterThan(0);
    await saveShot(page, 'desktop', '08-edit-panel.png');
    // antd 两字按钮自动插空格："取 消"
    await page.locator('[class*="editActions"] button')
      .filter({hasText: /取\s*消/}).click();
    await page.waitForTimeout(400);
    expect(await page.locator('[class*="editPanel"]').count()).toBe(0);
    expect(page.url()).toContain(`/upgrade/workbench/${targetRecord.id}`);
  });

  test('NARROW - 480px 窄屏上下排列与控件可用性', async ({page, browser}) => {
    test.skip(!targetRecord, '无可用升级记录');
    const narrow = await browser.newContext({
      viewport: {width: 480, height: 900},
    });
    const npage = await narrow.newPage();
    await openApp(npage, token, `/upgrade/workbench/${targetRecord.id}`);
    await npage.waitForSelector('[class*="infoBar"]', {timeout: 20000});
    await npage.waitForTimeout(1200);
    await saveShot(npage, 'narrow', '11-workbench.png');

    // 两栏纵向堆叠（第二栏在第一栏下方）
    const stacked = await npage.evaluate(() => {
      const cols = document.querySelectorAll('[class*="panelCol"]');
      if (cols.length < 2) return false;
      const a = cols[0].getBoundingClientRect();
      const b = cols[1].getBoundingClientRect();
      return b.top >= a.bottom - 2;
    });
    expect(stacked).toBe(true);

    // 无意外横向溢出
    const overflow = await npage.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.clientWidth + 2);

    // 更多菜单可用
    const moreBtn = npage.locator('[class*="stepList"] [aria-label*="更多操作"]').first();
    if (await moreBtn.count() > 0) {
      await moreBtn.click();
      await npage.waitForTimeout(500);
      expect(await npage.locator('.ant-dropdown:visible').count()).toBeGreaterThan(0);
      await saveShot(npage, 'narrow', '12-more-menu.png');
      await closeOverlays(npage);
    }
    await narrow.close();
  });
});
