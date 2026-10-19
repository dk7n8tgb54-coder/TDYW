/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
/**
 * 运行处置记录详情——单页分区锚点与定位滚动（2026-10-18 页签改分区）。
 * 原"基本信息/进展/附件"三页签改为单页连续分区后，原进展页签定位入口
 * （主列表与系统档案"进展数"列）改为按区块锚点滚动定位：详情内容加载
 * 完成后由 RecordDetail.componentDidUpdate 触发，不使用固定延时。
 */

// 进展时间线区块锚点（原 progress 页签定位目标的落点）
export const PROGRESS_SECTION_ID = 'op-record-progress-section';

// 附件区块锚点（原 attachments 页签定位目标的落点）
export const ATTACHMENT_SECTION_ID = 'op-record-attachment-section';

// 附件折叠面板 ID（区块标题按钮 aria-controls 指向，可访问性关联）
export const ATTACHMENT_PANEL_ID = 'op-record-attachment-panel';

// 把详情弹窗内容区滚动到指定区块顶部（8px 呼吸间距）。
// 区块节点或弹窗内容区不存在（如失败态未渲染正文）时返回 false、不滚动；
// 手动计算 scrollTop 而不用 scrollIntoView，避免连带滚动弹窗背后的页面
export function scrollToSection(sectionId) {
  const node = document.getElementById(sectionId);
  if (!node) return false;
  const body = node.closest('.ant-modal-body');
  if (!body) return false;
  const delta = node.getBoundingClientRect().top
    - body.getBoundingClientRect().top;
  body.scrollTop += delta - 8;
  return true;
}
