/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 操作记录展示共享单元：动作文案、详情行解析。
 * 消费方：RecordsTab（手册级时间线）与 FileHistoryModal（按文件过滤），
 * 两个真实调用场景——文案与解析只在此处维护，避免双处漂移。
 */

const ACTION_LABELS = {
  create: '创建手册',
  // upload_original / create_draft 为历史已落库的动作，仅用于渲染旧操作
  // 记录（原稿能力已整体删除，界面不提供任何原稿相关入口）
  upload_original: '上传初始来源',
  create_draft: '创建草稿', restore_draft: '恢复草稿',
  repair_draft: '修复工作副本', save_draft: '保存草稿',
  session_start: '进入编辑',
  session_revoke: '退出编辑', publish: '发布版本', deprecate: '废止版本',
  rollback: '从历史版本回退', password_reset: '重置编辑密码',
  config_change: '调整配置', chapter_update: '章节分工', delete: '删除手册',
  download: '下载文件', file_add: '新增文件', file_assign: '文件分工',
  file_submit: '提交待发布核对', file_rename: '文件改名',
  file_move: '调整顺序', file_remove: '移除文件',
  revision_start: '开始修订',
};

const HIGHLIGHT = new Set([
  'publish', 'deprecate', 'rollback', 'password_reset', 'delete',
]);

export function oplogActionLabel(action) {
  return ACTION_LABELS[action] || action;
}

export function oplogActionHighlight(action) {
  return HIGHLIGHT.has(action);
}

/** 操作详情 JSON -> 一行摘要（解析失败显示 '-'，不抛错） */
export function renderOplogDetail(record) {
  if (!record.detail) return '-';
  try {
    const d = JSON.parse(record.detail);
    const parts = [];
    if (d.revision !== undefined) parts.push(`修订 r${d.revision}`);
    if (d.file_revision !== undefined) parts.push(`修订 r${d.file_revision}`);
    if (d.file_name) parts.push(d.file_name);
    if (d.version_no) parts.push(`v${d.version_no}`);
    if (d.change_note) parts.push(d.change_note);
    if (d.title) parts.push(d.title);
    if (d.progress) parts.push(`进度→${d.progress}`);
    // 文件分工（file_assign）：owner_name='' 表示清空负责人
    if (d.owner_name !== undefined) {
      parts.push(d.owner_name ? `负责人→${d.owner_name}` : '负责人已清空');
    }
    if (d.reason) parts.push(d.reason);
    return parts.join(' · ') || '-';
  } catch (e) {
    return '-';
  }
}
