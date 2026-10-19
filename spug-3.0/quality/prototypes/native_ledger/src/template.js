const SHEET_ID = "ledger";
const COLUMN_WIDTHS = [44, 152, 88, 78, 78, 88, 82, 78, 88, 84, 84, 84, 84, 196];
const ROW_HEIGHTS = [
  54, 36, 34, 52,
  38, 44, 38, 46, 40, 42, 38, 44, 40, 38, 46, 40,
  44, 34, 32, 40, 40, 40, 32, 38, 38, 88, 28,
];

const CHANNELS = [
  {
    site: "东区中继站",
    channel: "CH-01",
    links: [
      { link: "主用", tx: "43.2", swr: "1.18", ber: "1.4E-6", rx: "-72.4", snr: "31.8", rxBer: "8.0E-7", mode: "主用", ppb: "12", clock: "锁定", verdict: "合格", note: "巡检正常，接头无氧化" },
      { link: "备用", tx: "42.7", swr: "1.21", ber: "2.0E-6", rx: "-74.1", snr: "30.6", rxBer: "1.2E-6", mode: "热备", ppb: "18", clock: "锁定", verdict: "合格", note: "主备切换测试通过" },
    ],
  },
  {
    site: "北区中继站",
    channel: "CH-07",
    links: [
      { link: "主用", tx: "42.9", swr: "1.24", ber: "1.8E-6", rx: "-73.2", snr: "30.9", rxBer: "9.0E-7", mode: "主用", ppb: "15", clock: "锁定", verdict: "合格", note: "指标平稳" },
      { link: "备用", tx: "41.8", swr: "1.58", ber: "3.6E-6", rx: "-75.8", snr: "28.7", rxBer: "2.4E-6", mode: "热备", ppb: "26", clock: "锁定", verdict: "复测合格", note: "更换馈线跳线后复测" },
    ],
  },
  {
    site: "西区微波站",
    channel: "CH-12",
    links: [
      { link: "主用", tx: "43.6", swr: "1.15", ber: "1.1E-4", rx: "-71.5", snr: "32.4", rxBer: "7.0E-7", mode: "主用", ppb: "9", clock: "锁定", verdict: "复测合格", note: "清洁光模块并更换尾纤" },
      { link: "备用", tx: "42.4", swr: "1.27", ber: "2.2E-6", rx: "-74.6", snr: "29.8", rxBer: "1.5E-6", mode: "热备", ppb: "21", clock: "锁定", verdict: "合格", note: "备用链路正常" },
    ],
  },
  {
    site: "中心站",
    channel: "CH-03",
    links: [
      { link: "主用", tx: "43.9", swr: "1.12", ber: "9.0E-7", rx: "-70.8", snr: "33.1", rxBer: "6.0E-7", mode: "主用", ppb: "7", clock: "锁定", verdict: "合格", note: "核心链路，重点巡检" },
      { link: "备用", tx: "43.1", swr: "1.19", ber: "1.3E-6", rx: "-72.9", snr: "31.2", rxBer: "8.0E-7", mode: "热备", ppb: "11", clock: "锁定", verdict: "合格", note: "倒换正常" },
    ],
  },
  {
    site: "南郊中继站",
    channel: "CH-09",
    links: [
      { link: "主用", tx: "42.5", swr: "1.29", ber: "2.8E-6", rx: "-74.8", snr: "29.4", rxBer: "1.8E-6", mode: "主用", ppb: "23", clock: "锁定", verdict: "合格", note: "室外单元防水检查" },
      { link: "备用", tx: "42.2", swr: "1.31", ber: "3.1E-6", rx: "-75.2", snr: "28.9", rxBer: "2.1E-6", mode: "热备", ppb: "25", clock: "锁定", verdict: "合格", note: "接地电阻复测合格" },
    ],
  },
  {
    site: "应急通信车",
    channel: "CH-21",
    links: [
      { link: "主用", tx: "41.9", swr: "1.36", ber: "4.0E-6", rx: "-76.1", snr: "27.8", rxBer: "2.8E-6", mode: "主用", ppb: "31", clock: "保持", verdict: "观察", note: "车内温度偏高，已加强散热" },
      { link: "备用", tx: "41.5", swr: "1.41", ber: "4.6E-6", rx: "-77.0", snr: "27.1", rxBer: "3.2E-6", mode: "冷备", ppb: "35", clock: "保持", verdict: "观察", note: "列入下次维护重点" },
    ],
  },
];

const B = (color = "#94a3b8") => ({ s: 1, cl: { rgb: color } });
const BORDER = { t: B(), r: B(), b: B(), l: B() };

const STYLES = {
  base: { ff: "Microsoft YaHei", fs: 9, cl: { rgb: "#1f2937" }, vt: 2, ht: 2, tb: 3, bd: BORDER },
  title: { ff: "Microsoft YaHei", fs: 17, bl: 1, cl: { rgb: "#103a5c" }, vt: 2, ht: 2, tb: 3 },
  meta: { ff: "Microsoft YaHei", fs: 8.5, cl: { rgb: "#475569" }, vt: 2, ht: 1, tb: 3, bd: BORDER },
  group: { ff: "Microsoft YaHei", fs: 9.5, bl: 1, bg: { rgb: "#dbeafe" }, cl: { rgb: "#123a5c" }, vt: 2, ht: 2, tb: 3, bd: BORDER },
  sub: { ff: "Microsoft YaHei", fs: 8, bl: 1, bg: { rgb: "#eff6ff" }, cl: { rgb: "#1e3a5f" }, vt: 2, ht: 2, tb: 3, bd: BORDER },
  cell: { ff: "Microsoft YaHei", fs: 8.5, cl: { rgb: "#111827" }, vt: 2, ht: 2, tb: 3, bd: BORDER },
  left: { ff: "Microsoft YaHei", fs: 8.5, cl: { rgb: "#111827" }, vt: 2, ht: 1, tb: 3, bd: BORDER },
  note: { ff: "Microsoft YaHei", fs: 7.5, cl: { rgb: "#334155" }, vt: 2, ht: 1, tb: 3, bd: BORDER },
  total: { ff: "Microsoft YaHei", fs: 9, bl: 1, bg: { rgb: "#f1f5f9" }, cl: { rgb: "#0f2f4f" }, vt: 2, ht: 2, tb: 3, bd: BORDER },
  section: { ff: "Microsoft YaHei", fs: 10, bl: 1, bg: { rgb: "#dbeafe" }, cl: { rgb: "#103a5c" }, vt: 2, ht: 1, tb: 3, bd: BORDER },
  name: { ff: "Microsoft YaHei", fs: 11, bl: 1, cl: { rgb: "#111827" }, vt: 2, ht: 1, tb: 3, bd: BORDER },
  hint: { ff: "Microsoft YaHei", fs: 7.5, cl: { rgb: "#64748b" }, vt: 2, ht: 1, tb: 3 },
};

function createCellData() {
  const cellData = {};
  const mergeData = [];
  const set = (row, col, value, style = "cell") => {
    if (!cellData[row]) cellData[row] = {};
    cellData[row][col] = { v: value, s: style };
  };

  set(0, 0, "通信信道维护台账（2026 年第三季度）", "title");
  mergeData.push({ startRow: 0, startColumn: 0, endRow: 0, endColumn: 13 });

  const meta = [
    [0, 2, "单位：直属通信中心（脱敏示例）"],
    [3, 5, "台账编号：TX-2026-Q3-001"],
    [6, 8, "维护日期：2026-09-18"],
    [9, 11, "环境：晴 22℃ / 湿度 46%"],
    [12, 13, "模板版本：v1"],
  ];
  for (const [start, end, text] of meta) {
    set(1, start, text, "meta");
    if (end > start) mergeData.push({ startRow: 1, startColumn: start, endRow: 1, endColumn: end });
  }

  const groupHeader = [
    [0, 0, "序号"], [1, 1, "站点 / 信道"], [2, 2, "链路"],
    [3, 5, "上行（站点 → 中心）"], [6, 8, "下行（中心 → 站点）"],
    [9, 9, "主备"], [10, 11, "时钟同步"], [12, 12, "判定"], [13, 13, "备注"],
  ];
  for (const [start, end, text] of groupHeader) {
    set(2, start, text, "group");
    if (end > start) mergeData.push({ startRow: 2, startColumn: start, endRow: 2, endColumn: end });
  }
  for (const [col, text] of [[0, "序号"], [1, "站点 / 信道"], [2, "链路"], [9, "主备"], [12, "判定"], [13, "备注"]]) {
    set(3, col, text, "sub");
    mergeData.push({ startRow: 2, startColumn: col, endRow: 3, endColumn: col });
  }
  for (const [col, text] of [
    [3, "发射功率\n(dBm)"], [4, "驻波比"], [5, "误码率"],
    [6, "接收电平\n(dBm)"], [7, "信噪比\n(dB)"], [8, "误码率"],
    [10, "偏差\n(ppb)"], [11, "状态"],
  ]) {
    set(3, col, text, "sub");
  }

  let row = 4;
  for (let i = 0; i < CHANNELS.length; i += 1) {
    const group = CHANNELS[i];
    const start = row;
    for (const link of group.links) {
      set(row, 0, start === row ? i + 1 : null, "cell");
      set(row, 1, start === row ? `${group.site}\n${group.channel}` : null, "left");
      set(row, 2, link.link, "cell");
      set(row, 3, link.tx, "cell");
      set(row, 4, link.swr, "cell");
      set(row, 5, link.ber, "cell");
      set(row, 6, link.rx, "cell");
      set(row, 7, link.snr, "cell");
      set(row, 8, link.rxBer, "cell");
      set(row, 9, link.mode, "cell");
      set(row, 10, link.ppb, "cell");
      set(row, 11, link.clock, "cell");
      set(row, 12, link.verdict, "cell");
      set(row, 13, start === row ? link.note : null, "note");
      row += 1;
    }
    mergeData.push({ startRow: start, startColumn: 0, endRow: row - 1, endColumn: 0 });
    mergeData.push({ startRow: start, startColumn: 1, endRow: row - 1, endColumn: 1 });
    mergeData.push({ startRow: start, startColumn: 13, endRow: row - 1, endColumn: 13 });
  }

  set(16, 0, "合计 / 总体判定", "total");
  mergeData.push({ startRow: 16, startColumn: 0, endRow: 16, endColumn: 2 });
  set(16, 3, "合格 10 项 / 观察 2 项", "total");
  mergeData.push({ startRow: 16, startColumn: 3, endRow: 16, endColumn: 5 });
  set(16, 6, "复测通过 2 项", "total");
  mergeData.push({ startRow: 16, startColumn: 6, endRow: 16, endColumn: 8 });
  set(16, 9, "维护结论：链路指标整体正常；CH-07 备用链路驻波比偏高，已更换跳线并复测；应急通信车列入下次维护重点。", "left");
  mergeData.push({ startRow: 16, startColumn: 9, endRow: 16, endColumn: 13 });

  set(17, 0, "二、异常处理、备件更换与签字确认", "section");
  mergeData.push({ startRow: 17, startColumn: 0, endRow: 17, endColumn: 13 });
  for (const [start, end, text] of [[0, 2, "异常描述"], [3, 6, "处置过程"], [7, 9, "备件"], [10, 13, "复测结果"]]) {
    set(18, start, text, "group");
    mergeData.push({ startRow: 18, startColumn: start, endRow: 18, endColumn: end });
  }
  const blocks = [
    [0, 2, "CH-07 备用链路驻波比 1.58，超出 1.50 限值；CH-12 主用上行误码率短时升高。"],
    [3, 6, "更换 CH-07 室外 SMA 跳线 1 根并重新紧固；清洁 CH-12 光模块端面、更换尾纤后复测。"],
    [7, 9, "SMA 跳线 ×1\nLC-LC 尾纤 ×1"],
    [10, 13, "复测：CH-07 驻波比 1.21；CH-12 误码率 1.1E-6，均恢复至限值内。"],
  ];
  for (const [start, end, text] of blocks) {
    set(19, start, text, "left");
    mergeData.push({ startRow: 19, startColumn: start, endRow: 21, endColumn: end });
  }
  for (const [start, end, text] of [[0, 2, "备件名称"], [3, 5, "型号 / 编号"], [6, 8, "数量"], [9, 13, "更换原因"]]) {
    set(22, start, text, "group");
    mergeData.push({ startRow: 22, startColumn: start, endRow: 22, endColumn: end });
  }
  const parts = [
    ["SMA 跳线", "SMA-NM-5M / SP-0921", "1 根", "CH-07 备用链路驻波比超标"],
    ["LC-LC 尾纤", "LC-LC-3M / FB-1107", "1 根", "CH-12 主用链路误码率升高"],
  ];
  parts.forEach((part, index) => {
    const r = 23 + index;
    set(r, 0, part[0], "left");
    mergeData.push({ startRow: r, startColumn: 0, endRow: r, endColumn: 2 });
    set(r, 3, part[1], "left");
    mergeData.push({ startRow: r, startColumn: 3, endRow: r, endColumn: 5 });
    set(r, 6, part[2], "cell");
    mergeData.push({ startRow: r, startColumn: 6, endRow: r, endColumn: 8 });
    set(r, 9, part[3], "left");
    mergeData.push({ startRow: r, startColumn: 9, endRow: r, endColumn: 13 });
  });

  set(25, 0, "维护人员（签字）", "name");
  mergeData.push({ startRow: 25, startColumn: 0, endRow: 25, endColumn: 2 });
  set(25, 3, "张工（示例）", "name");
  mergeData.push({ startRow: 25, startColumn: 3, endRow: 25, endColumn: 10 });
  set(25, 11, "日期：2026-09-18", "meta");
  mergeData.push({ startRow: 25, startColumn: 11, endRow: 25, endColumn: 13 });

  set(26, 0, "说明：本样板使用脱敏示例数据，仅用于评估原生维护台账的制作、填写和打印效果，不代表真实台站记录。", "note");
  mergeData.push({ startRow: 26, startColumn: 0, endRow: 26, endColumn: 13 });

  return { cellData, mergeData };
}

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

export function buildWorkbookSnapshot(title = "通信信道维护台账（2026 年第三季度）") {
  const { cellData, mergeData } = createCellData();
  cellData[0][0].v = title;
  return {
    id: `native-ledger-${Date.now()}`,
    name: "通信信道维护台账",
    appVersion: "1.1.0",
    locale: "zhCN",
    styles: STYLES,
    sheetOrder: [SHEET_ID],
    sheets: {
      [SHEET_ID]: {
        id: SHEET_ID,
        name: "信道维护台账",
        tabColor: "#1d4ed8",
        hidden: 0,
        freeze: { xSplit: 0, ySplit: 4, startRow: 4, startColumn: 0 },
        rowCount: 40,
        columnCount: 14,
        zoomRatio: 0.75,
        scrollTop: 0,
        scrollLeft: 0,
        defaultColumnWidth: 88,
        defaultRowHeight: 32,
        mergeData,
        cellData,
        rowData: Object.fromEntries(ROW_HEIGHTS.map((h, i) => [i, { h }])),
        columnData: Object.fromEntries(COLUMN_WIDTHS.map((w, i) => [i, { w }])),
        rowHeader: { width: 42 },
        columnHeader: { height: 22 },
        showGridlines: 0,
        rightToLeft: 0,
      },
    },
  };
}

function makeBindings() {
  const bindings = [];
  const add = (key, label, section, range, type, placeholder = "") => {
    bindings.push({ id: `bind-${key}`, key, label, section, range, type, placeholder });
  };
  for (let i = 0; i < CHANNELS.length; i += 1) {
    const group = CHANNELS[i];
    for (let j = 0; j < group.links.length; j += 1) {
      const r = 5 + i * 2 + j;
      const link = group.links[j];
      add(`tx_${i}_${j}`, `上行发射功率 · ${group.channel} ${link.link}`, "上行指标", `D${r}`, "number", "dBm");
      add(`rx_${i}_${j}`, `下行接收电平 · ${group.channel} ${link.link}`, "下行指标", `G${r}`, "number", "dBm");
    }
  }
  add("overall", "总体维护结论", "结论与签字", "J17", "text", "填写总体结论");
  add("total_ok", "合格项统计", "结论与签字", "D17", "text", "例如：合格 10 项");
  add("total_issue", "观察/异常项统计", "结论与签字", "G17", "text", "例如：观察 2 项");
  add("finding_desc", "异常描述", "异常处理", "A20", "textarea", "描述发现的异常");
  add("finding_action", "处置过程", "异常处理", "D20", "textarea", "描述处置过程");
  add("part_name", "备件名称 / 数量", "异常处理", "H20", "textarea", "备件与数量");
  add("retest_result", "复测结果", "异常处理", "K20", "textarea", "复测数据与结论");
  add("inspector_name", "维护人员姓名", "签字确认", "D26", "text", "请填写姓名");
  add("inspect_date", "维护日期", "签字确认", "L26", "date", "YYYY-MM-DD");
  return bindings;
}

function sampleRecordValues() {
  const values = {};
  for (let i = 0; i < CHANNELS.length; i += 1) {
    for (let j = 0; j < 2; j += 1) {
      const link = CHANNELS[i].links[j];
      values[`tx_${i}_${j}`] = link.tx;
      values[`rx_${i}_${j}`] = link.rx;
    }
  }
  values.overall = "链路指标整体正常；CH-07 备用链路驻波比偏高，已更换跳线并复测；应急通信车列入下次维护重点。";
  values.total_ok = "合格 10 项";
  values.total_issue = "观察 2 项";
  values.finding_desc = "CH-07 备用链路驻波比 1.58，超出 1.50 限值；CH-12 主用上行误码率短时升高。";
  values.finding_action = "更换 CH-07 室外 SMA 跳线 1 根并重新紧固；清洁 CH-12 光模块端面、更换尾纤后复测。";
  values.part_name = "SMA 跳线 ×1 / LC-LC 尾纤 ×1";
  values.retest_result = "CH-07 驻波比 1.21；CH-12 误码率 1.1E-6，均恢复至限值内。";
  values.inspector_name = "张工";
  values.inspect_date = "2026-09-18";
  return values;
}

export function createSeedWorkspace() {
  const now = new Date().toISOString();
  const snapshot = buildWorkbookSnapshot();
  const bindings = makeBindings();
  const version = {
    id: "ver-v1",
    label: "v1",
    note: "初始示例版本",
    createdAt: now,
    snapshot,
    bindings,
    paper: structuredClone(DEFAULT_PAPER),
  };
  return {
    schema: 1,
    template: {
      id: "tpl-native-ledger",
      name: "通信信道维护台账（原生样板）",
      currentVersionId: "ver-v1",
      draft: { snapshot, bindings, paper: structuredClone(DEFAULT_PAPER), updatedAt: now },
      versions: [version],
    },
    records: [
      {
        id: "rec-demo-001",
        code: "TX-2026-Q3-001",
        title: "东区及周边信道季度维护",
        versionId: "ver-v1",
        values: sampleRecordValues(),
        status: "已填写",
        updatedAt: now,
      },
    ],
  };
}

export function getLatestVersion(workspace) {
  const { versions, currentVersionId } = workspace.template;
  return versions.find((item) => item.id === currentVersionId) || versions[versions.length - 1];
}

export { CHANNELS, COLUMN_WIDTHS, ROW_HEIGHTS };
