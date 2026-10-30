/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 草稿状态共享文案（draft-status 接口数据源的展示映射）：
 * 逐份文件"草稿 vs 当前生效版本"关系、修订进行中状态 与 整套待发布变化
 * 摘要的文案与颜色。关系与修订状态均由服务端计算（快照哈希/名称/序位/
 * revision_open 显式状态），前端只做文案映射，不得以修订号或文件名推断
 * 内容是否变化。
 *
 * 状态语义（2026-10-30 修订轮改造）：
 * - revision_open（修订进行中）是显式持久状态：发布成功才对发布清单内
 *   文件关闭；它与"内容是否变化"（哈希比对）独立——修订开启但内容未变
 *   不是待发布变化，内容已变也不是"已生效"。
 * - 工作副本（草稿）发布后仍保留，但不再以"未发布草稿"名义展示；
 *   已生效且无未发布修改时显示「已生效」。
 */

export const DRAFT_RELATION_LABELS = {
  unchanged: '与生效版本一致',
  modified: '已修改未发布',
  added: '新增（未进入生效版本）',
  awaiting_first_publish: '等待首次发布',
  no_draft: '缺草稿',
  unconfirmed: '暂不能确认',
};

export const DRAFT_RELATION_COLORS = {
  unchanged: 'green',
  modified: 'orange',
  added: 'blue',
  awaiting_first_publish: 'gold',
  no_draft: 'red',
  unconfirmed: 'volcano',
};

/**
 * 逐份文件的日常状态（文件清单「状态」列的唯一渲染依据）。
 * 合并 服务端内容关系（relation）+ 修订进行中（file.revision_open）+
 * 编辑占用，输出一行一个可懂的短语；信息细节（修订号/基于版本/关系
 * 原文）放草稿工作台详情与变更记录。
 *
 * 返回 {label, color, tip}；relation 为 null（未加载/失败）时返回 null，
 * 调用方渲染占位「—」，绝不渲染"一致/无变化"语义。
 */
export function buildFileState(file, relation) {
  if (!file) return null;
  const revisionOpen = !!file.revision_open;
  if (!file.draft) {
    const hint = file.draft_recovery;
    if (hint && hint.source === 'current_version') {
      return {label: '草稿未就绪', color: 'orange',
        tip: `可从当前生效版本 v${hint.version_no} 恢复草稿`};
    }
    return {label: '草稿未就绪', color: 'orange',
      tip: hint && hint.note ? hint.note : '该文件还没有可编辑草稿'};
  }
  if (!relation) return null;
  if (relation.status === 'unconfirmed') {
    const session = relation.session || {};
    if (session.is_mine) {
      return {label: '我的编辑进行中', color: 'orange',
        tip: relation.unconfirmed_message || '编辑会话进行中（含未完成同步）'};
    }
    if (session.user_name) {
      return {label: `${session.user_name} 编辑中`, color: 'orange',
        tip: relation.unconfirmed_message || '编辑会话进行中（含未完成同步）'};
    }
    return {label: '暂不能确认', color: 'volcano',
      tip: relation.unconfirmed_message || '该文件状态暂不能确认'};
  }
  if (relation.status === 'awaiting_first_publish') {
    return {label: '待首次发布', color: 'gold', tip: '尚无生效版本'};
  }
  if (relation.status === 'added') {
    return {label: '新增待发布', color: 'blue', tip: '尚未进入生效版本'};
  }
  if (relation.status === 'modified') {
    return revisionOpen
      ? {label: '修订中 · 有未发布修改', color: 'orange',
        tip: '草稿内容与生效版本不同，发布后生效'}
      : {label: '有未发布修改', color: 'orange',
        tip: '草稿内容与生效版本不同，发布后生效'};
  }
  // relation.status === 'unchanged'
  if (revisionOpen) {
    return {label: '修订进行中', color: 'orange',
      tip: '已开启修订，暂无内容变化；修改内容后可发布'};
  }
  return {label: '已生效', color: 'green',
    tip: '与生效版本一致，无未发布修改'};
}

/**
 * 整套待发布变化摘要文案（如 "2 份文件有未发布修改、1 份新增文件"）。
 * 覆盖 内容修改/新增/移除/改名/顺序调整 与 缺草稿 异常；没有可罗列的
 * 变化时返回 null（是否"一致"由调用方按 summary.consistent 判断，
 * 存在 unconfirmed 时绝不显示"一致"）。
 */
export function buildDraftChangeSummaryText(summary) {
  if (!summary) return null;
  const parts = [];
  if (summary.modified) parts.push(`${summary.modified} 份文件有未发布修改`);
  if (summary.added) parts.push(`${summary.added} 份新增文件`);
  if (summary.removed) parts.push(`${summary.removed} 份文件被移除`);
  if (summary.renamed) parts.push(`${summary.renamed} 份文件已改名`);
  if (summary.reordered) parts.push('文件顺序已调整');
  if (summary.no_draft) parts.push(`${summary.no_draft} 份缺草稿`);
  return parts.length ? parts.join('、') : null;
}
