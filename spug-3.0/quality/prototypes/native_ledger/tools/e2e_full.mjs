import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const BASE = "http://127.0.0.1:4173/";
const OUT = "E:/TDYW/spug-3.0/quality/reports/native_ledger_poc";
fs.mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 980 }, acceptDownloads: true });
const page = await context.newPage();
const logs = [];
page.on("console", (msg) => {
  if (msg.type() === "error") logs.push(`console-error: ${msg.text()}`);
});
page.on("pageerror", (error) => logs.push(`page-error: ${error.message}`));

const timings = {};
const started = Date.now();
await page.goto(BASE, { waitUntil: "networkidle" });
await page.evaluate(() => localStorage.clear());
await page.reload({ waitUntil: "networkidle" });
await page.waitForTimeout(2600);
timings.initial_load_ms = Date.now() - started;

async function shot(name, fullPage = false) {
  await page.screenshot({ path: path.join(OUT, name), fullPage });
}

async function clickCell(a1) {
  const point = await page.evaluate((cellA1) => {
    const ws = window.__nativeLedgerDebug.worksheet;
    const cell = ws.getRange(cellA1).getCell();
    const zoom = ws.getZoom();
    const canvases = [...document.querySelectorAll("canvas")]
      .map((canvas) => canvas.getBoundingClientRect())
      .filter((rect) => rect.width > 300 && rect.height > 200);
    const canvas = canvases[canvases.length - 1];
    return {
      x: canvas.left + cell.mergeInfo.startX * zoom + 8,
      y: canvas.top + cell.mergeInfo.startY * zoom + 8,
    };
  }, a1);
  await page.mouse.click(point.x, point.y);
}

await shot("01_template_desktop.png");
console.log("STEP template screenshot");

const editStarted = Date.now();
await page.fill("#template-title", "通信信道维护台账（2026 年第三季度 · 已校核）");
await page.click("#apply-title");
await page.waitForTimeout(700);
await clickCell("E5");
await page.waitForTimeout(500);
console.log("SELECTED", await page.locator("#selected-range").innerText());
await page.fill("#binding-label", "驻波比复核");
await page.selectOption("#binding-type", "text");
await page.click("#add-binding");
await page.waitForTimeout(500);
await shot("02_template_after_edit.png");
await page.click("#publish-version");
await page.waitForTimeout(900);
const versionCount = await page.locator(".version-row").count();
console.log("VERSIONS", versionCount);
timings.template_edit_ms = Date.now() - editStarted;

await page.click("#tab-fill");
await page.waitForTimeout(1600);
await page.click("#new-record");
await page.waitForTimeout(2300);
console.log("FIELDS", await page.locator("[data-field-key]").count());
const customKey = await page.evaluate(() => {
  const workspace = JSON.parse(localStorage.getItem("native-ledger-poc.workspace.v1"));
  return workspace.template.draft.bindings.find((item) => item.label === "驻波比复核")?.key;
});
console.log("CUSTOM_KEY", customKey);
const fillStarted = Date.now();
const seedValues = await page.evaluate(() => {
  const workspace = JSON.parse(localStorage.getItem("native-ledger-poc.workspace.v1"));
  return workspace.records.find((record) => record.id === "rec-demo-001")?.values || {};
});
for (const [key, value] of Object.entries(seedValues)) {
  if (["inspector_name", "inspect_date"].includes(key)) continue;
  const field = page.locator(`[data-field-key="${key}"]`);
  if (await field.count()) await field.fill(String(value));
}
await page.fill('[data-field-key="tx_0_0"]', "43.6");
await page.fill('[data-field-key="rx_0_0"]', "-71.8");
await page.fill('[data-field-key="overall"]', "本季度信道指标总体正常，抽检问题已闭环。");
await page.fill(`[data-field-key="${customKey}"]`, "1.22");
await page.fill('[data-field-key="inspector_name"]', "李敏");
await page.fill('[data-field-key="inspect_date"]', "2026-09-20");
await page.waitForTimeout(300);
const liveMetaDate = await page.evaluate(() => window.__nativeLedgerDebug.worksheet.getRange("G2").getValue());
await shot("03_fill_desktop.png");
await page.click("#save-record");
await page.waitForTimeout(700);
timings.fill_and_save_ms = Date.now() - fillStarted;
const savedCode = await page.locator("#record-code").inputValue();
console.log("SAVED", savedCode);

await page.reload({ waitUntil: "networkidle" });
await page.waitForTimeout(2400);
await page.click("#tab-fill");
await page.waitForTimeout(2300);
const reopened = {
  code: await page.locator("#record-code").inputValue(),
  name: await page.locator('[data-field-key="inspector_name"]').inputValue(),
  date: await page.locator('[data-field-key="inspect_date"]').inputValue(),
  tx: await page.locator('[data-field-key="tx_0_0"]').inputValue(),
  custom: await page.locator(`[data-field-key="${customKey}"]`).inputValue(),
};
console.log("REOPENED", JSON.stringify(reopened));
await shot("04_fill_reopened_desktop.png");

await page.click("#open-print");
await page.waitForTimeout(1400);
await shot("05_print_preview_a4_landscape.png");
const previewMeta = await page.locator(".print-meta").innerText();
console.log("PREVIEW_META", previewMeta);

const pdfStarted = Date.now();
async function exportPdf(name) {
  const downloadPromise = page.waitForEvent("download", { timeout: 40000 });
  await page.click("#export-pdf");
  const download = await downloadPromise;
  const target = path.join(OUT, name);
  await download.saveAs(target);
  return fs.statSync(target).size;
}
const a4Size = await exportPdf("native-ledger_A4_landscape.pdf");
timings.a4_pdf_ms = Date.now() - pdfStarted;

await page.selectOption("#paper-size", "A3");
await page.waitForTimeout(1200);
await shot("06_print_preview_a3_landscape.png");
const a3Started = Date.now();
const a3Size = await exportPdf("native-ledger_A3_landscape.pdf");
timings.a3_pdf_ms = Date.now() - a3Started;

await page.selectOption("#paper-size", "A4");
await page.selectOption("#paper-orientation", "portrait");
await page.waitForTimeout(1200);
await shot("07_print_preview_a4_portrait.png");
const portraitWarnings = await page.locator(".print-warnings li").allInnerTexts();
const portraitSize = await exportPdf("native-ledger_A4_portrait.pdf");
console.log("PORTRAIT_WARNINGS", JSON.stringify(portraitWarnings));

await page.uncheck("#fit-to-width");
await page.waitForTimeout(1000);
await shot("10_print_preview_a4_portrait_actual.png");
const actualWarnings = await page.locator(".print-warnings li").allInnerTexts();
const actualSize = await exportPdf("native-ledger_A4_portrait_actual.pdf");
console.log("ACTUAL_WARNINGS", JSON.stringify(actualWarnings));
await page.click(".print-dialog-head .icon-button");
await page.waitForTimeout(500);

await page.setViewportSize({ width: 900, height: 1100 });
await page.reload({ waitUntil: "networkidle" });
await page.waitForTimeout(2400);
await page.click("#tab-template");
await page.waitForTimeout(800);
await shot("08_template_narrow_900.png", true);
await page.click("#tab-fill");
await page.waitForTimeout(2400);
const narrowField = await page.evaluate(() => {
  const el = document.querySelector('[data-field-key="inspector_name"]');
  const r = el?.getBoundingClientRect();
  const stage = document.querySelector(".sheet-stage").getBoundingClientRect();
  return r ? { x: r.x, y: r.y, w: r.width, h: r.height, stage: { x: stage.x, y: stage.y, w: stage.width, h: stage.height }, font: getComputedStyle(el).fontSize } : null;
});
console.log("NARROW_FIELD", JSON.stringify(narrowField));
await shot("09_fill_narrow_900.png", true);

page.once("dialog", (dialog) => dialog.accept());
await page.getByRole("button", { name: "清空样板数据" }).first().click();
await page.waitForTimeout(500);
const cleared = await page.locator(".empty-card").innerText();
await page.getByRole("button", { name: "恢复示例数据" }).click();
await page.waitForTimeout(2200);
const restored = await page.locator(".platform-logo strong").innerText();
console.log("CLEARED", cleared.split("\n")[1], "RESTORED", restored);

const result = {
  completedAt: new Date().toISOString(),
  timings,
  versions: versionCount,
  savedCode,
  reopened,
  liveMetaDate,
  clearRestore: { cleared: Boolean(cleared), restored },
  previewMeta,
  portraitWarnings,
  actualWarnings,
  pdfBytes: { a4: a4Size, a3: a3Size, a4Portrait: portraitSize, a4PortraitActual: actualSize },
  narrowField,
  consoleErrors: logs,
};
fs.writeFileSync(path.join(OUT, "e2e_result.json"), JSON.stringify(result, null, 2), "utf8");
console.log("RESULT", JSON.stringify(result, null, 2));
await browser.close();
