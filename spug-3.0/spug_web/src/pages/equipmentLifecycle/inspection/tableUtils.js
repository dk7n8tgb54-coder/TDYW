/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 巡检列式表格布局助手（今日巡检工作台 / 巡检单记录详情共用）：
 * 一行 = 检查项目（设备名称快照）× 检查内容，四轮取值横向展开；
 * 同一检查项目的连续行在第一列合并单元格（rowSpan）。
 */

/**
 * 输入条目需带 project 字段，输出按原顺序逐项标注：
 * - isGroupStart：该行是否为当前检查项目的第一行（渲染第一列单元格）；
 * - span：从该行起连续同项目的行数（作为 rowSpan）。
 */
export function withProjectSpans(items) {
  return items.map((item, idx) => {
    const isGroupStart = idx === 0 || items[idx - 1].project !== item.project;
    let span = 1;
    if (isGroupStart) {
      while (idx + span < items.length && items[idx + span].project === item.project) span += 1;
    }
    return {item, isGroupStart, span};
  });
}

/**
 * 判断某轮次草稿是否有已填写内容（value_text / onsite_action 任一非空），
 * 用于轮次表头"有草稿"提示与该列浅色底（未记录轮次不因空白列而染色）。
 */
export function roundHasDraft(roundValues) {
  return Object.values(roundValues || {}).some(
    v => !!v && !!((v.value_text && String(v.value_text).trim()) ||
      (v.onsite_action && String(v.onsite_action).trim())));
}
