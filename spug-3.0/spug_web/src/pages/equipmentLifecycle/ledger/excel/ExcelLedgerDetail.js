/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * Excel 路线维护台账详情视图（2026-10 自 ExcelLedgerPage 抽出复用）。
 *
 * 正式周月/季维护台账列表点击 Excel 来源记录时复用本组件；试点页
 * ExcelLedgerPage 委托同一实现。版式回放（LayoutTable 填写模式）——
 * 草稿渲染输入控件，历史状态只读展示当时填写值；主操作"完成填写"
 * （2026-10-16 流程简化，草稿专用）先保存未保存的填写值与执行日期再完成
 * （草稿 → 已完成，校验必填），次操作"保存草稿"；返回列表前有未保存修改
 * 先确认（继续填写保留内容）；已完成台账支持"更正"（进入更正模式修改后
 * 提交，记录原因与前后值）+ 更正记录展示；一键正常（仅填充未填写的
 * 正常/异常格，不覆盖已填）/ 作废（沿用既有台账端点）/ 删除（仅草稿）/
 * 导出 Excel 与 PDF；导出 PDF 先走预检接口，默认使用
 * 版本快照的模板级参数，高级设置弹窗可覆盖（仅本次）。
 *
 * onBack：返回回调；缺省时回到试点页列表（清空详情并刷新），
 * 正式台账页传入自己的返回逻辑（关闭详情并刷新统一列表）。
 */
import React, {useState} from 'react';
import {observer} from 'mobx-react';
import {
  Button, Card, DatePicker, Descriptions, Dropdown, Input, Menu, Modal,
  Popconfirm, Space, Spin, Table, Tag, message,
} from 'antd';
import moment from 'moment';
import {
  ArrowLeftOutlined, FileExcelOutlined, FilePdfOutlined, SettingOutlined,
} from '@ant-design/icons';

import LayoutTable from './components/LayoutTable';
import PdfParamsForm from './PdfParamsForm';
import {normalizePdfParams, serializePdfParams} from './pdfParams';

export const LEDGER_TYPE_TEXT = {week_month: '周月维护', seasonal: '季维护'};
// 草稿/已完成/已作废 三状态（与后端值域一致，旧流程状态已退役）
export const STATUS_TEXT = {
  draft: '草稿', completed: '已完成', void: '已作废',
};
export const STATUS_COLOR = {
  draft: 'default', completed: 'success', void: 'error',
};
// 可删除状态（与后端一致：仅草稿；已完成/已作废不可删除）
const DELETABLE_STATUS = ['draft'];

/** 表头信息（状态/类型/计划期次/执行日期/完成时间/录入人/模板/版本/源文件/哈希）。
 * 实际执行日期在可编辑（草稿）或更正模式由填写人录入（周期生成的应填台账
 * 生成时留空，创建时间不冒充执行日期）；日期草稿入 store 参与未保存状态
 * 判断，未改动时保存保持当前日期（不再误清空已录入日期）。
 * observer：直接读取 store.dateDraft/submitting 等可观察值，不包 observer 时
 * store 变化不会触发本组件重渲染（详情卡加载态定格缺陷的根因之一）。 */
const DetailDescriptions = observer(function DetailDescriptions({detail, version, editable, correcting, saving, store, onSaveHeader}) {
  const dateEditable = editable || correcting;
  const dateValue = store.dateDraft === undefined
    ? (detail.executed_date ? moment(String(detail.executed_date).slice(0, 10)) : null)
    : (store.dateDraft === '' ? null : moment(store.dateDraft));
  const handleSaveDate = () => {
    const raw = store.dateDraft !== undefined
      ? store.dateDraft
      : (detail.executed_date ? String(detail.executed_date).slice(0, 10) : '');
    onSaveHeader({executed_date: raw});
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
        {dateEditable ? (
          <Space size={4}>
            <DatePicker
              data-testid="excel-executed-date"
              size="small"
              style={{width: 130}}
              placeholder="执行后录入"
              value={dateValue}
              onChange={value => store.setDateDraft(value ? value.format('YYYY-MM-DD') : '')}/>
            {editable && (
              <Button data-testid="excel-save-executed-date" size="small"
                      disabled={store.submitting} loading={saving}
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
      {/* 列表已不放录入时间（2026-10-18 移入详情），Excel 详情头部补齐该信息 */}
      <Descriptions.Item label="录入时间">
        {detail.created_at ? String(detail.created_at).slice(0, 19).replace('T', ' ') : '—'}
      </Descriptions.Item>
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
});

/** 详情操作栏（按状态与模式显隐，2026-10-16 流程简化）：
 * - 草稿：保存草稿（次）+ 完成填写（主，先保存未保存修改再完成）+ 一键正常
 *   + 删除（草稿不走作废，直接删除重填）+ 导出；
 * - 已完成：更正（进入更正模式，须填原因）+ 作废 + 导出（不可删除）；
 * - 更正模式中：提交更正（主）+ 取消更正 + 导出；
 * - 已作废：仅查看 + 导出（保留作废信息，不再编辑/删除）。
 * 保存与完成互斥（disabled/loading 双保险），防止重复点击与并发处理。
 * observer：按 store 状态显隐按钮，状态流转（完成/作废/更正）须即时反映。 */
const DetailToolbar = observer(function DetailToolbar({detail, editable, correcting, submitting, saving, handlers}) {
  const isVoid = detail.status === 'void';
  const canDelete = DELETABLE_STATUS.includes(detail.status);
  return (
    <Space>
      <Button data-testid="excel-detail-back" icon={<ArrowLeftOutlined/>}
              onClick={handlers.onBack}>返回列表</Button>
      {correcting && (
        <Button data-testid="ledger-cancel-correct" disabled={saving}
                onClick={handlers.onCancelCorrect}>取消更正</Button>
      )}
      {correcting && (
        <Button data-testid="ledger-submit-correct" type="primary"
                loading={saving} onClick={handlers.onSubmitCorrect}>
          提交更正
        </Button>
      )}
      {editable && !correcting && (
        <Button data-testid="ledger-fill-normal" disabled={saving || submitting}
                onClick={handlers.onFillNormal}>一键正常</Button>
      )}
      {editable && !correcting && (
        <Button data-testid="ledger-save" loading={saving} disabled={submitting}
                onClick={handlers.onSave}>保存草稿</Button>
      )}
      {editable && !correcting && (
        <Button data-testid="ledger-submit" type="primary"
                loading={submitting} disabled={saving} onClick={handlers.onComplete}>
          完成填写
        </Button>
      )}
      {detail.status === 'completed' && !correcting && (
        <Button data-testid="ledger-correct" type="primary" onClick={handlers.onStartCorrect}>
          更正
        </Button>
      )}
      {!isVoid && detail.status !== 'draft' && !correcting && (
        <Popconfirm title="作废后不可恢复，确认作废？" onConfirm={handlers.onVoid}
                    okText="作废" cancelText="取消">
          <Button danger>作废</Button>
        </Popconfirm>
      )}
      {canDelete && !correcting && (
        <Popconfirm
          title="删除后台账及其填写内容将从列表与导出中移除且不可恢复，确认删除？"
          onConfirm={handlers.onDelete} okText="删除" cancelText="取消">
          <Button data-testid="ledger-delete" danger>删除</Button>
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
});

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

/** 详情主体：表头信息 + 更正记录 + 版式回放表格 + 填写提示 + 高级 PDF 设置弹窗。
 * observer：本组件读取 store.loading（版式表格 Spin），而父组件 render 路径
 * 不读取 loading——不包 observer 时 loading:false 的变化无人订阅，详情打开后
 * 加载态会永久定格（2026-10-17 实机缺陷根因，修法同故障详情时间线）。 */
const DetailBody = observer(function DetailBody({store, detail, version, sheet, pdfExport}) {
  const corrections = detail.corrections || [];
  return (
    <React.Fragment>
      <DetailDescriptions key={detail.id} detail={detail} version={version}
                          editable={store.editable} correcting={store.correcting}
                          saving={store.saving}
                          store={store}
                          onSaveHeader={header => store.saveHeader(header).catch(() => {})}/>
      {corrections.length > 0 && (
        <Table
          data-testid="excel-corrections"
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
      <Spin spinning={store.loading}>
        {sheet ? (
          <LayoutTable
            sheet={sheet}
            bindingByCell={store.bindingByCell}
            fillMode
            readOnly={!store.correctingEditable}
            values={store.values}
            onValueChange={(fieldId, value) => store.setValue(fieldId, value)}/>
        ) : (
          <div>版本快照缺失</div>
        )}
      </Spin>
      {store.editable && (
        <div style={{color: '#999', marginTop: 8}}>
          仅绑定单元格可填写（标题与普通单元格不可编辑）；"完成填写"会先保存
          未保存的填写值与实际执行日期，并校验必填项，完成后流程结束。
        </div>
      )}
      {store.correcting && (
        <div style={{color: '#fa8c16', marginTop: 8}} data-testid="correct-mode-banner">
          更正模式：修改完成后点击「提交更正」，变更前后值与更正原因将记入更正记录。
        </div>
      )}
      <PdfAdvancedModal
        visible={pdfExport.pdfAdvancedVisible} pdfForm={pdfExport.pdfForm}
        onChange={form => pdfExport.setPdfForm(form)}
        onOk={pdfExport.advancedExportOk}
        onCancel={pdfExport.closeAdvanced}/>
    </React.Fragment>
  );
});

/** 详情动作集合（2026-10-16 自组件抽出）：必填预检、返回守卫、完成填写、
 * 更正模式进出（原因弹窗）、删除、作废与 PDF 导出链路；组件只负责渲染。
 * 组件级入口：jsdom 下 rc-dropdown 悬停无法模拟，测试经由 ref.openPdfAdvanced
 * 打开高级 PDF 设置（与真实 UI 菜单项同一处理函数）。 */
function useDetailHandlers(store, onBack, ref) {
  const guardRequired = () => {
    const missing = store.requiredMissing();
    if (missing.length) {
      message.warning(`必填字段未填写：${missing.join('、')}`);
      return false;
    }
    return true;
  };

  const pdfExport = usePdfExport(store, guardRequired);

  const doBack = () => {
    if (onBack) {
      onBack();
    } else {
      store.applyDetail(null);
      store.fetchList().catch(() => {});
    }
  };

  const handleBack = () => {
    if (store.hasUnsaved) {
      // 有未保存修改先确认：继续填写保留内容，确认放弃才返回
      Modal.confirm({
        title: '有未保存的修改',
        content: '返回列表将放弃尚未保存的填写值与实际执行日期，是否继续？',
        okText: '放弃修改并返回',
        cancelText: '继续填写',
        onOk: () => doBack(),
      });
      return;
    }
    doBack();
  };

  const handleComplete = () => {
    if (!guardRequired()) return;
    store.complete().catch(() => {});
  };

  /** 进入更正模式：先填更正原因（必填），确认后填写区解锁。 */
  const handleStartCorrect = () => {
    let reason = '';
    Modal.confirm({
      title: '更正已完成台账',
      content: (
        <React.Fragment>
          <p style={{color: '#666'}}>
            更正须填写原因；提交后修改人、时间与修改前后内容将记入更正记录。
          </p>
          <Input.TextArea
            rows={3} maxLength={200}
            placeholder="请填写更正原因（必填）"
            onChange={e => { reason = e.target.value; }}/>
        </React.Fragment>
      ),
      okText: '进入更正', cancelText: '取消',
      onOk: () => {
        if (!reason.trim()) {
          message.warning('更正必须填写原因');
          return Promise.reject();
        }
        store.startCorrection(reason.trim());
      },
    });
  };

  const handleSubmitCorrect = () => {
    store.submitCorrection().catch(() => {});
  };

  const handleDelete = () => {
    store.deleteLedger()
      .then(() => {
        message.success('台账已删除');
        doBack();
      })
      .catch(() => {});
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

  React.useImperativeHandle(ref, () => ({
    openPdfAdvanced: pdfExport.openAdvanced,
  }));

  return {
    guardRequired, pdfExport, handleBack, handleComplete, handleStartCorrect,
    handleSubmitCorrect, handleDelete, handleVoid, handleExportPdf,
  };
}

const ExcelLedgerDetail = React.forwardRef(function ExcelLedgerDetail({store, onBack}, ref) {
  const detail = store.detail;
  const version = store.version;
  const sheet = store.currentSheet;
  const handlers = useDetailHandlers(store, onBack, ref);
  const {
    guardRequired, pdfExport, handleBack, handleComplete, handleStartCorrect,
    handleSubmitCorrect, handleDelete, handleVoid, handleExportPdf,
  } = handlers;

  return (
    <Card bordered={false}
          title={`Excel 台账：${detail.ledger_no}`}
          extra={
            <DetailToolbar
              detail={detail}
              editable={store.editable}
              correcting={store.correcting}
              submitting={store.submitting}
              saving={store.saving}
              handlers={{
                onBack: handleBack,
                onFillNormal: () => store.fillNormal(),
                onSave: () => store.saveValues().catch(() => {}),
                onComplete: handleComplete,
                onStartCorrect: handleStartCorrect,
                onSubmitCorrect: handleSubmitCorrect,
                onCancelCorrect: () => store.cancelCorrection(),
                onDelete: handleDelete,
                onVoid: handleVoid,
                onExportExcel: () => {
                  if (guardRequired()) store.exportExcel().catch(() => {});
                },
                onExportPdf: handleExportPdf,
                onOpenPdfAdvanced: pdfExport.openAdvanced,
              }}/>
          }>
      <DetailBody store={store} detail={detail} version={version}
                  sheet={sheet} pdfExport={pdfExport}/>
    </Card>
  );
});

export default observer(ExcelLedgerDetail);
