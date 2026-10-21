/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * "批量导出 PDF"弹窗（2026-10-21，替换原"导出明细 CSV"入口）：
 * 周月维护 / 季维护两个列表的"按维护周期"与"按模板查看"视图共用，
 * 按模板多选导出。打开时 store 拉取模板候选清单（本租户、当前台账类型，
 * 含已停用但有历史台账的模板；手工补录无模板版式不在清单）。
 *
 * 交互：模板支持按名称/ID 搜索、全选当前搜索结果与多选，明确显示已选
 * 数量；状态范围默认"已完成"（不含草稿/已作废），可显式放宽；预览区
 * 实时给出所选模板的可导出数量、涉及版本与状态范围（纯前端按候选数据
 * 计算，与实际导出共用同一口径，导出时后端重查并复核数量一致性）。
 * 所选范围下无可导出记录或超过单次上限时禁用导出并明确提示。
 *
 * 导出规则（与后端 ledger_template_group_services.export_templates_pdfs
 * 一致）：按模板 ID 组织，每个模板一份 PDF（各台账按维护期次从早到晚
 * 排列，未标注期次的按创建顺序排在最后），多模板打包 ZIP；不继承列表
 * 的日期/周期筛选，也不按当前分页截取。
 *
 * 结构：主体只做布局与装配；预览明细（SelectedPreview）与提示告警
 * （ExportAlerts）拆为独立展示组件（门禁函数行数约束）。
 */
import React, {useState} from 'react';
import {observer} from 'mobx-react';
import {Alert, Button, Input, Modal, Select, Table, Tag, Tooltip} from 'antd';
import {exportableCountOf, EXPORT_STATUS_OPTIONS, versionsUnderScope} from './constants';

const STATUS_SCOPE_TEXT = {
  '': '已完成（不含草稿/已作废）',
  all: '全部（含草稿、已作废）',
  draft: '草稿',
  void: '已作废',
};

function TemplateNameCell({template}) {
  return (
    <div>
      <span>{template.template_name}</span>
      {!template.is_active && (
        <Tooltip title="模板已停用（不能用于新建），历史台账仍可导出">
          <Tag style={{marginLeft: 6}}>已停用</Tag>
        </Tooltip>
      )}
      {/* 模板 ID 常驻展示：名称相同的模板以 ID 区分 */}
      <div style={{color: '#999', fontSize: 12}}>ID: {template.template_id}</div>
    </div>
  );
}

function VersionText({template, status}) {
  const versions = versionsUnderScope(template, status);
  if (!versions.length) return <span>—</span>;
  return <span>{versions.map(v => `v${v.version_no}（${v.count} 条）`).join('、')}</span>;
}

/** 预览明细：所选模板逐行的数量/涉及版本（与实际导出同口径的展示）。 */
function SelectedPreview({perTemplate, status, total}) {
  return (
    <div style={{
      marginTop: 8, padding: '8px 12px', background: '#fafafa',
      border: '1px solid #eee', borderRadius: 4}}>
      <div style={{marginBottom: 4}}>
        共 <b>{total}</b> 条台账（状态范围：{STATUS_SCOPE_TEXT[status] || status}）
      </div>
      {perTemplate.map(item => (
        <div key={item.template.template_id} style={{fontSize: 12, color: '#666'}}>
          {item.template.template_name}（ID: {item.template.template_id}）：{item.count} 条；
          涉及版本 <VersionText template={item.template} status={status}/>
          {item.count === 0 && ' —— 在所选状态范围内没有可导出的台账'}
        </div>
      ))}
    </div>
  );
}

/** 状态提示：未选择 / 无可导出 / 超限（导出按钮在这些情况下禁用）。 */
function ExportAlerts({selectedCount, total, emptySelected, overLimit, maxRecords}) {
  return (
    <React.Fragment>
      {selectedCount === 0 && (
        <Alert
          style={{marginTop: 8}}
          type="info"
          showIcon
          message="请先勾选要导出的模板"
          description="默认导出所选模板的全部已完成台账；如需包含草稿或已作废台账，请调整导出状态范围。"/>
      )}
      {emptySelected.map(item => (
        <Alert
          key={item.template.template_id}
          style={{marginTop: 8}}
          type="warning"
          showIcon
          message={`模板「${item.template.template_name}」在所选状态范围内没有可导出的台账`}
          description="请取消勾选该模板，或将导出状态范围调整为包含其台账（如“全部”）。"/>
      ))}
      {selectedCount > 0 && total === 0 && emptySelected.length === 0 && (
        <Alert
          style={{marginTop: 8}}
          type="warning"
          showIcon
          message="所选模板没有可导出的台账"
          description="请调整导出状态范围后重试。"/>
      )}
      {overLimit && (
        <Alert
          style={{marginTop: 8}}
          type="warning"
          showIcon
          message={`所选模板可导出台账共 ${total} 条，超过单次导出上限 ${maxRecords} 条`}
          description="请减少模板或缩小状态范围后重试。"/>
      )}
    </React.Fragment>
  );
}

/** 工具栏：状态范围 / 搜索 / 全选搜索结果 / 清空 / 已选数量常显。 */
function ExportToolbar({store, status, keyword, setKeyword, selectableIds}) {
  const selectedIds = store.multiExportSelected;
  return (
    <div style={{marginBottom: 8, display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center'}}>
      <span>导出状态范围：</span>
      <Select
        style={{width: 280}}
        value={status}
        onChange={v => store.setMultiExportStatus(v)}
        data-testid="multi-export-status">
        {EXPORT_STATUS_OPTIONS.map(opt => (
          <Select.Option value={opt.value} key={opt.value}>{opt.label}</Select.Option>
        ))}
      </Select>
      <Input.Search
        allowClear
        style={{width: 200}}
        placeholder="搜索模板名称或 ID"
        value={keyword}
        onChange={e => setKeyword(e.target.value)}
        data-testid="multi-export-search"/>
      <Button
        data-testid="multi-export-select-all"
        disabled={!selectableIds.length}
        onClick={() => store.setMultiExportSelected(
          Array.from(new Set([...selectedIds, ...selectableIds])))}>
        全选搜索结果
      </Button>
      <Button
        data-testid="multi-export-clear"
        disabled={!selectedIds.length}
        onClick={() => store.setMultiExportSelected([])}>
        清空选择
      </Button>
      {/* 已选数量常显（含 0），明确当前选择状态 */}
      <span data-testid="multi-export-selected-count">
        已选择 <b>{selectedIds.length}</b> 个模板
      </span>
    </div>
  );
}

const LedgerMultiExportModal = observer(function LedgerMultiExportModal({store}) {
  const visible = store.multiExportVisible;
  const payload = store.multiExportTemplates;
  const templates = (payload && payload.templates) || [];
  const maxRecords = payload ? payload.max_records : 0;
  const status = store.multiExportStatus;
  const [keyword, setKeyword] = useState('');
  const text = keyword.trim().toLowerCase();
  const filtered = text
    ? templates.filter(t => t.template_name.toLowerCase().includes(text)
      || String(t.template_id).includes(text))
    : templates;
  const selectedIds = store.multiExportSelected;
  const selectedTemplates = templates.filter(t => selectedIds.includes(t.template_id));
  const perTemplate = selectedTemplates.map(template => ({
    template,
    count: exportableCountOf(template, status),
  }));
  const total = perTemplate.reduce((sum, item) => sum + item.count, 0);
  const emptySelected = perTemplate.filter(item => item.count === 0);
  const overLimit = maxRecords > 0 && total > maxRecords;
  // 无可导出记录（整体为 0 或个别所选模板为 0）与超限时禁用导出并明确提示
  const canExport = selectedIds.length > 0 && total > 0
    && emptySelected.length === 0 && !overLimit;

  // selectedRowKeys 必须与 rowKey（template_id，数字）同类型：antd conductCheck
  // 会丢弃不匹配 keyEntities 的键（字符串 '7' 会把已选行整个丢掉）
  const rowSelection = {
    selectedRowKeys: selectedIds,
    onChange: keys => store.setMultiExportSelected(keys.map(Number)),
    getCheckboxProps: record => ({
      disabled: exportableCountOf(record, status) === 0,
    }),
  };
  const selectableFilteredIds = filtered
    .filter(t => exportableCountOf(t, status) > 0)
    .map(t => t.template_id);

  const handleOk = () => {
    store.closeMultiExport();
    store.exportMultiPdf();
  };

  return (
    <Modal
      title="按模板批量导出 PDF"
      visible={visible}
      width={760}
      okText="导出 PDF"
      cancelText="取消"
      okButtonProps={{disabled: !canExport, loading: store.isMultiExporting}}
      onOk={handleOk}
      onCancel={store.closeMultiExport}
      destroyOnClose>
      {visible && (
        <React.Fragment>
          <p style={{margin: '0 0 8px', color: '#888'}}>
            导出范围由本弹窗选择的模板与状态决定，不继承列表的日期/周期筛选，也不按当前分页截取。
            手工补录台账没有模板版式，不在导出范围。
          </p>
          <ExportToolbar
            store={store} status={status}
            keyword={keyword} setKeyword={setKeyword}
            selectableIds={selectableFilteredIds}/>
          <Table
            rowKey="template_id"
            size="small"
            loading={store.isMultiExportFetching}
            dataSource={filtered}
            rowSelection={rowSelection}
            pagination={{pageSize: 8, showSizeChanger: false, hideOnSinglePage: true}}
            locale={{emptyText: '暂无可导出的模板台账（模板需已有台账记录）'}}
            columns={[
              {title: '模板名称', dataIndex: 'template_name', render: (_, template) =>
                <TemplateNameCell template={template}/>},
              {title: '可导出台账数量', dataIndex: 'count', width: 120, render: (_, template) =>
                exportableCountOf(template, status)},
            ]}/>
          {selectedIds.length > 0 && (
            <SelectedPreview
              perTemplate={perTemplate} status={status} total={total}/>
          )}
          <ExportAlerts
            selectedCount={selectedIds.length} total={total}
            emptySelected={emptySelected} overLimit={overLimit}
            maxRecords={maxRecords}/>
          {canExport && (
            <p style={{margin: '12px 0 0', color: '#888'}}>
              每个模板生成一份 PDF，模板内台账按维护期次从早到晚排列
              （未标注期次的按创建顺序排在最后）；选择多个模板时打包为 ZIP 下载。
            </p>
          )}
        </React.Fragment>
      )}
    </Modal>
  );
});

export default LedgerMultiExportModal;
