/**
 * 窄屏编辑器 drawer 定位独立复核（真实 Chromium，2026-10-24）。
 *
 * 背景：IAB 实测编辑器抽屉根元素带 transform matrix(1,0,0,1,-180,0)，
 * footer 整体左移 125px；需判定是 IAB 渲染怪癖还是产品缺陷。
 * 本脚本以独立 Chromium 390×844 走同一页面路径量测同一组数值。
 */
import {createRequire} from 'node:module';
import {readFileSync} from 'node:fs';

// Playwright 依赖在 quality/e2e（自包含），从那里解析
const require = createRequire(new URL('../../e2e/package.json', import.meta.url));
const {chromium} = require('@playwright/test');

const envText = readFileSync(new URL('../../e2e/.env', import.meta.url), 'utf8');
const user = envText.match(/^E2E_ADMIN_USERNAME=(.*)$/m)[1].trim();
const pass = envText.match(/^E2E_ADMIN_PASSWORD=(.*)$/m)[1].trim();

const browser = await chromium.launch();
const vw = parseInt(process.env.VW || '390', 10);
const page = await browser.newPage({viewport: {width: vw, height: 844}});
await page.goto('http://localhost:3000/el/form-ledger-templates');
await page.waitForTimeout(3000);
if (await page.locator('input[placeholder="请输入账户"]').count()) {
  await page.fill('input[placeholder="请输入账户"]', user);
  await page.fill('input[placeholder="请输入密码"]', pass);
  await page.click('button:has-text("登")');
  await page.waitForTimeout(3000);
  await page.goto('http://localhost:3000/el/form-ledger-templates');
  await page.waitForTimeout(3000);
}
await page.fill('input[placeholder="搜索模板名称"]', 'E2E_填写体验');
await page.waitForTimeout(1200);
await page.click('button:has-text("编辑表单")');
await page.waitForTimeout(2500);

const result = await page.evaluate(() => {
  const drawers = Array.from(document.querySelectorAll('.ant-drawer'))
    .map(d => {
      const title = (d.querySelector('.ant-drawer-title') || {textContent: ''}).textContent;
      const cs = getComputedStyle(d);
      const r = d.getBoundingClientRect();
      const mask = d.querySelector('.ant-drawer-mask');
      return {title: title.slice(0, 20), transform: cs.transform,
              rect: {left: Math.round(r.left), right: Math.round(r.right)},
              rootStyleAttr: d.getAttribute('style'),
              maskStyleAttr: mask ? mask.getAttribute('style') : null};
    });
  const footer = document.querySelector('.ant-drawer-footer');
  const fr = footer.getBoundingClientRect();
  const publish = Array.from(document.querySelectorAll('button'))
    .find(b => b.textContent.replace(/\s/g, '') === '发布版本');
  const pr = publish.getBoundingClientRect();
  const transformHolders = Array.from(document.querySelectorAll('body *'))
    .filter(el => /translateX/.test(el.getAttribute('style') || ''))
    .map(el => ({tag: el.tagName, cls: el.className.toString().slice(0, 50),
                 w: Math.round(el.getBoundingClientRect().width),
                 style: (el.getAttribute('style') || '').slice(0, 90)}));
  return {
    viewport: window.innerWidth,
    drawers,
    bodyStyle: {overflow: document.body.style.overflow,
                paddingRight: document.body.style.paddingRight},
    scrollbarEnv: {innerW: window.innerWidth,
                   bodyOffsetW: document.body.offsetWidth,
                   docClientW: document.documentElement.clientWidth},
    transformHolders,
    footer: {left: Math.round(fr.left), right: Math.round(fr.right),
             w: Math.round(fr.width), scrollW: footer.scrollWidth},
    publish: {left: Math.round(pr.left), right: Math.round(pr.right),
              fullyVisible: pr.left >= 0 && pr.right <= window.innerWidth},
  };
});
console.log(JSON.stringify(result, null, 2));
await browser.close();
