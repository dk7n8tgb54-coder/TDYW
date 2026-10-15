/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * "导出本模板台账"确认框（2026-10-11）：
 * 点击组内批量导出按钮后，store 先向后端取确认数据（模板名称/匹配记录数/
 * 实际日期范围/状态范围/涉及模板版本），本组件只做展示与确认；确认后以
 * 相同筛选发起 POST 导出，由后端重新查询并逐条生成、依序合并为一份 PDF。
 * 预计页数依赖逐条 LibreOffice 转换，无可靠估算口径，不予展示。默认状态
 * 范围（已提交及后续有效状态，不含草稿/已作废）由后端下发，前端仅做文本
 * 映射；无匹配记录或超过单次上限时禁用"导出 PDF"并给出明确提示。
 */
import React from 'react';
import {observer} from 'mobx-react';
import {Alert, Descriptions, Modal} from 'antd';
import {STATUS_TEXT} from './constants';

const LedgerBatchExportModal = observer(function LedgerBatchExportModal({store}) {
  const preview = store.batchExportPreview;
  const visible = !!preview;
  const total = preview ? preview.total : 0;
  const maxRecords = preview ? preview.max_records : 0;
  const overLimit = visible && maxRecords > 0 && total > maxRecords;
  const statusText = visible
    ? (preview.status_scope || []).map(code => STATUS_TEXT[code] || code).join('、') || '—'
    : '';
  const versionText = visible
    ? (preview.versions || []).map(v => `v${v.version_no}（${v.count} 条）`).join('、') || '—'
    : '';
  const dateText = visible && preview.executed_from
    ? `${preview.executed_from} ~ ${preview.executed_to}`
    : '—';
  const handleOk = () => {
    store.closeBatchExport();
    store.exportBatchPdf();
  };
  return (
    <Modal
      title="导出本模板台账"
      visible={visible}
      okText="导出 PDF"
      cancelText="取消"
      okButtonProps={{disabled: !visible || total === 0 || overLimit}}
      onOk={handleOk}
      onCancel={store.closeBatchExport}
      destroyOnClose>
      {visible && total === 0 && (
        <Alert
          type="warning"
          showIcon
          message="当前筛选条件下没有符合条件的台账"
          description="请调整组内筛选条件（状态/编号/日期范围）后重试。"
          style={{marginBottom: 12}}/>
      )}
      {visible && overLimit && (
        <Alert
          type="warning"
          showIcon
          message={`匹配台账共 ${total} 条，超过单次导出上限 ${maxRecords} 条`}
          description="请缩小日期范围或增加筛选条件后重试。"
          style={{marginBottom: 12}}/>
      )}
      {visible && (
        <Descriptions column={1} size="small" bordered>
          <Descriptions.Item label="模板名称">{preview.template_name}</Descriptions.Item>
          <Descriptions.Item label="匹配记录数">{total} 条</Descriptions.Item>
          <Descriptions.Item label="日期范围">{dateText}</Descriptions.Item>
          <Descriptions.Item label="状态范围">{statusText}</Descriptions.Item>
          <Descriptions.Item label="涉及模板版本">{versionText}</Descriptions.Item>
        </Descriptions>
      )}
      {visible && total > 0 && !overLimit && (
        <p style={{margin: '12px 0 0', color: '#888'}}>
          各台账将按创建时的模板版本与打印参数生成 PDF，按实际执行日期与台账编号排序后依序合并为一份文件。
        </p>
      )}
    </Modal>
  );
});

export default LedgerBatchExportModal;
