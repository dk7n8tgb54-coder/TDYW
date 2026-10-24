/**
 * 对照实验（2026-10-24）：既有 Excel 模板编辑抽屉在 390×390 窄视口下
 * 是否出现与数字表单编辑器相同的根元素 translateX 偏移。
 * 用于判定 D3（rc-drawer 窄视口偏移）是全局既有现象还是本模块特有。
 */
import {createRequire} from 'node:module';
import {readFileSync} from 'node:fs';

const require = createRequire(new URL('../../e2e/package.json', import.meta.url));
const {chromium} = require('@playwright/test');

const envText = readFileSync(new URL('../../e2e/.env', import.meta.url), 'utf8');
const user = envText.match(/^E2E_ADMIN_USERNAME=(.*)$/m)[1].trim();
const pass = envText.match(/^E2E_ADMIN_PASSWORD=(.*)$/m)[1].trim();

const browser = await chromium.launch();
const page = await browser.newPage({viewport: {width: 390, height: 844}});
await page.goto('http://localhost:3000/el/excel-ledger-templates');
await page.waitForTimeout(3000);
if (await page.locator('input[placeholder="请输入账户"]').count()) {
  await page.fill('input[placeholder="请输入账户"]', user);
  await page.fill('input[placeholder="请输入密码"]', pass);
  await page.click('button:has-text("登")');
  await page.waitForTimeout(3000);
  await page.goto('http://localhost:3000/el/excel-ledger-templates');
  await page.waitForTimeout(3000);
}
// 打开第一个「编辑模板」类按钮（Excel 模板列表）
const btn = page.locator('button:has-text("编辑")').first();
await btn.click();
await page.waitForTimeout(2500);
const result = await page.evaluate(() => {
  const drawers = Array.from(document.querySelectorAll('.ant-drawer')).map(d => {
    const title = (d.querySelector('.ant-drawer-title') || {textContent: ''}).textContent;
    const r = d.getBoundingClientRect();
    return {title: title.slice(0, 24),
            styleAttr: d.getAttribute('style'),
            rect: {left: Math.round(r.left), right: Math.round(r.right)}};
  });
  return {viewport: window.innerWidth, drawerCount: drawers.length, drawers};
});
console.log(JSON.stringify(result, null, 2));
await browser.close();
