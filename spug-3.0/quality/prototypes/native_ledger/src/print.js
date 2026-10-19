import { PAPER_PRESETS } from "./template";

const MM_TO_PX = 96 / 25.4;
const PRINT_BREAK_BEFORE = 17;
const HEADER_ROWS = [0, 1, 2, 3];
const FIRST_ROW = 0;
const LAST_ROW = 26;

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function color(value) {
  if (!value) return "transparent";
  if (typeof value === "string") return value;
  return value.rgb || "transparent";
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
  return Number(sheet.rowData?.[row]?.h ?? sheet.defaultRowHeight ?? 32);
}

function colWidth(sheet, col) {
  return Number(sheet.columnData?.[col]?.w ?? sheet.defaultColumnWidth ?? 88);
}

function cellValue(snapshot, sheet, row, col, bindings, values) {
  const binding = bindings.find((item) => item.range === `${colName(col)}${row + 1}`);
  if (binding && Object.prototype.hasOwnProperty.call(values, binding.key)) {
    return values[binding.key];
  }
  return sheet.cellData?.[row]?.[col]?.v ?? "";
}

function cellStyle(snapshot, sheet, row, col) {
  const styleRef = sheet.cellData?.[row]?.[col]?.s;
  if (!styleRef) return {};
  const style = typeof styleRef === "string" ? snapshot.styles?.[styleRef] : styleRef;
  return style || {};
}

function isStyle(snapshot, sheet, row, col, name) {
  const ref = sheet.cellData?.[row]?.[col]?.s;
  return ref === name;
}

function inlineStyle(snapshot, sheet, row, col, scaledFont) {
  const style = cellStyle(snapshot, sheet, row, col);
  const fs = Number(style.fs || 9) * 1.3333 * scaledFont;
  const pieces = [
    `font-size:${fs.toFixed(2)}px`,
    `font-family:${esc(style.ff || "Microsoft YaHei")}, "Noto Sans CJK SC", "SimSun", sans-serif`,
    `color:${esc(color(style.cl) === "transparent" ? "#111827" : color(style.cl))}`,
    `background:${esc(color(style.bg))}`,
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
  if (isStyle(snapshot, sheet, row, col, "title")) pieces.push("border:none");
  if (isStyle(snapshot, sheet, row, col, "note")) pieces.push("border-left:none", "border-right:none", "border-bottom:none");
  return pieces.join(";");
}

function findMerges(sheet) {
  return (sheet.mergeData || []).map((merge) => ({
    startRow: merge.startRow,
    startColumn: merge.startColumn,
    endRow: merge.endRow,
    endColumn: merge.endColumn,
  }));
}

function mergeFor(merges, row, col) {
  return merges.find(
    (merge) => row >= merge.startRow && row <= merge.endRow && col >= merge.startColumn && col <= merge.endColumn,
  );
}

function crossingMerge(merges, breakRow) {
  return merges.find((merge) => merge.startRow < breakRow && merge.endRow >= breakRow);
}

function paginate(sheet, contentHeightPx, scale) {
  const groups = [
    { start: FIRST_ROW, end: PRINT_BREAK_BEFORE - 1, header: [] },
    { start: PRINT_BREAK_BEFORE, end: LAST_ROW, header: [] },
  ];
  const pages = [];
  const warnings = [];
  const merges = findMerges(sheet);
  const footerHeight = 22;
  for (const group of groups) {
    let cursor = group.start;
    let headerRows = group.header;
    let first = true;
    while (cursor <= group.end) {
      const rowList = [...headerRows];
      for (let r = cursor; r <= group.end; r += 1) rowList.push(r);
      const heightOf = (rows) => rows.reduce((sum, r) => sum + rowHeight(sheet, r) * scale, 0);
      const available = contentHeightPx - footerHeight;
      let pageRows = [...rowList];
      if (heightOf(pageRows) > available && !first) {
        pageRows = [...headerRows];
      }
      if (heightOf(pageRows) > available) {
        const bodyRows = [];
        let used = heightOf(headerRows);
        let r = cursor;
        while (r <= group.end) {
          const nextHeight = rowHeight(sheet, r) * scale;
          if (used + nextHeight > available && bodyRows.length > 0) break;
          bodyRows.push(r);
          used += nextHeight;
          r += 1;
        }
        pageRows = [...headerRows, ...bodyRows];
        if (r <= group.end) {
          const crossing = crossingMerge(merges, r);
          if (crossing && crossing.startRow >= cursor) {
            const adjusted = [...headerRows];
            for (let rr = cursor; rr < crossing.startRow; rr += 1) adjusted.push(rr);
            pageRows = adjusted;
            r = crossing.startRow;
          }
          warnings.push(`第 ${pages.length + 1} 页按行分页，分页点避开纵向合并区域。`);
        }
        cursor = r;
      } else {
        cursor = group.end + 1;
      }
      const body = pageRows.filter((r) => !headerRows.includes(r));
      const allRows = [...headerRows, ...body];
      pages.push({ rows: allRows, headerRows, bodyRows: body, height: heightOf(allRows) });
      first = false;
      if (!body.length) break;
    }
  }
  return { pages, warnings, merges };
}

function buildTable({ snapshot, sheet, page, merges, bindings, values, scale }) {
  const columnCount = 14;
  const widths = Array.from({ length: columnCount }, (_, c) => colWidth(sheet, c) * scale);
  const totalWidth = widths.reduce((sum, w) => sum + w, 0);
  const covered = new Set();
  for (const merge of merges) {
    if (!page.rows.includes(merge.startRow) || !page.rows.includes(merge.endRow)) continue;
    for (let r = merge.startRow; r <= merge.endRow; r += 1) {
      for (let c = merge.startColumn; c <= merge.endColumn; c += 1) {
        if (r !== merge.startRow || c !== merge.startColumn) covered.add(`${r}:${c}`);
      }
    }
  }

  const colGroup = widths.map((w) => `<col style="width:${w.toFixed(2)}px">`).join("");
  const rowsHtml = page.rows.map((r) => {
    const cells = [];
    for (let c = 0; c < columnCount; c += 1) {
      if (covered.has(`${r}:${c}`)) continue;
      const merge = merges.find(
        (item) => item.startRow === r && item.startColumn === c && page.rows.includes(item.endRow),
      );
      const rowSpan = merge && page.rows.includes(merge.endRow) ? merge.endRow - merge.startRow + 1 : 1;
      const colSpan = merge ? merge.endColumn - merge.startColumn + 1 : 1;
      const value = cellValue(snapshot, sheet, r, c, bindings, values);
      const text = value === null || value === undefined || value === "" ? "&nbsp;" : esc(value);
      const address = `${colName(c)}${r + 1}`;
      const style = inlineStyle(snapshot, sheet, r, c, scale);
      const classNames = ["cell"];
      const styleRef = sheet.cellData?.[r]?.[c]?.s;
      if (typeof styleRef === "string") classNames.push(`st-${styleRef}`);
      cells.push(
        `<td class="${classNames.join(" ")}" data-cell="${address}" rowspan="${rowSpan}" colspan="${colSpan}" style="${style}">${text}</td>`,
      );
    }
    return `<tr style="height:${(rowHeight(sheet, r) * scale).toFixed(2)}px">${cells.join("")}</tr>`;
  }).join("");

  return {
    html: `<table class="ledger-table" style="width:${totalWidth.toFixed(2)}px"><colgroup>${colGroup}</colgroup><tbody>${rowsHtml}</tbody></table>`,
    totalWidth,
  };
}

export function renderPrintDocument({
  snapshot,
  bindings,
  values,
  paper,
  record,
  templateName,
  previewZoom = 1,
}) {
  const sheet = getSheet(snapshot);
  const dims = PAPER_PRESETS[paper.size] || PAPER_PRESETS.A4;
  const pageWidth = paper.orientation === "landscape" ? dims.height : dims.width;
  const pageHeight = paper.orientation === "landscape" ? dims.width : dims.height;
  const margins = paper.margins;
  const contentWidth = (pageWidth - margins.left - margins.right) * MM_TO_PX;
  const contentHeight = (pageHeight - margins.top - margins.bottom) * MM_TO_PX;
  const rawWidth = Array.from({ length: 14 }, (_, c) => colWidth(sheet, c)).reduce((a, b) => a + b, 0);
  const scale = paper.fitToWidth ? Math.min(1, contentWidth / rawWidth) : 1;
  const { pages, warnings, merges } = paginate(sheet, contentHeight, scale);
  const generatedAt = new Date().toLocaleString("zh-CN", { hour12: false });
  const warningsAll = [...warnings];
  if (scale < 0.7) {
    warningsAll.push(`当前纸张下自动缩放为 ${(scale * 100).toFixed(0)}%，已低于 70% 的可读性参考线。`);
  }
  if (!paper.fitToWidth && rawWidth > contentWidth) {
    warningsAll.push(`表格实际宽度 ${Math.round(rawWidth)}px，超出可打印宽度 ${Math.round(contentWidth)}px，右侧会被裁切。`);
  }

  const crossPageMerges = [];
  pages.forEach((page, index) => {
    const rows = new Set(page.rows);
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
    warningsAll.push(`${crossPageMerges.length} 处纵向合并被分页切断，需要调整分页点。`);
  }

  const pageHtml = pages.map((page, index) => {
    const table = buildTable({ snapshot, sheet, page, merges, bindings, values, scale });
    return `
      <section class="page-sheet" data-page="${index + 1}" style="width:${pageWidth}mm;height:${pageHeight}mm;padding:${margins.top}mm ${margins.right}mm ${margins.bottom}mm ${margins.left}mm">
        <div class="page-inner">
          <div class="ledger-caption">${esc(templateName)} <span class="record-code">${esc(record?.code || "未保存草稿")}</span></div>
          ${table.html}
          <div class="page-spacer"></div>
          <div class="page-foot">
            <span>制表：原生维护台账样板 · 脱敏示例</span>
            <span>第 ${index + 1} 页 / 共 ${pages.length} 页 · ${esc(generatedAt)}</span>
          </div>
        </div>
      </section>`;
  }).join("");

  const css = `
    @page { size: ${pageWidth}mm ${pageHeight}mm; margin: 0; }
    * { box-sizing: border-box; }
    html, body { margin: 0; padding: 0; background: #e5e7eb; }
    body { font-family: "Microsoft YaHei", "Noto Sans CJK SC", "SimSun", sans-serif; color: #111827; }
    .pages { display: flex; flex-direction: column; align-items: center; gap: 12mm; padding: 8mm 0; }
    .page-sheet { position: relative; background: #fff; overflow: hidden; break-after: page; page-break-after: always; }
    .page-sheet:last-child { break-after: auto; page-break-after: auto; }
    .page-inner { width: 100%; height: 100%; display: flex; flex-direction: column; }
    .ledger-caption { display: none; justify-content: space-between; align-items: baseline; gap: 8px; margin: 0 0 2mm; color: #334155; font-size: 8pt; font-weight: 600; }
    .page-sheet:not([data-page="1"]) .ledger-caption { display: flex; }
    .record-code { color: #1d4ed8; font-size: 8pt; }
    .page-sheet:not([data-page="1"]) .ledger-table { margin-top: 0; }
    .ledger-table { border-collapse: collapse; table-layout: fixed; margin: 0 auto; }
    .ledger-table td { border: 0.5px solid #64748b; padding: 2px 3px; overflow: hidden; }
    .ledger-table td.st-title { border: none; }
    .ledger-table td.st-note { border-left: none; border-right: none; border-bottom: none; }
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

  return {
    html: `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>${esc(record?.code || "维护台账打印预览")}</title><style>${css}</style></head><body><main class="pages">${pageHtml}</main></body></html>`,
    pageCount: pages.length,
    scale,
    warnings: warningsAll,
    rawWidth,
    contentWidth,
    crossPageMerges,
  };
}

export { PRINT_BREAK_BEFORE };
