/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * 历史版本只读查看抽屉（2026-10-21，自 ExcelTemplatePage 拆出的独立组件，
 * 控制主页面文件规模）。
 *
 * 内容与只读约束（任务书「历史版本必须可查看」）：
 * - 展示模板名称快照 / 发布时间 / 源文件与哈希 / 字段绑定数，源文件可下载；
 * - 四个只读视图：版式布局（与模板编辑同一套纸张观感：灰底白纸/页边距/
 *   分页参考线/适合页宽与原始尺寸/多工作表，复用 PaperSheetArea +
 *   usePaperDisplay，分页取版本快照 print_plan）、字段绑定清单、PDF 打印
 *   参数、真实 PDF 打印预览（版本自身 preview/pdf 接口，iframe 展示）；
 * - LayoutTable 不传任何选格/编辑回调且 fillMode=false——单元格、绑定、
 *   打印参数与源文件在网页层面不可修改（后端版本写路径本就缺失）；
 * - 复制为新草稿入口在头部：文案明确「历史版本不会被修改、不会自动发布」，
 *   二次确认在页面层（ExcelTemplatePage）完成；本组件只上报 onCopy。
 * 查看失败显示真实错误与重试，不显示空白成功状态。
 */
import React, {useEffect, useMemo, useState} from 'react';
import {observer} from 'mobx-react';
import {
  Alert, Button, Descriptions, Drawer, Empty, Radio, Space, Spin, Table, Tag,
} from 'antd';
import {CopyOutlined, DownloadOutlined} from '@ant-design/icons';
import {exportFile} from 'libs';

import LayoutTable from './LayoutTable';
import PaperSheetArea, {SheetViewToolbar, usePaperDisplay} from './PaperSheetArea';
import {formatPaperText} from '../excelTemplateStore';
import {
  INPUT_TYPE_LABELS, pdfParamsSummary, versionSourceUrl,
} from '../excelVersionView';

/**
 * 只读版式视图：与模板编辑/台账填写同一纸张展示层（print_plan 优先）。
 * 数据源为版本快照（version.print_plan/pdf_params），不是当前草稿。
 */
const VersionLayoutPane = function VersionLayoutPane({version}) {
  const sheets = (version.layout && version.layout.sheets) || [];
  const [activeSheet, setActiveSheet] = useState(
    version.sheet_name || (sheets[0] ? sheets[0].name : ''));
  const sheet = sheets.find(item => item.name === activeSheet) || sheets[0] || null;
  const viewStore = useMemo(() => ({
    version: {print_plan: version.print_plan, pdf_params: version.pdf_params},
    activeSheet: sheet ? sheet.name : '',
  }), [version, sheet]);
  const bindingByCell = useMemo(() => {
    const map = {};
    (version.bindings || []).forEach(binding => {
      map[`${binding.sheet_name}!${binding.cell_coordinate}`] = binding;
    });
    return map;
  }, [version]);
  const {mode, setMode, paper, viewSize, naturalSize, areaRef, tableRef, scale} =
    usePaperDisplay({store: viewStore, sheet, detailKey: version.version_no});
  if (!sheet) {
    return <Empty description="该版本没有可展示的工作表布局" style={{padding: 48}}/>;
  }
  return (
    <div className="el-fill-workspace" data-testid="ver-layout">
      <div className="el-fill-main">
        <SheetViewToolbar sheets={sheets} activeSheet={sheet.name}
                          onSheetChange={setActiveSheet} mode={mode}
                          onModeChange={setMode} paper={paper}
                          navCollapsed={false} onExpand={() => {}}
                          testPrefix="ver"/>
        <PaperSheetArea paper={paper} scale={scale} viewSize={viewSize}
                        naturalSize={naturalSize} areaRef={areaRef}
                        testPrefix="ver">
          <LayoutTable sheet={sheet} bindingByCell={bindingByCell}
                       tableRef={tableRef} wrapOverflow="visible"/>
        </PaperSheetArea>
      </div>
    </div>
  );
};

const BINDING_COLUMNS = [
  {title: '字段名称', dataIndex: 'field_name'},
  {title: '工作表', dataIndex: 'sheet_name'},
  {title: '单元格', dataIndex: 'cell_coordinate'},
  {title: '类型', dataIndex: 'input_type',
   render: value => INPUT_TYPE_LABELS[value] || value},
  {title: '必填', dataIndex: 'is_required', render: value => (value ? '是' : '否')},
  {title: '单位', dataIndex: 'unit', render: value => value || '—'},
];

const BINDINGS_VIEW = 'bindings';
const LAYOUT_VIEW = 'layout';
const PARAMS_VIEW = 'params';
const PREVIEW_VIEW = 'preview';

function VersionBindingsPane({version}) {
  return (
    <Table rowKey="field_id" size="small" columns={BINDING_COLUMNS}
           dataSource={version.bindings || []} pagination={false}
           data-testid="ver-bindings"
           locale={{emptyText: '该版本没有绑定任何字段'}}/>
  );
}

function VersionParamsPane({version}) {
  return (
    <div data-testid="ver-params">
      <Alert type="info" showIcon style={{marginBottom: 12}}
             message="以下为该版本发布时固定的打印参数快照（只读）"/>
      <Descriptions size="small" bordered column={1}>
        {pdfParamsSummary(version.pdf_params).map(item => (
          <Descriptions.Item key={item.label} label={item.label}>
            {item.value}
          </Descriptions.Item>
        ))}
      </Descriptions>
    </div>
  );
}

function VersionPreviewPane({onPreview, previewUrl, previewMeta, previewLoading,
                             previewError, previewWarnings}) {
  return (
    <div data-testid="ver-preview">
      <div className="el-print-preview-bar">
        <Button size="small" type="primary" ghost data-testid="ver-preview-refresh"
                loading={previewLoading} onClick={onPreview}>
          刷新预览
        </Button>
        {previewMeta && (previewMeta.pages || previewMeta.paper) && (
          <span className="el-print-preview-meta" data-testid="ver-preview-meta">
            {formatPaperText(previewMeta.paper)}
            {previewMeta.pages ? ` · ${previewMeta.pages} 页` : ''}
            {' '}· 参数：该版本快照的打印参数
          </span>
        )}
      </div>
      {previewError ? (
        <Empty description={previewError} style={{padding: 24}}>
          <Button type="primary" onClick={onPreview}>重试</Button>
        </Empty>
      ) : previewUrl ? (
        <iframe title="版本打印预览" src={previewUrl}
                className="el-print-preview-frame" data-testid="ver-preview-iframe"/>
      ) : (
        <Empty description="正在生成版本打印预览..." style={{padding: 48}}/>
      )}
      {previewWarnings && previewWarnings.length ? (
        <Alert type="warning" showIcon style={{marginTop: 8}}
               message="版式预检提示"
               description={previewWarnings.join('；')}/>
      ) : null}
    </div>
  );
}

/**
 * 历史版本查看抽屉：头部快照信息 + 只读内容视图 + 复制为新草稿入口。
 * templateId 供下载源文件与预览使用；canCopy=false（已停用模板/无 edit
 * 权限/未打开模板详情）时隐藏复制入口（后端仍独立校验）。
 */
/** 版本快照头部信息：名称快照/发布时间/源文件（可下载）/哈希/字段数。 */
function VersionMetaHeader({store, version}) {
  return (
    <Descriptions size="small" column={2} bordered style={{marginBottom: 12}}>
      <Descriptions.Item label="模板名称（发布时快照）">
        {version.template_name}
      </Descriptions.Item>
      <Descriptions.Item label="发布时间">{version.published_at}</Descriptions.Item>
      <Descriptions.Item label="源文件">
        <Space size={4}>
          {version.source_filename}
          <Button type="link" size="small" icon={<DownloadOutlined/>}
                  data-testid="ver-source-download"
                  onClick={() => exportFile({
                    url: versionSourceUrl(store.templateId, version.version_no),
                    method: 'get',
                    defaultFilename: version.source_filename || '版本源文件.xlsx',
                  })}>
            下载
          </Button>
        </Space>
      </Descriptions.Item>
      <Descriptions.Item label="SHA-256">
        <span style={{fontFamily: 'monospace'}}>
          {String(version.source_hash || '').slice(0, 16)}…
        </span>
      </Descriptions.Item>
      <Descriptions.Item label="字段绑定">{version.field_count} 个</Descriptions.Item>
      <Descriptions.Item label="状态">
        <Tag color="blue">已发布版本（不可变）</Tag>
      </Descriptions.Item>
    </Descriptions>
  );
}

export default observer(function VersionViewerDrawer({store, templateId, canCopy, onCopy}) {
  const version = store.version;
  const versionNo = store.versionNo;
  const [viewMode, setViewMode] = useState(LAYOUT_VIEW);
  // 切换版本重置到版式视图
  useEffect(() => {
    setViewMode(LAYOUT_VIEW);
  }, [versionNo]);
  // 进入打印预览视图自动生成一次（失败/生成中不重复触发）
  useEffect(() => {
    if (viewMode === PREVIEW_VIEW && version && !store.previewUrl
        && !store.previewLoading && !store.previewError) {
      store.loadPreview().catch(() => {});
    }
  }, [viewMode, version, store.previewUrl, store.previewLoading,
    store.previewError, store]);
  return (
    <Drawer title={versionNo
      ? `版本 v${versionNo}（只读）：${(version && version.template_name)
        || store.templateName}`
      : '版本详情（只读）'}
            width={1040} visible={store.visible} destroyOnClose
            onClose={() => store.close()}
            className="excel-version-viewer">
      {store.loading ? (
        <Spin spinning tip="加载版本内容..." style={{display: 'block', padding: 48}}/>
      ) : store.error ? (
        <div data-testid="ver-error">
          <Alert type="error" showIcon message="版本内容读取失败"
                 description={store.error} style={{marginBottom: 12}}/>
          {store.templateId && versionNo !== null && (
            <Button type="primary"
                    onClick={() => store.open(store.templateId, store.templateName,
                                              versionNo, store.templateIsActive)
                              .catch(() => {})}>
              重试
            </Button>
          )}
        </div>
      ) : version ? (
        <React.Fragment>
          <VersionMetaHeader store={store} version={version}/>
          <div className="excel-version-viewer-actions">
            <Space>
              {canCopy && (
                <Button type="primary" icon={<CopyOutlined/>} loading={store.copying}
                        disabled={!store.templateIsActive}
                        data-testid="ver-copy"
                        onClick={() => onCopy && onCopy(version)}>
                  复制为新草稿
                </Button>
              )}
              {!canCopy && (
                <span style={{color: '#999'}}>
                  历史版本只读。如需继续使用该版式，请打开模板后在版本记录中复制为新草稿。
                </span>
              )}
            </Space>
          </div>
          <div style={{margin: '8px 0'}}>
            <Radio.Group size="small" buttonStyle="solid" value={viewMode}
                         data-testid="ver-view-mode"
                         onChange={event => setViewMode(event.target.value)}>
              <Radio.Button value={LAYOUT_VIEW} data-testid="ver-view-layout">
                版式布局
              </Radio.Button>
              <Radio.Button value={BINDINGS_VIEW} data-testid="ver-view-bindings">
                字段绑定
              </Radio.Button>
              <Radio.Button value={PARAMS_VIEW} data-testid="ver-view-params">
                打印参数
              </Radio.Button>
              <Radio.Button value={PREVIEW_VIEW} data-testid="ver-view-preview">
                打印预览
              </Radio.Button>
            </Radio.Group>
          </div>
          {viewMode === LAYOUT_VIEW ? <VersionLayoutPane version={version}/> : null}
          {viewMode === BINDINGS_VIEW ? <VersionBindingsPane version={version}/> : null}
          {viewMode === PARAMS_VIEW ? <VersionParamsPane version={version}/> : null}
          {viewMode === PREVIEW_VIEW ? (
            <VersionPreviewPane
              onPreview={() => store.loadPreview().catch(() => {})}
              previewUrl={store.previewUrl}
              previewMeta={store.previewMeta}
              previewLoading={store.previewLoading}
              previewError={store.previewError}
              previewWarnings={store.previewMeta ? store.previewMeta.warnings : null}/>
          ) : null}
        </React.Fragment>
      ) : null}
    </Drawer>
  );
});
