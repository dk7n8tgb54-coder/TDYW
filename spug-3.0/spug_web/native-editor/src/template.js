/**
 * 模板数据工具（正式编辑器）：纸张预设、空白底表种子、绑定工具。
 * 与样板（quality/prototypes/native_ledger/src/template.js）的协议一致，
 * 但不含样板示例数据：新建模板由本模块生成空白底表，版式由用户在
 * Univer 编辑器中绘制；快照协议由后端 native_template_services 校验。
 */

export const SHEET_ID = "ledger";

export const PAPER_PRESETS = {
  A4: { width: 210, height: 297, label: "A4 (210 × 297 mm)" },
  A3: { width: 297, height: 420, label: "A3 (297 × 420 mm)" },
};

export const DEFAULT_PAPER = {
  size: "A4",
  orientation: "landscape",
  fitToWidth: true,
  margins: { top: 12, right: 10, bottom: 12, left: 10 },
};

export const BINDING_TYPES = [
  { value: "text", label: "文本" },
  { value: "number", label: "数值" },
  { value: "date", label: "日期" },
  { value: "status", label: "正常/不正常" },
  { value: "textarea", label: "多行文本" },
];

/** 新建模板的空白底表：42 行 × 14 列默认网格，无预置内容。 */
export function buildBlankSnapshot() {
  return {
    id: `native-ledger-${Date.now()}`,
    name: "维护台账",
    appVersion: "1.1.0",
    locale: "zhCN",
    styles: {},
    sheetOrder: [SHEET_ID],
    sheets: {
      [SHEET_ID]: {
        id: SHEET_ID,
        name: "维护台账",
        hidden: 0,
        freeze: { xSplit: 0, ySplit: 0, startRow: 0, startColumn: 0 },
        rowCount: 42,
        columnCount: 14,
        zoomRatio: 0.8,
        scrollTop: 0,
        scrollLeft: 0,
        defaultColumnWidth: 88,
        defaultRowHeight: 32,
        mergeData: [],
        cellData: {},
        rowData: {},
        columnData: {},
        rowHeader: { width: 42 },
        columnHeader: { height: 22 },
        showGridlines: 0,
        rightToLeft: 0,
      },
    },
  };
}

/** 新模板草稿（快照 + 空绑定 + 默认纸张）。 */
export function buildNewDraft() {
  return {
    snapshot: buildBlankSnapshot(),
    bindings: [],
    paper: structuredClone(DEFAULT_PAPER),
  };
}

export function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

/** 空白填写值骨架（绑定 key → 空串）。 */
export function buildEmptyValues(bindings) {
  return Object.fromEntries(bindings.map((binding) => [binding.key, ""]));
}

/** A1 引用解析为 0 起行列（"D5" → {row:4, col:3}）；非法返回 null。 */
export function parseRange(range) {
  const match = /^([A-Z]{1,3})([1-9][0-9]*)$/.exec(String(range || "").toUpperCase());
  if (!match) return null;
  let col = 0;
  for (const ch of match[1]) col = col * 26 + (ch.charCodeAt(0) - 64);
  return { row: parseInt(match[2], 10) - 1, col: col - 1 };
}

/** 0 起列索引 → 列字母（批量绑定与打印层共用）。 */
export function colName(index) {
  let value = index + 1;
  let text = "";
  while (value > 0) {
    const remainder = (value - 1) % 26;
    text = String.fromCharCode(65 + remainder) + text;
    value = Math.floor((value - 1) / 26);
  }
  return text;
}

/** 规范化纸张（对齐后端 validate_paper 缺省兜底）。 */
export function normalizePaper(paper) {
  const merged = clone(DEFAULT_PAPER);
  if (!paper || typeof paper !== "object") return merged;
  if (PAPER_PRESETS[paper.size]) merged.size = paper.size;
  if (paper.orientation === "portrait" || paper.orientation === "landscape") {
    merged.orientation = paper.orientation;
  }
  if (typeof paper.fitToWidth === "boolean") merged.fitToWidth = paper.fitToWidth;
  if (paper.margins && typeof paper.margins === "object") {
    for (const side of ["top", "right", "bottom", "left"]) {
      const value = Number(paper.margins[side]);
      if (Number.isFinite(value) && value >= 4 && value <= 40) {
        merged.margins[side] = value;
      }
    }
  }
  return merged;
}
