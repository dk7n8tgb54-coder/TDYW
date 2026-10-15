/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * Excel 路线维护台账详情视图（2026-10 自 ExcelLedgerPage 抽出复用）。
 *
 * 正式周月/季维护台账列表点击 Excel 来源记录时复用本组件；试点页
 * ExcelLedgerPage 委托同一实现。版式回放（LayoutTable 填写模式）——
 * 可编辑状态渲染输入控件，历史状态只读展示当时填写值；保存草稿 /
 * 一键正常（仅填充未填写的正常/异常格，不覆盖已填）/ 提交（必填校验）/
 * 复核 / 作废（沿用既有台账端点）/ 导出 Excel 与 PDF；导出 PDF 先走
 * 预检接口，默认使用版本快照的模板级参数，高级设置弹窗可覆盖（仅本次）。
 *
 * onBack：返回回调；缺省时回到试点页列表（清空详情并刷新），
 * 正式台账页传入自己的返回逻辑（关闭详情并刷新统一列表）。
 */
import React, {useState} from 'react';
import {observer} from 'mobx-react';
import {
  Button, Card, DatePicker, Descriptions, Dropdown, Input, Menu, Modal,
  Popconfirm, Space, Spin, Tag, message,
} from 'antd';
import moment from 'moment';
import {
  ArrowLeftOutlined, FileExcelOutlined, FilePdfOutlined, SettingOutlined,
} from '@ant-design/icons';

import LayoutTable from './components/LayoutTable';
import PdfParamsForm from './PdfParamsForm';
import {normalizePdfParams, serializePdfParams} from './pdfParams';

export const LEDGER_TYPE_TEXT = {week_month: '周月维护', seasonal: '季维护'};
export const STATUS_TEXT = {
  draft: '草稿', submitted: '已提交', returned: '已退回',
  reviewed: '已复核', void: '已作废',
};
export const STATUS_COLOR = {
  draft: 'default', submitted: 'processing', returned: 'warning',
  reviewed: 'success', void: 'error',
};

/** 表头信息（状态/类型/计划期次/执行日期/执行人/模板/版本/源文件/哈希）。
 * 实际执行日期在可编辑状态由填写人录入（周期生成的应填台账生成时留空，
 * 创建时间不冒充执行日期）。 */
function DetailDescriptions({detail, version, editable, saving, onSaveHeader}) {
  const [executedDate, setExecutedDate] = useState(null);
  const handleSaveDate = () => {
    onSaveHeader({executed_date: executedDate ? executedDate.format('YYYY-MM-DD') : ''});
  };
  return (
    <Descriptions size="small" bordered column={4} style={{marginBottom: 12}}>
      <Descriptions.Item label="状态">
        <Tag color={STATUS_COLOR[detail.status]}>{STATUS_TEXT[detail.status] || detail.status}</Tag>
      </Descriptions.Item>
      <Descriptions.Item label="类型">
        {LEDGER_TYPE_TEXT[detail.ledger_type] || detail.ledger_type}
      </Descriptions.Item>
      <Descriptions.Item label="计划期次">
        {detail.maintenance_period || '—'}
      </Descriptions.Item>
      <Descriptions.Item label="实际执行日期">
        {editable ? (
          <Space size={4}>
            <DatePicker
              data-testid="excel-executed-date"
              size="small"
              style={{width: 130}}
              placeholder="执行后录入"
              value={executedDate || (detail.executed_date ? moment(String(detail.executed_date).slice(0, 10)) : null)}
              onChange={value => setExecutedDate(value)}/>
            <Button data-testid="excel-save-executed-date" size="small"
                    loading={saving} onClick={handleSaveDate}>保存</Button>
          </Space>
        ) : (
          detail.executed_date ? String(detail.executed_date).slice(0, 10) : '—'
        )}
      </Descriptions.Item>
      <Descriptions.Item label="执行人">{detail.executor_names || '—'}</Descriptions.Item>
      <Descriptions.Item label="模板">{version ? version.template_name : '—'}</Descriptions.Item>
      <Descriptions.Item label="版本">{version ? `v${version.version_no}` : '—'}</Descriptions.Item>
      <Descriptions.Item label="源文件">{version ? version.source_filename : '—'}</Descriptions.Item>
      <Descriptions.Item label="SHA-256">
        <span style={{fontFamily: 'monospace'}}>
          {version ? `${String(version.source_hash).slice(0, 16)}…` : '—'}
        </span>
      </Descriptions.Item>
    </Descriptions>
  );
}

/** 详情操作栏：返回/一键正常/保存/提交/复核/作废/导出（按状态显隐）。 */
function DetailToolbar({detail, editable, submitting, saving, handlers}) {
  return (
    <Space>
      <Button data-testid="excel-detail-back" icon={<ArrowLeftOutlined/>}
              onClick={handlers.onBack}>返回列表</Button>
      {editable && (
        <Button data-testid="ledger-fill-normal"
                onClick={handlers.onFillNormal}>一键正常</Button>
      )}
      {editable && (
        <Button data-testid="ledger-save" loading={saving}
                onClick={handlers.onSave}>保存填写值</Button>
      )}
      {detail.status === 'draft' && (
        <Button data-testid="ledger-submit" type="primary"
                loading={submitting} onClick={handlers.onSubmit}>
          提交
        </Button>
      )}
      {detail.status === 'submitted' && (
        <Button data-testid="ledger-review" type="primary" onClick={handlers.onReview}>
          复核
        </Button>
      )}
      {detail.status !== 'void' && (
        <Popconfirm title="作废后不可恢复，确认作废？" onConfirm={handlers.onVoid}
                    okText="作废" cancelText="取消">
          <Button danger>作废</Button>
        </Popconfirm>
      )}
      <Button data-testid="ledger-export-excel" icon={<FileExcelOutlined/>}
              onClick={handlers.onExportExcel}>导出 Excel</Button>
      <Dropdown.Button
        data-testid="ledger-export-pdf"
        icon={<FilePdfOutlined/>}
        onClick={handlers.onExportPdf}
        overlay={
          <Menu onClick={({key}) => {
            if (key === 'advanced') handlers.onOpenPdfAdvanced();
          }}>
            <Menu.Item key="advanced" data-testid="ledger-export-pdf-advanced">
              <SettingOutlined/> 高级设置并导出…
            </Menu.Item>
          </Menu>
        }>
        导出 PDF
      </Dropdown.Button>
    </Space>
  );
}

/** 高级 PDF 设置弹窗（仅本次导出生效，不改模板）。 */
function PdfAdvancedModal({visible, pdfForm, onChange, onOk, onCancel}) {
  return (
    <Modal title="高级 PDF 设置（仅本次导出生效）"
           visible={visible} width={560} destroyOnClose
           okText="确定" cancelText="取消"
           onOk={onOk} onCancel={onCancel}>
      <div style={{color: '#999', marginBottom: 12}}>
        默认使用模板发布时的参数配置；此处调整仅对本次导出生效，
        不会修改模板。
      </div>
      {pdfForm && (
        <PdfParamsForm value={pdfForm} onChange={onChange}/>
      )}
    </Modal>
  );
}

/** PDF 导出链路：预检确认弹窗 + 高级设置弹窗状态 + 覆盖导出（仅本次生效）。 */
function usePdfExport(store, guardRequired) {
  const [pdfAdvancedVisible, setPdfAdvancedVisible] = useState(false);
  const [pdfForm, setPdfForm] = useState(null);

  /** 导出前预检：有提示先弹窗确认（仍要导出/取消），无提示直接导出。
   * params 为高级设置覆盖参数，预检与导出用同一份参数估算。 */
  async function checkThenExport(runExport, params) {
    try {
      const warnings = await store.checkPdfExport(params);
      if (warnings.length) {
        Modal.confirm({
          title: '导出前检查发现以下问题',
          content: (
            <div data-testid="export-check-warnings">
              {warnings.map(item => <div key={item}>· {item}</div>)}
            </div>
          ),
          okText: '仍要导出', cancelText: '取消',
          onOk: () => runExport(),
        });
      } else {
        await runExport();
      }
    } catch (e) {
      // 预检失败已由公共拦截器提示，不继续导出
    }
  }

  /** 高级设置导出：以版本快照参数预填，调整仅对本次导出生效。 */
  function openAdvanced() {
    if (!guardRequired()) return;
    setPdfAdvancedVisible(true);
    setPdfForm(normalizePdfParams((store.version && store.version.pdf_params) || {}));
  }

  async function advancedExportOk() {
    const {payload, error} = serializePdfParams(pdfForm);
    if (error) {
      message.warning(error);
      return Promise.reject();
    }
    setPdfAdvancedVisible(false);
    await checkThenExport(() => store.exportPdf(payload), payload);
  }

  function closeAdvanced() {
    setPdfAdvancedVisible(false);
  }

  return {
    pdfAdvancedVisible, pdfForm, setPdfForm,
    checkThenExport, openAdvanced, advancedExportOk, closeAdvanced,
  };
}

const ExcelLedgerDetail = React.forwardRef(function ExcelLedgerDetail({store, onBack}, ref) {
  const detail = store.detail;
  const version = store.version;
  const sheet = store.currentSheet;

  const guardRequired = () => {
    const missing = store.requiredMissing();
    if (missing.length) {
      message.warning(`必填字段未填写：${missing.join('、')}`);
      return false;
    }
    return true;
  };

  const pdfExport = usePdfExport(store, guardRequired);

  const handleBack = () => {
    if (onBack) {
      onBack();
    } else {
      store.applyDetail(null);
      store.fetchList().catch(() => {});
    }
  };

  const handleSubmit = () => {
    if (!guardRequired()) return;
    store.submit().catch(() => {});
  };

  const handleVoid = () => {
    let reason = '';
    Modal.confirm({
      title: '作废台账',
      content: <Input placeholder="请填写作废原因" onChange={e => {
        reason = e.target.value;
      }}/>,
      onOk: () => {
        if (!reason.trim()) {
          message.warning('作废必须填写原因');
          return Promise.reject();
        }
        return store.voidLedger(reason.trim()).catch(() => {});
      },
    });
  };

  const handleExportPdf = async () => {
    if (!guardRequired()) return;
    await pdfExport.checkThenExport(() => store.exportPdf());
  };

  // 组件级入口：jsdom 下 rc-dropdown 悬停无法模拟，测试经由本方法打开
  // 高级 PDF 设置（与真实 UI 菜单项 onOpenPdfAdvanced 同一处理函数）
  React.useImperativeHandle(ref, () => ({
    openPdfAdvanced: pdfExport.openAdvanced,
  }));

  return (
    <Card bordered={false}
          title={`Excel 台账：${detail.ledger_no}`}
          extra={
            <DetailToolbar
              detail={detail}
              editable={store.editable}
              submitting={store.submitting}
              saving={store.saving}
              handlers={{
                onBack: handleBack,
                onFillNormal: () => store.fillNormal(),
                onSave: () => store.saveValues().catch(() => {}),
                onSubmit: handleSubmit,
                onReview: () => store.review().catch(() => {}),
                onVoid: handleVoid,
                onExportExcel: () => {
                  if (guardRequired()) store.exportExcel().catch(() => {});
                },
                onExportPdf: handleExportPdf,
                onOpenPdfAdvanced: pdfExport.openAdvanced,
              }}/>
          }>
      <DetailDescriptions key={detail.id} detail={detail} version={version}
                          editable={store.editable} saving={store.saving}
                          onSaveHeader={header => store.saveHeader(header).catch(() => {})}/>
      <Spin spinning={store.loading}>
        {sheet ? (
          <LayoutTable
            sheet={sheet}
            bindingByCell={store.bindingByCell}
            fillMode
            readOnly={!store.editable}
            values={store.values}
            onValueChange={(fieldId, value) => store.setValue(fieldId, value)}/>
        ) : (
          <div>版本快照缺失</div>
        )}
      </Spin>
      {store.editable && (
        <div style={{color: '#999', marginTop: 8}}>
          仅绑定单元格可填写（标题与普通单元格不可编辑）；提交后校验必填项。
        </div>
      )}
      <PdfAdvancedModal
        visible={pdfExport.pdfAdvancedVisible} pdfForm={pdfExport.pdfForm}
        onChange={form => pdfExport.setPdfForm(form)}
        onOk={pdfExport.advancedExportOk}
        onCancel={pdfExport.closeAdvanced}/>
    </Card>
  );
});

export default observer(ExcelLedgerDetail);
