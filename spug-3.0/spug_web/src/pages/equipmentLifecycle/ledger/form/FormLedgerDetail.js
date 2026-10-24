/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * 数字表单路线台账详情/填写视图（2026-10-21，与 ExcelLedgerDetail 平级）。
 *
 * - 正式周月/季维护台账列表点击"数字表单"来源记录时进入（LedgerDetailLayer
 *   按 store.detail 挂载）；草稿渲染可编辑表单，历史状态只读展示；
 * - 完成度条 + 必填未填计数（点击定位第一项，滚动至锚点）；必填口径与
 *   后端 missing_required_labels 同构（collectFillUnits）；
 * - 主操作"完成填写"（草稿专用）：有必填未填时先定位不提交；通过后先保存
 *   未保存内容再请求完成（草稿 → 已完成，后端必填终验兜底）；
 * - 返回列表前有未保存修改先确认（不保存并返回/继续填写）；
 * - PDF 预览/导出（2026-10-22，ledger.export 权限）：与后端同一生成函数，
 *   有未保存修改先确认"PDF 基于最近一次保存的内容"再生成；
 * - 作废/删除等低频操作沿用列表"更多"菜单（既有 /ledgers 端点），
 *   本视图不重复提供。
 */
import React, {useEffect} from 'react';
import {observer} from 'mobx-react';
import {Button, Card, Descriptions, Empty, Modal, Progress, Spin, Tag, message} from 'antd';
import {ArrowLeftOutlined, AimOutlined} from '@ant-design/icons';
import FormFillRenderer, {
  collectFillUnits, useNarrowViewport,
} from './FormFillRenderer';
import {LEDGER_TYPE_TEXT, PERM_L} from '../constants';
import {STATUS_TEXT} from '../constants';
import {AuthButton} from 'components';

const STATUS_COLOR = {draft: 'default', completed: 'success', void: 'error'};

function scrollToAnchor(anchor) {
  const el = document.getElementById(anchor);
  if (el && el.scrollIntoView) {
    el.scrollIntoView({behavior: 'smooth', block: 'center'});
  }
}

function locateFirstMissing(units) {
  const missing = units.find(unit => unit.required && !unit.filled);
  if (missing) {
    scrollToAnchor(missing.anchor);
    message.warning(`必填项未填写：${missing.label}`);
  }
}

const HeaderDescriptions = observer(function HeaderDescriptions({detail}) {
  const form = detail.form || {};
  const version = form.version || {};
  return (
    <Descriptions size="small" bordered column={4} style={{marginBottom: 12}}>
      <Descriptions.Item label="模板">{version.template_name || '—'}</Descriptions.Item>
      <Descriptions.Item label="版本">{version.version_no ? `v${version.version_no}` : '—'}</Descriptions.Item>
      <Descriptions.Item label="状态">
        <Tag color={STATUS_COLOR[detail.status]}>{STATUS_TEXT[detail.status] || detail.status}</Tag>
      </Descriptions.Item>
      <Descriptions.Item label="类型">
        {LEDGER_TYPE_TEXT[detail.ledger_type] || detail.ledger_type}
      </Descriptions.Item>
      <Descriptions.Item label="系统">{detail.system_name || '—'}</Descriptions.Item>
      <Descriptions.Item label="计划期次">{detail.maintenance_period || '—'}</Descriptions.Item>
      <Descriptions.Item label="录入人">{detail.created_by_name || '—'}</Descriptions.Item>
      <Descriptions.Item label="完成时间">
        {detail.completed_at ? String(detail.completed_at).slice(0, 19).replace('T', ' ') : '—'}
      </Descriptions.Item>
    </Descriptions>
  );
});

const ProgressLine = observer(function ProgressLine({store}) {
  const form = store.formStructure;
  const units = collectFillUnits(form, store.values);
  const total = units.length;
  const filled = units.filter(unit => unit.filled).length;
  const missingRequired = units.filter(unit => unit.required && !unit.filled).length;
  const percent = total ? Math.round((filled / total) * 100) : 100;
  return (
    <div style={{display: 'flex', alignItems: 'center', marginBottom: 12, gap: 12}}
         data-testid="form-fill-progress">
      <Progress percent={percent} size="small" style={{flex: 1, marginBottom: 0}}/>
      <span style={{color: '#999', whiteSpace: 'nowrap'}}>已填 {filled}/{total}</span>
      {missingRequired > 0 && (
        <a style={{color: '#f5222d', whiteSpace: 'nowrap'}}
           data-testid="form-locate-missing"
           onClick={() => locateFirstMissing(units)}>
          <AimOutlined/> 必填未填 {missingRequired} 项，点击定位
        </a>
      )}
    </div>
  );
});

/**
 * 数字表单台账 PDF 预览弹层：打开时请求后端生成（POST preview/pdf/，
 * 与导出同一生成函数——看到的就是下载的结果），iframe 内嵌展示 +
 * 页数/纸张反馈；生成失败显示失败态可重试。关闭时释放 blob URL。
 * observer：弹窗读取 store 的加载/失败/URL 状态，必须订阅变更。
 */
const LedgerPdfPreviewModal = observer(function LedgerPdfPreviewModal({visible, store, onClose}) {
  useEffect(() => {
    if (visible && store.detail) {
      store.fetchPdfPreview().catch(() => {});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible, store.detail && store.detail.id]);
  return (
    <Modal title={`PDF 预览：${store.detail ? store.detail.ledger_no : ''}`}
           visible={visible} footer={<Button onClick={onClose}>关闭</Button>}
           onCancel={onClose} width={900} destroyOnClose>
      {store.pdfPreviewError ? (
        <Empty description={
          <span>
            {store.pdfPreviewError}
            <Button type="link" size="small" data-testid="form-pdf-preview-retry"
                    onClick={() => store.fetchPdfPreview().catch(() => {})}>
              重新生成
            </Button>
          </span>}/>
      ) : store.pdfPreviewUrl ? (
        <div data-testid="form-pdf-preview-body">
          <div style={{marginBottom: 8, color: '#999', fontSize: 12}}
               data-testid="form-pdf-preview-meta">
            {store.pdfPreviewMeta && store.pdfPreviewMeta.pages
              ? `共 ${store.pdfPreviewMeta.pages} 页` : ''}
            {store.pdfPreviewMeta && store.pdfPreviewMeta.paper
              ? ` · ${store.pdfPreviewMeta.paper}` : ''}
            {' '}· 基于最近一次保存的填写内容生成
          </div>
          <iframe title="数字表单台账 PDF 预览" src={store.pdfPreviewUrl}
                  style={{width: '100%', height: 560, border: '1px solid #e8e8e8'}}
                  data-testid="form-pdf-preview-iframe"/>
        </div>
      ) : (
        <div style={{padding: '80px 0', textAlign: 'center'}}>
          <Spin/>
          <div style={{marginTop: 12, color: '#999'}}>正在生成 PDF…</div>
        </div>
      )}
    </Modal>
  );
});

function FormLedgerDetail({store, onBack}) {
  const detail = store.detail;
  const narrow = useNarrowViewport();
  const [pdfPreviewVisible, setPdfPreviewVisible] = React.useState(false);
  if (!detail) {
    return <Spin style={{display: 'block', margin: '80px auto'}}/>;
  }
  const editable = store.editable;

  /** PDF 基于已保存数据生成：有未保存修改时先明确提示，不静默导出。 */
  const guardSaved = proceed => {
    if (!store.hasUnsaved) {
      proceed();
      return;
    }
    Modal.confirm({
      title: '有未保存的修改',
      content: 'PDF 将基于最近一次保存的填写内容生成，未保存的修改不会包含在内；'
        + '如需包含，请先保存草稿。',
      okText: '继续生成', cancelText: '取消',
      onOk: proceed,
    });
  };

  const handlePdfPreview = () => guardSaved(() => setPdfPreviewVisible(true));
  const handlePdfExport = () => guardSaved(() => store.exportPdf().catch(() => {}));

  const handleBack = () => {
    if (store.hasUnsaved) {
      Modal.confirm({
        title: '有未保存的修改',
        content: '返回列表将丢失未保存的填写内容，确定返回？',
        okText: '不保存并返回',
        okButtonProps: {danger: true},
        cancelText: '继续填写',
        onOk: onBack,
      });
      return;
    }
    onBack();
  };

  const handleComplete = () => {
    const units = collectFillUnits(store.formStructure, store.values);
    const missing = units.filter(unit => unit.required && !unit.filled);
    if (missing.length > 0) {
      Modal.confirm({
        title: `还有 ${missing.length} 项必填未填写`,
        content: missing.slice(0, 5).map(unit => unit.label).join('、')
          + (missing.length > 5 ? ` 等 ${missing.length} 项` : ''),
        okText: '定位第一项',
        cancelText: '返回填写',
        onOk: () => locateFirstMissing(units),
      });
      return;
    }
    store.complete().catch(() => {});
  };

  return (
    <Card bordered={false}
          title={`数字表单台账：${detail.ledger_no}`}
          extra={
            <span>
              <Button data-testid="form-detail-back" icon={<ArrowLeftOutlined/>}
                      onClick={handleBack}>返回列表</Button>
              <AuthButton auth={PERM_L.LED_EXPORT} style={{marginLeft: 8}}
                          data-testid="form-pdf-preview"
                          loading={store.pdfPreviewLoading}
                          onClick={handlePdfPreview}>预览 PDF</AuthButton>
              <AuthButton auth={PERM_L.LED_EXPORT} style={{marginLeft: 8}}
                          data-testid="form-pdf-export"
                          loading={store.exportingPdf}
                          onClick={handlePdfExport}>导出 PDF</AuthButton>
              {editable && (
                <Button style={{marginLeft: 8}} loading={store.saving}
                        data-testid="form-save-draft"
                        onClick={() => store.saveValues().catch(() => {})}>
                  保存草稿
                </Button>
              )}
              {editable && (
                <Button style={{marginLeft: 8}} type="primary" loading={store.submitting}
                        data-testid="form-complete"
                        onClick={handleComplete}>
                  完成填写
                </Button>
              )}
            </span>
          }>
      <HeaderDescriptions detail={detail}/>
      {editable && <ProgressLine store={store}/>}
      {detail.status === 'void' && (
        <div style={{marginBottom: 12}}>
          <Tag color="default">已作废</Tag>
          {detail.void_reason ? <span style={{color: '#999'}}>作废原因：{detail.void_reason}</span> : null}
        </div>
      )}
      <FormFillRenderer
        form={store.formStructure}
        values={store.values}
        editable={editable}
        narrow={narrow}
        onEdit={(...args) => store.edit(...args)}/>
      <LedgerPdfPreviewModal visible={pdfPreviewVisible} store={store}
                             onClose={() => {
                               setPdfPreviewVisible(false);
                               store.closePdfPreview();
                             }}/>
    </Card>
  );
}

export default observer(FormLedgerDetail);
