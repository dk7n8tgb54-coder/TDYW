/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * 原生台账详情工具栏（按状态与模式显隐，2026-10-16 流程简化，与 Excel 详情一致）：
 * - 草稿：保存草稿 + 完成填写 + 删除（草稿直接删除重填）；
 * - 已完成：更正（进入更正模式）+ 作废 + 导出（不可删除）；
 * - 更正模式中：提交更正 + 取消更正；
 * - 已作废：仅查看 + 导出。
 */
import React from 'react';
import {Button, Popconfirm, Space} from 'antd';
import {
  ArrowLeftOutlined, CheckCircleOutlined, FilePdfOutlined, SaveOutlined,
} from '@ant-design/icons';

const DELETABLE_STATUS = ['draft'];

export default function NativeLedgerToolbar({detail, store, handlers}) {
  const isVoid = detail.status === 'void';
  const canDelete = DELETABLE_STATUS.includes(detail.status);
  const editable = store.editable;
  return (
    <Space wrap>
      <Button data-testid="native-detail-back" icon={<ArrowLeftOutlined/>}
              onClick={handlers.handleBack}>返回列表</Button>
      {store.correcting && (
        <Button data-testid="native-cancel-correct" disabled={store.saving}
                onClick={() => store.cancelCorrection()}>取消更正</Button>
      )}
      {store.correcting && (
        <Button data-testid="native-submit-correct" type="primary"
                loading={store.saving} onClick={handlers.handleSubmitCorrect}>
          提交更正
        </Button>
      )}
      {editable && !store.correcting && (
        <Button data-testid="native-save" icon={<SaveOutlined/>}
                loading={store.saving} disabled={store.submitting}
                onClick={handlers.handleSave}>保存草稿</Button>
      )}
      {editable && !store.correcting && (
        <Button data-testid="native-complete" type="primary"
                icon={<CheckCircleOutlined/>} loading={store.submitting}
                disabled={store.saving} onClick={handlers.handleComplete}>
          完成填写
        </Button>
      )}
      {detail.status === 'completed' && !store.correcting && (
        <Button data-testid="native-correct" type="primary"
                onClick={handlers.handleStartCorrect}>更正</Button>
      )}
      {!isVoid && detail.status !== 'draft' && !store.correcting && (
        <Popconfirm title="作废后不可恢复，确认作废？"
                    onConfirm={handlers.handleVoid} okText="作废" cancelText="取消">
          <Button danger>作废</Button>
        </Popconfirm>
      )}
      {canDelete && !store.correcting && (
        <Popconfirm
          title="删除后台账及其填写内容将从列表与导出中移除且不可恢复，确认删除？"
          onConfirm={handlers.handleDelete} okText="删除" cancelText="取消">
          <Button data-testid="native-delete" danger>删除</Button>
        </Popconfirm>
      )}
      <Button data-testid="native-export-pdf" icon={<FilePdfOutlined/>}
              onClick={handlers.handleExportPdf}>导出 PDF</Button>
    </Space>
  );
}
