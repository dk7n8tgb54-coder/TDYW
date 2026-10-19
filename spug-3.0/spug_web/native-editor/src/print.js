/**
 * 打印分页 HTML 构建（正式编辑器预览用）。
 *
 * 分页规范与后端 native_pdf_service.py 一致（同一套算法的 JS 版）：
 * - 打印范围 = 实际内容范围（cellData/合并覆盖到的最大行列），不打印空白补位行；
 * - 重复表头 = 快照冻结行（freeze.ySplit），跨页自动重复；
 * - 分页按行高累计，分页点避开纵向合并区域（合并起始行前断页；
 *   合并起始行就是页首且整页放不下时按行切断并告警）；
 * - fitToWidth 按内容宽度收缩（只缩不放），字体随缩放；
 * - 边框完全按快照样式 bd 声明绘制，未画边框不输出边框。
 *
 * 预览与导出同源：本模块只负责预览 HTML；导出 PDF 由宿主页面请求
 * 后端正式接口生成（服务端按同一份版本快照渲染），保证导出内容
 * 以服务端数据为准。
 */
import { PAPER_PRESETS } from "./template";

const MM_TO_PX = 96 / 25.4;
const FOOTER_HEIGHT_PX = 22;
const LOW_SCALE_WARN = 0.7;

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function color(value) {
  if (!value) return "";
  if (typeof value === "string") return value;
  return value.rgb || "";
}

function colName(index) {
  let n = index + 1;
  let out = "";
  while (n > 0) {
    const rem = (n - 1) % 26;
    out = String.fromCharCode(65 + rem) + out;
    n = Math.floor((n - 1) / 26);
  }
  return out;
}

function getSheet(snapshot) {
  const sheetId = snapshot.sheetOrder?.[0] || Object.keys(snapshot.sheets)[0];
  return snapshot.sheets[sheetId];
}

function rowHeight(sheet, row) {
  const entry = sheet.rowData?.[row] || {};
  return Number(entry.h ?? sheet.defaultRowHeight ?? 32);
}

function colWidth(sheet, col) {
  const entry = sheet.columnData?.[col] || {};
  return Number(entry.w ?? sheet.defaultColumnWidth ?? 88);
}

function cellValue(sheet, row, col, bindingByRange, values) {
  const binding = bindingByRange[`${colName(col)}${row + 1}`];
  if (binding && Object.prototype.hasOwnProperty.call(values, binding.key)) {
    return values[binding.key];
  }
  return sheet.cellData?.[row]?.[col]?.v ?? "";
}

function styleOf(snapshot, sheet, row, col) {
  const ref = sheet.cellData?.[row]?.[col]?.s;
  if (!ref) return {};
  const style = typeof ref === "string" ? snapshot.styles?.[ref] : ref;
  return style || {};
}

function borderCss(style) {
  const bd = style.bd;
  if (!bd || typeof bd !== "object") return "";
  const sides = { t: "top", r: "right", b: "bottom", l: "left" };
  const pieces = [];
  for (const [short, side] of Object.entries(sides)) {
    const border = bd[short];
    if (!border || typeof border !== "object" || !border.s) continue;
    const rgb = color(border.cl) || "#64748b";
    pieces.push(`border-${side}:0.5px solid ${esc(rgb)}`);
  }
  return pieces.join(";");
}

function inlineStyle(style, scale) {
  const fs = Number(style.fs || 9) * 1.3333 * scale;
  const pieces = [
    `font-size:${fs.toFixed(2)}px`,
    `font-family:${esc(style.ff || "Microsoft YaHei")}, "Noto Sans CJK SC", "SimSun", sans-serif`,
    `color:${esc(color(style.cl) || "#111827")}`,
    `background:${esc(color(style.bg) || "transparent")}`,
    `text-align:${style.ht === 1 ? "left" : style.ht === 3 ? "right" : "center"}`,
    `vertical-align:${style.vt === 1 ? "top" : style.vt === 3 ? "bottom" : "middle"}`,
    "white-space:pre-wrap",
    "word-break:break-word",
    "overflow:hidden",
    "line-height:1.25",
    "padding:2px 3px",
    "box-sizing:border-box",
  ];
  if (style.bl === 1) pieces.push("font-weight:700");
  if (style.it === 1) pieces.push("font-style:italic");
  const border = borderCss(style);
  if (border) pieces.push(border);
  return pieces.join(";");
}

function parseA1(range) {
  const match = /^([A-Z]{1,3})([1-9][0-9]*)$/.exec(String(range || "").toUpperCase());
  if (!match) return null;
  let col = 0;
  for (const ch of match[1]) col = col * 26 + (ch.charCodeAt(0) - 64);
  return { row: parseInt(match[2], 10) - 1, col: col - 1 };
}

function contentExtent(sheet, bindings) {
  let maxRow = 0;
  let maxCol = 0;
  for (const [rowKey, cols] of Object.entries(sheet.cellData || {})) {
    const row = Number(rowKey);
    if (!Number.isInteger(row) || row < 0) continue;
    maxRow = Math.max(maxRow, row);
    for (const colKey of Object.keys(cols)) {
      const col = Number(colKey);
      if (Number.isInteger(col) && col >= 0) maxCol = Math.max(maxCol, col);
    }
  }
  for (const merge of sheet.mergeData || []) {
    maxRow = Math.max(maxRow, Number(merge.endRow) || 0);
    maxCol = Math.max(maxCol, Number(merge.endColumn) || 0);
  }
  // 绑定单元格计入范围：填写格可能没有底表静态内容（空格子绑定）
  for (const binding of bindings || []) {
    const parsed = parseA1(binding && binding.range);
    if (!parsed) continue;
    maxRow = Math.max(maxRow, parsed.row);
    maxCol = Math.max(maxCol, parsed.col);
  }
  return { maxRow, maxCol };
}

function frozenHeaderRows(sheet) {
  const ySplit = Math.max(0, Math.min(10, Number(sheet.freeze?.ySplit) || 0));
  return Array.from({ length: ySplit }, (_, i) => i);
}

function crossingMerge(merges, breakRow) {
  return merges.find((m) => m.startRow < breakRow && m.endRow >= breakRow) || null;
}

function paginate(sheet, merges, headerRows, lastRow, contentHeightPx, scale, warnings) {
  const pages = [];
  const available = contentHeightPx - FOOTER_HEIGHT_PX;
  const firstContent = headerRows.length ? headerRows[headerRows.length - 1] + 1 : 0;
  let cursor = firstContent;
  while (cursor <= lastRow) {
    let pageRows = [...headerRows];
    let used = headerRows.reduce((sum, r) => sum + rowHeight(sheet, r) * scale, 0);
    let r = cursor;
    while (r <= lastRow) {
      const height = rowHeight(sheet, r) * scale;
      if (used + height > available && pageRows.length > headerRows.length) break;
      pageRows.push(r);
      used += height;
      r += 1;
    }
    if (pageRows.length === headerRows.length) {
      // 单行超出整页可用高度：强制放行该行，避免死循环
      pageRows.push(cursor);
      r = cursor + 1;
      warnings.push(`第 ${pages.length + 1} 页存在超高行，内容可能溢出页面。`);
    } else if (r <= lastRow) {
      const crossing = crossingMerge(merges, r);
      if (crossing && crossing.startRow > cursor) {
        pageRows = [...headerRows, ...pageRows.filter((x) => x >= cursor && x < crossing.startRow)];
        r = crossing.startRow;
        warnings.push(`第 ${pages.length + 1} 页按行分页，分页点避开纵向合并区域。`);
      } else if (crossing) {
        warnings.push(`第 ${pages.length + 1} 页存在超出整页高度的合并区域，跨页部分被切断。`);
      } else {
        warnings.push(`第 ${pages.length + 1} 页按行分页。`);
      }
    }
    pages.push(pageRows);
    cursor = r;
  }
  if (!pages.length) pages.push([...headerRows]);
  return pages;
}

function buildTable({ snapshot, sheet, pageRows, merges, bindingByRange, values, scale, maxCol }) {
  const widths = Array.from({ length: maxCol + 1 }, (_, c) => colWidth(sheet, c) * scale);
  const totalWidth = widths.reduce((sum, w) => sum + w, 0);
  const rowsSet = new Set(pageRows);
  const covered = new Set();
  for (const merge of merges) {
    if (!rowsSet.has(merge.startRow) || !rowsSet.has(merge.endRow)) continue;
    for (let r = merge.startRow; r <= merge.endRow; r += 1) {
      for (let c = merge.startColumn; c <= merge.endColumn; c += 1) {
        if (r !== merge.startRow || c !== merge.startColumn) covered.add(`${r}:${c}`);
      }
    }
  }
  const colGroup = widths.map((w) => `<col style="width:${w.toFixed(2)}px">`).join("");
  const rowsHtml = pageRows.map((r) => {
    const cells = [];
    for (let c = 0; c <= maxCol; c += 1) {
      if (covered.has(`${r}:${c}`)) continue;
      let rowSpan = 1;
      let colSpan = 1;
      for (const merge of merges) {
        if (merge.startRow === r && merge.startColumn === c && rowsSet.has(merge.endRow)) {
          rowSpan = merge.endRow - merge.startRow + 1;
          colSpan = merge.endColumn - merge.startColumn + 1;
          break;
        }
      }
      const value = cellValue(sheet, r, c, bindingByRange, values);
      const text = value === null || value === undefined || value === "" ? "&nbsp;" : esc(value);
      const style = inlineStyle(styleOf(snapshot, sheet, r, c), scale);
      cells.push(
        `<td rowspan="${rowSpan}" colspan="${colSpan}" style="${style}">${text}</td>`,
      );
    }
    return `<tr style="height:${(rowHeight(sheet, r) * scale).toFixed(2)}px">${cells.join("")}</tr>`;
  }).join("");
  return {
    html: `<table class="ledger-table" style="width:${totalWidth.toFixed(2)}px"><colgroup>${colGroup}</colgroup><tbody>${rowsHtml}</tbody></table>`,
    totalWidth,
  };
}

function pageCss(pageWidth, pageHeight, margins, previewZoom) {
  return `
    @page { size: ${pageWidth}mm ${pageHeight}mm; margin: 0; }
    * { box-sizing: border-box; }
    html, body { margin: 0; padding: 0; background: #e5e7eb; }
    body { font-family: "Microsoft YaHei", "Noto Sans CJK SC", "SimSun", sans-serif; color: #111827; }
    .pages { display: flex; flex-direction: column; align-items: center; gap: 12mm; padding: 8mm 0; }
    .page-sheet { position: relative; background: #fff; overflow: hidden; break-after: page; page-break-after: always;
      width:${pageWidth}mm;height:${pageHeight}mm;padding:${margins.top}mm ${margins.right}mm ${margins.bottom}mm ${margins.left}mm; }
    .page-sheet:last-child { break-after: auto; page-break-after: auto; }
    .page-inner { width: 100%; height: 100%; display: flex; flex-direction: column; }
    .ledger-caption { display: none; justify-content: space-between; align-items: baseline; gap: 8px; margin: 0 0 2mm; color: #334155; font-size: 8pt; font-weight: 600; }
    .page-sheet:not([data-page="1"]) .ledger-caption { display: flex; }
    .record-code { color: #1d4ed8; font-size: 8pt; }
    .ledger-table { border-collapse: collapse; table-layout: fixed; margin: 0 auto; }
    .ledger-table td { border: none; padding: 2px 3px; overflow: hidden; }
    .page-spacer { flex: 1 1 auto; }
    .page-foot { display: flex; justify-content: space-between; gap: 8px; padding-top: 2mm; color: #64748b; font-size: 7.5pt; border-top: 0.5px solid #cbd5e1; }
    @media screen {
      body { zoom: ${previewZoom}; }
      .pages { padding: 8mm 0 12mm; }
      .page-sheet { box-shadow: 0 2px 10px rgba(15,23,42,.18); }
    }
    @media print {
      html, body { background: #fff; zoom: 1 !important; }
      .pages { display: block; padding: 0; gap: 0; }
      .page-sheet { box-shadow: none; margin: 0; }
    }
  `;
}

/**
 * 构建打印预览 HTML。meta: {templateName, recordCode}。
 * 返回 {html, pageCount, scale, warnings, rawWidth, contentWidth, crossPageMerges}。
 */
export function renderPrintDocument({
  snapshot,
  bindings,
  values,
  paper,
  meta,
  previewZoom = 1,
}) {
  const sheet = getSheet(snapshot);
  const { maxRow, maxCol } = contentExtent(sheet, bindings);
  const dims = PAPER_PRESETS[paper.size] || PAPER_PRESETS.A4;
  const pageWidth = paper.orientation === "landscape" ? dims.height : dims.width;
  const pageHeight = paper.orientation === "landscape" ? dims.width : dims.height;
  const margins = paper.margins;
  const contentWidth = (pageWidth - margins.left - margins.right) * MM_TO_PX;
  const contentHeight = (pageHeight - margins.top - margins.bottom) * MM_TO_PX;
  const rawWidth = Array.from({ length: maxCol + 1 }, (_, c) => colWidth(sheet, c))
    .reduce((a, b) => a + b, 0);
  const scale = paper.fitToWidth && rawWidth > 0
    ? Math.min(1, contentWidth / rawWidth)
    : 1;
  const merges = (sheet.mergeData || []).map((merge) => ({
    startRow: merge.startRow,
    startColumn: merge.startColumn,
    endRow: merge.endRow,
    endColumn: merge.endColumn,
  }));
  const warnings = [];
  const pages = paginate(
    sheet, merges, frozenHeaderRows(sheet), maxRow, contentHeight, scale, warnings);
  if (scale < LOW_SCALE_WARN) {
    warnings.push(`当前纸张下自动缩放为 ${(scale * 100).toFixed(0)}%，已低于 70% 的可读性参考线。`);
  }
  if (!paper.fitToWidth && rawWidth > contentWidth) {
    warnings.push(`表格实际宽度 ${Math.round(rawWidth)}px，超出可打印宽度 ${Math.round(contentWidth)}px，右侧会被裁切。`);
  }
  const crossPageMerges = [];
  pages.forEach((page, index) => {
    const rows = new Set(page);
    for (const merge of merges) {
      const hasStart = rows.has(merge.startRow);
      const hasEnd = rows.has(merge.endRow);
      if (hasStart !== hasEnd) {
        crossPageMerges.push({
          page: index + 1,
          range: `${colName(merge.startColumn)}${merge.startRow + 1}:${colName(merge.endColumn)}${merge.endRow + 1}`,
        });
      }
    }
  });
  if (crossPageMerges.length > 0) {
    warnings.push(`${crossPageMerges.length} 处纵向合并被分页切断，需要调整版式或纸张。`);
  }
  const bindingByRange = {};
  for (const binding of bindings || []) bindingByRange[binding.range] = binding;

  const generatedAt = new Date().toLocaleString("zh-CN", { hour12: false });
  const templateName = String(meta?.templateName || "维护台账");
  const recordCode = String(meta?.recordCode || "");
  const css = pageCss(pageWidth, pageHeight, margins, previewZoom);
  const pageHtml = pages.map((pageRows, index) => {
    const table = buildTable({
      snapshot, sheet, pageRows, merges, bindingByRange, values, scale, maxCol,
    });
    const caption = index > 0
      ? `<div class="ledger-caption"><span>${esc(templateName)}</span><span class="record-code">${esc(recordCode)}</span></div>`
      : "";
    return `
      <section class="page-sheet" data-page="${index + 1}"><div class="page-inner">
        ${caption}
        ${table.html}
        <div class="page-spacer"></div>
        <div class="page-foot">
          <span>制表：${esc(templateName)}</span>
          <span>第 ${index + 1} 页 / 共 ${pages.length} 页 · ${esc(generatedAt)}</span>
        </div>
      </div></section>`;
  }).join("");

  return {
    html: `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>${esc(recordCode || templateName || "维护台账打印预览")}</title><style>${css}</style></head><body><main class="pages">${pageHtml}</main></body></html>`,
    pageCount: pages.length,
    scale,
    warnings,
    rawWidth,
    contentWidth,
    crossPageMerges,
  };
}
