/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 保存确认失败语境（finishingErrorKind）的标题与重试文案映射，
 * 供工作台文件头部 Alert 与放大态精简顶栏（ExpandedBar）共用：
 * - ''（缺省）：保存并结束编辑 / 离开保护失败 → 重试保存；
 * - 'switch_local'：切换到本机编辑被取消（确认失败或旧编辑实例回调
 *   尚未在服务端失效）→ 重试切换；
 * - 'download_draft'：下载草稿被取消（在线编辑期间下载先确认落盘）→
 *   重试下载。
 * 重试动作的分发在工作台（handleFinishingRetry），此处只映射文案。
 */

export function finishingErrorTitleOf(kind) {
  if (kind === 'switch_local') return '切换未完成，会话已保留';
  if (kind === 'download_draft') return '下载未完成，会话已保留';
  return '保存未确认，会话已保留';
}

export function finishingRetryLabelOf(kind) {
  if (kind === 'switch_local') return '重试切换';
  if (kind === 'download_draft') return '重试下载';
  return '重试保存';
}
