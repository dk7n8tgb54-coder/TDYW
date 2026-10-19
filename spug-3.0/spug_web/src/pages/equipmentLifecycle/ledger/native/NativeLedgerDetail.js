/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * 原生路线维护台账详情（iframe 编辑器壳 + 工具栏，2026-10-18）。
 *
 * 版式回放与填写在 iframe 编辑器内（创建时固定的发布版本快照，只读底表
 * + 绑定单元格输入层）；草稿可填写，历史状态只读。动作集合见
 * useNativeLedgerHandlers（保存/完成/更正/作废/删除/导出），工具栏见
 * NativeLedgerToolbar；编辑器加载失败给重试入口（EditorIframePane）。
 *
 * onBack：返回回调；正式台账页传入关闭详情并刷新列表的逻辑。
 */
import React, {useEffect, useRef} from 'react';
import {observer} from 'mobx-react';
import {Button, Card, DatePicker, Descriptions, Space, Table, Tag} from 'antd';
import moment from 'moment';

import {useEditorChannel} from './bridge';
import EditorIframePane from './EditorIframePane';
import NativeLedgerToolbar from './NativeLedgerToolbar';
import useNativeLedgerHandlers from './useNativeLedgerHandlers';
import {LEDGER_TYPE_TEXT, STATUS_TEXT, STATUS_COLOR} from '../constants';

/** 表头信息（状态/类型/期次/执行日期/完成时间/录入人/模板/版本）。 */
const DetailDescriptions = observer(function DetailDescriptions({store, editable, correcting}) {
  const detail = store.detail;
  const version = store.version;
  const dateEditable = editable || correcting;
  const dateValue = store.dateDraft === undefined
    ? (detail.executed_date ? moment(String(detail.executed_date).slice(0, 10)) : null)
    : (store.dateDraft === '' ? null : moment(store.dateDraft));
  const handleSaveDate = () => {
    const raw = store.dateDraft !== undefined
      ? store.dateDraft
      : (detail.executed_date ? String(detail.executed_date).slice(0, 10) : '');
    // 执行日期草稿经保存动作统一提交（与填写值一次 PUT）
    store.setDateDraft(raw);
    store.saveValues(null, null).catch(() => {});
  };
  return (
    <Descriptions size="small" bordered column={4} style={{marginBottom: 12}}>
      <Descriptions.Item label="状态">
        <Tag color={STATUS_COLOR[detail.status] || 'default'}>
          {STATUS_TEXT[detail.status] || detail.status}
        </Tag>
      </Descriptions.Item>
      <Descriptions.Item label="类型">
        {LEDGER_TYPE_TEXT[detail.ledger_type] || detail.ledger_type}
      </Descriptions.Item>
      <Descriptions.Item label="计划期次">{detail.maintenance_period || '—'}</Descriptions.Item>
      <Descriptions.Item label="实际执行日期">
        {dateEditable ? (
          <Space size={4}>
            <DatePicker
              data-testid="native-executed-date"
              size="small" style={{width: 130}} placeholder="执行后录入"
              value={dateValue}
              onChange={value => store.setDateDraft(value ? value.format('YYYY-MM-DD') : '')}/>
            {editable && (
              <Button data-testid="native-save-executed-date" size="small"
                      disabled={store.submitting} loading={store.saving}
                      onClick={handleSaveDate}>保存</Button>
            )}
          </Space>
        ) : (
          detail.executed_date ? String(detail.executed_date).slice(0, 10) : '—'
        )}
      </Descriptions.Item>
      <Descriptions.Item label="完成时间">
        {detail.completed_at ? String(detail.completed_at).slice(0, 19).replace('T', ' ') : '—'}
      </Descriptions.Item>
      <Descriptions.Item label="录入人">{detail.created_by_name || '—'}</Descriptions.Item>
      <Descriptions.Item label="录入时间">
        {detail.created_at ? String(detail.created_at).slice(0, 19).replace('T', ' ') : '—'}
      </Descriptions.Item>
      <Descriptions.Item label="原生模板">
        {version ? version.template_name : '—'}
      </Descriptions.Item>
      <Descriptions.Item label="版本">{version ? `v${version.version_no}` : '—'}</Descriptions.Item>
    </Descriptions>
  );
});

function NativeLedgerDetail({store, onBack}) {
  const iframeRef = useRef(null);
  const channel = useEditorChannel(iframeRef, {
    onValues: payload => store.applyEditorValues(payload),
  });
  const detail = store.detail;
  const correctingEditable = store.correctingEditable;
  const handlers = useNativeLedgerHandlers(store, channel, onBack);

  // 编辑器就绪（含重挂载）后注入初始化数据；更正模式切换（可写/只读，
  // iframe 随 key 重挂载并重新 READY）时也会重新注入
  useEffect(() => {
    if (!channel.readySeq || !detail) return;
    const version = store.version;
    if (!version) return;
    channel.sendInit({
      mode: 'fill',
      version: {
        snapshot: version.snapshot,
        bindings: version.bindings || [],
        paper: version.paper,
      },
      values: correctingEditable ? store.values : store.savedValues,
      meta: {
        ledgerNo: detail.ledger_no,
        templateName: version.template_name,
        versionNo: version.version_no,
        executedDate: detail.executed_date
          ? String(detail.executed_date).slice(0, 10) : '',
        statusText: STATUS_TEXT[detail.status] || detail.status,
        editable: correctingEditable,
      },
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channel.readySeq, detail && detail.id, correctingEditable, store.correcting]);

  if (!detail) return null;
  const corrections = detail.corrections || [];
  return (
    <Card bordered={false}
          title={`原生台账：${detail.ledger_no}`}
          extra={<NativeLedgerToolbar detail={detail} store={store} handlers={handlers}/>}>
      <DetailDescriptions store={store} editable={store.editable}
                          correcting={store.correcting}/>
      {corrections.length > 0 && (
        <Table
          data-testid="native-corrections"
          rowKey="id" size="small" pagination={false}
          style={{marginBottom: 12}}
          columns={[
            {title: '更正时间', dataIndex: 'corrected_at', width: 160},
            {title: '更正人', dataIndex: 'corrected_by_name', width: 100},
            {title: '更正原因', dataIndex: 'reason', ellipsis: true},
            {
              title: '变更内容', key: 'changes',
              render: (t, r) => (r.changes || []).map((c, i) => (
                <div key={i}>{c.label}: {String(c.old === undefined ? '' : c.old)} → {String(c.new)}</div>
              )),
            },
          ]}
          dataSource={corrections}/>
      )}
      {store.correcting && (
        <div style={{color: '#fa8c16', marginBottom: 8}} data-testid="native-correct-banner">
          更正模式：在编辑器中修改后点击「提交更正」，变更前后值与更正原因将记入更正记录。
        </div>
      )}
      <EditorIframePane
        iframeRef={iframeRef}
        ready={channel.ready}
        loadFailed={channel.loadFailed}
        retry={channel.retry}
        reloadToken={channel.reloadToken}
        height="calc(100vh - 320px)"
        testId="native-ledger-iframe"
        errorText="编辑器加载失败（静态资源未就绪），请刷新重试或联系管理员检查部署。"/>
      {store.editable && !store.correcting && (
        <div style={{color: '#999', marginTop: 8}}>
          仅绑定单元格可填写；"完成填写"会先保存未保存的填写值与实际执行日期并校验必填项，
          完成后流程结束。
        </div>
      )}
    </Card>
  );
}

export default observer(NativeLedgerDetail);
