import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const BASE = "http://127.0.0.1:4173/";
const OUT = "E:/TDYW/spug-3.0/quality/reports/native_ledger_poc";
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 980 } });
const page = await context.newPage();
const errors = [];
page.on("console", (msg) => { if (msg.type() === "error") errors.push(msg.text()); });
page.on("pageerror", (error) => errors.push(error.message));

await page.goto(BASE, { waitUntil: "networkidle" });
await page.evaluate(() => localStorage.clear());
await page.reload({ waitUntil: "networkidle" });
await page.waitForTimeout(2800);

async function cellPoint(a1) {
  return page.evaluate((address) => {
    const ws = window.__nativeLedgerDebug.worksheet;
    const cell = ws.getRange(address).getCell();
    const zoom = ws.getZoom();
    const canvases = [...document.querySelectorAll("canvas")]
      .map((canvas) => canvas.getBoundingClientRect())
      .filter((rect) => rect.width > 300 && rect.height > 200);
    const canvas = canvases[canvases.length - 1];
    return {
      x: canvas.left + (cell.mergeInfo.startX + (cell.mergeInfo.endX - cell.mergeInfo.startX) / 2) * zoom,
      y: canvas.top + (cell.mergeInfo.startY + (cell.mergeInfo.endY - cell.mergeInfo.startY) / 2) * zoom,
    };
  }, a1);
}

const start = await cellPoint("M13");
const end = await cellPoint("M16");
await page.mouse.move(start.x, start.y);
await page.mouse.down();
await page.mouse.move(end.x, end.y, { steps: 8 });
await page.mouse.up();
await page.waitForTimeout(500);
const selection = await page.evaluate(() => window.__nativeLedgerDebug.selection());
console.log("SELECTION", selection);

await page.fill("#batch-label-prefix", "链路状态");
await page.selectOption("#batch-binding-type", "status");
await page.screenshot({ path: path.join(OUT, "11_batch_bind_panel.png") });
await page.click("#batch-bind");
await page.waitForTimeout(600);
const fieldCount = await page.locator(".binding-row").count();
const statusOptions = await page.locator("#batch-binding-type option").allInnerTexts();
console.log("BATCH_FIELDS", fieldCount, "TYPE_OPTIONS", statusOptions);
await page.screenshot({ path: path.join(OUT, "12_batch_bind_result.png") });

await page.click("#publish-version");
await page.waitForTimeout(800);
await page.click("#tab-fill");
await page.waitForTimeout(1000);
await page.click("#new-record");
await page.waitForTimeout(2400);
const statusFields = page.locator("select.field-input.is-status");
const statusCount = await statusFields.count();
console.log("STATUS_CONTROLS", statusCount);
await statusFields.nth(0).selectOption("正常");
await statusFields.nth(1).selectOption("不正常");
await statusFields.nth(2).selectOption("正常");
await statusFields.nth(3).selectOption("正常");
await page.waitForTimeout(400);
await page.screenshot({ path: path.join(OUT, "13_status_fill.png") });
await page.click("#save-record");
await page.waitForTimeout(700);
const savedCode = await page.locator("#record-code").inputValue();

await page.reload({ waitUntil: "networkidle" });
await page.waitForTimeout(2600);
await page.click("#tab-fill");
await page.waitForTimeout(2400);
const reopenedStatus = await page.locator("select.field-input.is-status").evaluateAll((nodes) => nodes.map((node) => node.value));
const before = await page.evaluate(() => {
  const get = (key) => {
    const el = document.querySelector(`[data-field-key="${key}"]`);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { y: Math.round(r.y), h: Math.round(r.height) };
  };
  const status = document.querySelector("select.field-input.is-status")?.getBoundingClientRect();
  return { scroll: window.__nativeLedgerDebug.scroll(), tx: get("tx_0_0"), name: get("inspector_name"), status: status && { y: Math.round(status.y) } };
});
await page.mouse.move(940, 620);
await page.mouse.wheel(0, 140);
await page.waitForTimeout(700);
const after = await page.evaluate(() => {
  const get = (key) => {
    const el = document.querySelector(`[data-field-key="${key}"]`);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { y: Math.round(r.y), h: Math.round(r.height) };
  };
  const status = document.querySelector("select.field-input.is-status")?.getBoundingClientRect();
  return { scroll: window.__nativeLedgerDebug.scroll(), tx: get("tx_0_0"), name: get("inspector_name"), status: status && { y: Math.round(status.y) } };
});
console.log("SCROLL_BEFORE", JSON.stringify(before));
console.log("SCROLL_AFTER", JSON.stringify(after));
await page.screenshot({ path: path.join(OUT, "14_fill_scrolled.png"), fullPage: false });

const result = {
  completedAt: new Date().toISOString(),
  selection,
  batchFieldCount: fieldCount,
  typeOptions: statusOptions,
  statusCount,
  reopenedStatus,
  savedCode,
  scrollBefore: before,
  scrollAfter: after,
  consoleErrors: errors,
};
fs.writeFileSync(path.join(OUT, "batch_status_result.json"), JSON.stringify(result, null, 2), "utf8");
console.log(JSON.stringify(result, null, 2));
await browser.close();
