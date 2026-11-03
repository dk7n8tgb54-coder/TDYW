/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 提交待发布核对固定快照的公共读取口径（2026-11-03 固定快照交接改造）。
 *
 * 唯一契约见 `.tmp/institution-handoff-spec.md` 第 2/3/4 节。本模块只做
 * "读服务端下发字段"的纯函数映射，供三个真实调用场景共用：
 * 1) `compilationStatusShared.buildCompilationState`（编制状态文案）；
 * 2) 详情页文件清单 FileListTab（负责人列/冻结行/快照预览下载/撤回/退回）；
 * 3) 草稿工作台 draft/index + draft/FileNav（冻结提示、快照动作、负责人展示）；
 * 4) 发布确认窗 PublishButton（逐份发布来源与提交状态文案）。
 *
 * 语义边界（最重要）：
 * - **前端不推断**提交有效性：`submission.status` 是服务端下发的提交记录
 *   状态（pending/withdrawn/returned/published），`frozen` 表示该文件当前
 *   被固定快照冻结（不可再编辑内容/改结构/再次提交）。旧 payload（仅
 *   `state`=none/submitted/stale）只做安全降级映射，绝不自行比较修订号
 *   宣告"提交有效"——除 `submissionIsStale` 的兜底判据外不再推断。
 * - `legacy_submitted=true` 表示该文件只有旧流程（无副本）的提交记录：
 *   旧记录**不可用于发布**，必须按新规则重新提交待发布核对。
 * - 有效负责人唯一口径：`assignment.effective_owner_id`（后端
 *   `services.effective_owner`：文件负责人 > 手册所有者默认 > 未分配）；
 *   `owner_assigned=false` 表示负责人回退到手册所有者（默认），前端只在
 *   `effective_owner_id` 为空时显示「未分配」。
 * - 快照文件名/提交人/提交时间优先取 `submission.snapshot`（快照落库的
 *   原始文件名），其次接口响应（preview-url/download 返回），最后才退到
 *   草稿文件名——绝不把当前草稿冒充快照。
 */
import { formatDateTime } from './utils';

export const SUBMISSION_STATUS = {
  PENDING: 'pending',
  WITHDRAWN: 'withdrawn',
  RETURNED: 'returned',
  PUBLISHED: 'published',
  NONE: 'none',
};

/** 文件行上的提交信息（缺失=该文件没有提交域数据，安全降级为 null） */
export function submissionOf(file) {
  return (file && file.submission) || null;
}

/**
 * 提交记录状态（服务端字段优先；兼容 2026-11-02 旧 payload 的 state 三态）。
 * 旧 `state='stale'` 仍返回 pending，有效性由 submissionIsStale 判定。
 */
export function submissionStatusOf(submission) {
  if (!submission) return SUBMISSION_STATUS.NONE;
  if (submission.status) return submission.status;
  if (submission.state === 'submitted' || submission.state === 'stale') {
    return SUBMISSION_STATUS.PENDING;
  }
  return SUBMISSION_STATUS.NONE;
}

/**
 * 提交是否已失效（草稿在提交后又被保存/重建）。
 * 优先采信服务端 `state='stale'`；旧 payload 或服务端只下发 status 时，
 * 以"提交时修订号 != 当前草稿修订号"兜底（此为服务端同一判据的镜像，
 * 只用于展示"提交已失效"，绝不据此宣告"提交有效"）。
 */
export function submissionIsStale(file) {
  const submission = submissionOf(file);
  if (!submission) return false;
  if (submission.state === 'stale') return true;
  if (submissionStatusOf(submission) !== SUBMISSION_STATUS.PENDING) return false;
  const draftRevision = file && file.draft ? file.draft.revision : null;
  const submittedRevision = submission.submission_revision != null
    ? submission.submission_revision : submission.draft_revision;
  if (draftRevision == null || submittedRevision == null) return false;
  return submittedRevision !== draftRevision;
}

/** 该文件当前是否被提交固定快照冻结（内容/结构/二次提交均禁止） */
export function isFrozenSubmission(file) {
  const submission = submissionOf(file);
  return !!(submission && submission.frozen);
}

/** 有效负责人 id（文件的负责人 > 手册所有者默认 > null=未分配） */
export function effectiveOwnerIdOf(file) {
  const assignment = (file && file.assignment) || {};
  return assignment.effective_owner_id != null
    ? assignment.effective_owner_id : assignment.owner_id;
}

/** 有效负责人显示名（空则空串，绝不伪造"未分配"以外的名字） */
export function effectiveOwnerNameOf(file) {
  const assignment = (file && file.assignment) || {};
  if (assignment.effective_owner_name) return assignment.effective_owner_name;
  const ownerId = effectiveOwnerIdOf(file);
  if (!ownerId) return '';
  return assignment.owner_name || '该文件负责人';
}

/** 负责人是否回退到手册所有者（默认负责人，owner_assigned=false） */
export function ownerIsDefaultAssignment(file) {
  const assignment = (file && file.assignment) || {};
  return assignment.owner_assigned === false;
}

/**
 * 当前账号是否为该文件有效负责人（唯一依据：服务端 is_effective_owner；
 * 旧 payload 无该字段时回退 assignment.is_mine 保持旧语义）。
 */
export function isEffectiveOwnerOf(file) {
  const assignment = (file && file.assignment) || {};
  if (assignment.is_effective_owner !== undefined &&
    assignment.is_effective_owner !== null) {
    return !!assignment.is_effective_owner;
  }
  return !!assignment.is_mine;
}

/** 提交快照的显示文件名（snapshot 优先；绝不用当前草稿冒充快照） */
export function submissionSnapshotFileName(file) {
  const submission = submissionOf(file);
  const snapshot = (submission && submission.snapshot) || {};
  if (snapshot.file_name) return snapshot.file_name;
  if (file && file.draft && file.draft.file_name) return file.draft.file_name;
  return (file && file.name) || '';
}

/** 提交人展示名（接口响应优先，其次快照提交人） */
export function submissionSubmittedBy(file, data) {
  const submission = submissionOf(file) || {};
  return (data && data.submitted_by_name) || submission.submitted_by_name || '-';
}

/** 提交时间展示（接口响应优先，其次快照提交时间） */
export function submissionSubmittedAt(file, data) {
  const submission = submissionOf(file) || {};
  return formatDateTime((data && data.submitted_at) || submission.submitted_at);
}

/**
 * 待核对快照预览标题（唯一实现）：
 * 「预览待核对快照：<文件名>（提交人 X，提交时间 Y）」
 */
export function buildSubmissionPreviewTitle(file, data) {
  const name = (data && data.file_name) || submissionSnapshotFileName(file);
  return `预览待核对快照：${name}（提交人 ${submissionSubmittedBy(file, data)}，` +
    `提交时间 ${submissionSubmittedAt(file, data)}）`;
}

/** 发布权口径（与详情/草稿工作台既有口径一致：手册所有者 或 publish 授权） */
export function hasPublishRight(manual) {
  if (!manual) return false;
  return !!manual.is_owner || (manual.my_roles || []).includes('publish');
}

/**
 * 是否可撤回提交（负责人本人撤回；服务端 can_withdraw 优先）。
 * 撤回后旧快照作废、内容解冻，可重新提交（新行，旧行保留）。
 */
export function canWithdrawSubmission(file) {
  const submission = submissionOf(file);
  if (!submission) return false;
  if (submission.can_withdraw !== undefined) return !!submission.can_withdraw;
  return submissionStatusOf(submission) === SUBMISSION_STATUS.PENDING &&
    !submissionIsStale(file) && isEffectiveOwnerOf(file);
}

/**
 * 是否可退回修改（持发布权且非该文件有效负责人；服务端 can_return 优先）。
 * 退回必须填写原因（≤500），旧快照作废、内容解冻。
 */
export function canReturnSubmission(file, manual) {
  const submission = submissionOf(file);
  if (!submission) return false;
  if (submission.can_return !== undefined) return !!submission.can_return;
  return submissionStatusOf(submission) === SUBMISSION_STATUS.PENDING &&
    !submissionIsStale(file) && hasPublishRight(manual) &&
    !isEffectiveOwnerOf(file);
}
