/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * Excel 模板编辑工作区主体（2026-10-21 统一观感改版，自 ExcelTemplatePage
 * 拆出控制主页面文件规模）。
 *
 * 与「周月/季维护台账」填写界面同一套展示能力（共用 PaperSheetArea /
 * usePaperDisplay，模板数据源为草稿 print_plan/pdf_params，台账为版本
 * 快照，字段同构）：
 * - TemplateWorkspaceBody：「字段绑定 / 打印预览」两个视图（默认字段
 *   绑定），切换互不丢失编辑状态（绑定/选区都在 store）；
 * - TemplateBindingView：左侧可收起「字段绑定」面板（单字段属性配置 +
 *   批量绑定 + 已绑定字段导航），中央为纸张化表格区（灰底 + 白纸 +
 *   页边距 + 分页参考线 + 适合页宽/原始尺寸 + 多工作表切换），单元格
 *   选择/高亮/拖选批量绑定/字段定位/解绑能力不变；缩放为外层 transform
 *   等比缩放（文字/边框/行高/列宽同步缩放），选格与定位基于表格 DOM
 *   坐标，缩放后坐标天然准确；
 * - TemplatePrintPreviewPane：当前页面内 iframe 展示真实生成的 PDF
 *   （与「预览空白打印稿」同一模板预览服务，参数为模板已保存打印参数），
 *   标注页数/纸张与参数来源；预览生成后草稿再变更时明确提示需要刷新。
 *
 * 兼容性检查与填写区尺寸提示与绑定相关，随字段绑定视图渲染；
 * 已停用模板仅供查看（选格/定位冻结，后端独立校验兜底）。
 */
import React, {useCallback, useEffect, useRef, useState} from 'react';
import {observer} from 'mobx-react';
import {Alert, Button, Empty, Input, Radio, Tag} from 'antd';
import {DoubleLeftOutlined} from '@ant-design/icons';

import LayoutTable, {bindBlockReason} from './LayoutTable';
import PaperSheetArea, {SheetViewToolbar, usePaperDisplay} from './PaperSheetArea';
import FieldPanel from './FieldPanel';
import BatchBindingPanel from '../BatchBindingPanel';
import {tightMergedTextBindings} from '../utils';
import {formatPaperText} from '../excelTemplateStore';

/** 已绑定字段导航：搜索过滤 + 点击跨工作表定位并选中单元格。 */
function BindingNavigator({bindings, onSelect, disabled}) {
  const [query, setQuery] = useState('');
  const matches = bindings.filter(binding =>
    `${binding.field_name} ${binding.sheet_name} ${binding.cell_coordinate}`
      .toLowerCase().includes(query.trim().toLowerCase()));
  return (
    <section className="excel-workspace-section">
      <div className="excel-workspace-section-title">
        <strong>已绑定字段</strong><Tag>{bindings.length}</Tag>
      </div>
      <Input.Search data-testid="tpl-binding-search" aria-label="搜索字段或单元格"
                    placeholder="搜索字段或单元格"
                    value={query} onChange={event => setQuery(event.target.value)}/>
      <div className="excel-workspace-binding-list">
        {matches.length ? matches.map(binding => (
          <button type="button" key={binding.field_id}
                  data-testid="tpl-binding-item"
                  className="excel-workspace-binding-row" disabled={disabled}
                  onClick={() => onSelect(binding)}>
            <span className="excel-workspace-binding-name">{binding.field_name}</span>
            <span className="excel-workspace-binding-location">
              {binding.sheet_name} · {binding.cell_coordinate}
              {binding.is_required ? ' · 必填' : ''}
            </span>
          </button>
        )) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={query ? '没有匹配字段' : '暂无绑定字段'}/>}
      </div>
    </section>
  );
}

/**
 * 字段绑定视图：左侧可收起绑定面板 + 中央纸张化表格区。
 * 字段定位复用 LayoutTable 的 locate 机制（滚动进入可视区 + 短暂高亮，
 * 与填写导航同一实现），缩放是外层 transform，定位坐标不受影响。
 */
const TemplateBindingView = observer(function TemplateBindingView({store, deleted}) {
  const sheets = (store.layout && store.layout.sheets) || [];
  const sheet = store.currentSheet;
  const [navCollapsed, setNavCollapsed] = useState(false);
  const [locate, setLocate] = useState(null); // {coordinate, nonce}
  const nonceRef = useRef(0);
  const {mode, setMode, paper, viewSize, naturalSize, areaRef, tableRef,
    scale} = usePaperDisplay({
      store, sheet,
      // 切换模板重置显示状态；同一模板内保存绑定（详情刷新同 id）不重置
      detailKey: store.current ? store.current.id : null,
    });

  /** 导航定位：跨工作表先切换，选中目标格并以新 nonce 触发滚动高亮。 */
  const selectBinding = useCallback(binding => {
    if (deleted || !binding) return;
    if (store.activeSheet !== binding.sheet_name) store.setSheet(binding.sheet_name);
    store.clearSelection();
    if (store.selectedCell !== binding.cell_coordinate) {
      store.selectCell(binding.cell_coordinate);
    }
    nonceRef.current += 1;
    setLocate({coordinate: binding.cell_coordinate, nonce: nonceRef.current});
  }, [store, deleted]);

  if (!sheet) return null;
  return (
    <div className="el-fill-workspace" data-testid="tpl-binding-view">
      {!navCollapsed && (
        <aside className="excel-workspace-sidebar"
               data-testid="tpl-binding-sidebar">
          <div className="excel-workspace-sidebar-head">
            <strong>字段绑定</strong>
            <Button type="text" size="small" icon={<DoubleLeftOutlined/>}
                    data-testid="tpl-nav-collapse" title="收起字段绑定面板"
                    onClick={() => setNavCollapsed(true)}/>
          </div>
          <section className="excel-workspace-section">
            <div className="excel-workspace-section-title">
              <strong>{store.selectedCells.length ? '批量绑定' : '字段绑定'}</strong>
              <Tag color="blue">{store.selectedCells.length
                ? `已选 ${store.selectedCells.length} 格` : (store.selectedCell || '未选择')}</Tag>
            </div>
            {store.selectedCells.length > 0 ? (
              <BatchBindingPanel selectedCells={store.selectedCells}
                                 sheetName={store.activeSheet}
                                 bindingByCell={store.bindingByCell}
                                 saving={store.saving}
                                 onSave={form => store.saveBatchBinding(form)}
                                 onUnbind={() => store.saveBatchUnbind()}
                                 onClear={() => store.clearSelection()}/>
            ) : (
              <FieldPanel
                key={`${store.activeSheet}!${store.selectedCell}!${store.selectedBinding ? store.selectedBinding.field_id : 'none'}`}
                coord={store.selectedCell}
                binding={store.selectedBinding}
                sheetName={store.activeSheet}
                blockReason={store.selectedCell && !store.selectedBinding
                  ? bindBlockReason(sheet, store.selectedCell) : null}
                saving={store.saving}
                onSave={form => store.saveBinding(form)}
                onRemove={() => store.selectedBinding
                  && store.removeBinding(store.selectedBinding.field_id)}/>
            )}
          </section>
          <BindingNavigator bindings={store.bindings}
                            disabled={deleted} onSelect={selectBinding}/>
        </aside>
      )}
      <div className="el-fill-main">
        <SheetViewToolbar sheets={sheets} activeSheet={store.activeSheet}
                          onSheetChange={name => store.setSheet(name)}
                          mode={mode} onModeChange={setMode} paper={paper}
                          navCollapsed={navCollapsed}
                          onExpand={() => setNavCollapsed(false)}
                          testPrefix="tpl"/>
        <PaperSheetArea paper={paper} scale={scale} viewSize={viewSize}
                        naturalSize={naturalSize} areaRef={areaRef}
                        testPrefix="tpl">
          <LayoutTable
            sheet={sheet}
            bindingByCell={store.bindingByCell}
            fillMode={false}
            selectedCell={store.selectedCell}
            selectedCells={store.selectedCells}
            preventTextSelect={store.isDragging}
            locate={locate}
            tableRef={tableRef}
            wrapOverflow="visible"
            onSelectCell={(coord, event) => {
              if (deleted) return;
              store.handleCellClick(coord, event);
            }}
            onCellMouseDown={(coord, event) => {
              if (deleted) return;
              store.beginDrag(coord, event);
              // 拖拽从可填写格（含已绑定）开始时阻断浏览器文字选择，
              // 只作用于模板编辑表格的 mousedown，不影响其他区域
              if (store.isDragging && event
                  && typeof event.preventDefault === 'function') {
                event.preventDefault();
              }
            }}
            onCellMouseEnter={coord => store.extendDrag(coord)}/>
        </PaperSheetArea>
      </div>
    </div>
  );
});

/** 草稿兼容性检查提示（error=须处理后才能发布；warning=可能有格式差异）。 */
export function CompatibilityAlert({store}) {
  const compat = store.compatibility;
  if (!compat || compat.status === 'ok') return null;
  const messages = [
    ...(compat.warnings || []),
    ...(compat.unsupported && compat.unsupported.length
      ? [`包含平台暂不支持的特性：${compat.unsupported.join('、')}，请处理后重新上传源文件`]
      : []),
  ];
  if (!messages.length) return null;
  return (
    <Alert data-testid="tpl-compat" showIcon style={{marginBottom: 12}}
           type={compat.status === 'error' ? 'error' : 'warning'}
           message={compat.status === 'error'
             ? '模板草稿存在问题，处理后才能发布'
             : '模板可能存在格式差异'}
           description={messages.join('；')}/>
  );
}

/**
 * 填写区尺寸提示（2026-10-14）：横向合并多列不会增加填写高度，只有
 * 一行默认高度的合并文本填写格在网页上填写区域较小；提示在 Excel/WPS
 * 中设置行高后重传。只提示不改模板、不阻断发布。
 */
export function SizeHintsAlert({store}) {
  const sheet = store.currentSheet;
  if (!sheet) return null;
  const tight = tightMergedTextBindings(sheet, store.bindings);
  if (!tight.length) return null;
  const rowText = coord => coord.replace(/[A-Z]/g, '');
  return (
    <Alert data-testid="tpl-size-hints" showIcon type="info" style={{marginBottom: 12}}
           message="部分填写格只有一行高度，网页填写区域较小"
           description={(
             <div>
               {tight.map(item => (
                 <div key={item.coordinate}>
                   「{item.field_name}」（{item.coordinate}）位于单行高的合并区域：
                   横向合并多列不会增加填写高度。如需更大的填写区域，请在 Excel/WPS
                   中选中第 {rowText(item.coordinate)} 行，右键选择「行高」设置更大的值
                   （如 40 磅以上），然后重新上传源文件并重新绑定（重传会清空现有绑定）。
                 </div>
               ))}
             </div>
           )}/>
  );
}

/**
 * 打印预览视图（2026-10-21 统一观感）：当前页面内 iframe 展示真实生成
 * 的 PDF（与「预览空白打印稿」同一 preview/pdf 服务，使用模板已保存的
 * 打印参数）；进入视图自动生成一次，之后由「刷新预览」手动更新。
 * 反馈（页数/纸张）来自响应头真实读取；预览生成后草稿再变更（保存绑定/
 * 替换源文件/打印参数）时明确提示需要刷新，不静默当作最新版式。
 */
const TemplatePrintPreviewPane = observer(function TemplatePrintPreviewPane({store}) {
  const meta = store.printPreviewMeta;
  const templateId = store.current ? store.current.id : null;
  // 进入视图自动生成一次（无预览且未在生成中）；模板切换后重取
  useEffect(() => {
    if (templateId && !store.printPreviewUrl) {
      store.fetchTemplatePrintPreview().catch(() => {});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [templateId]);
  return (
    <div data-testid="tpl-print-preview">
      <div className="el-print-preview-bar">
        <Button size="small" type="primary" ghost
                data-testid="tpl-preview-refresh"
                loading={store.printPreviewLoading}
                onClick={() => store.fetchTemplatePrintPreview().catch(() => {})}>
          刷新预览
        </Button>
        {meta && (meta.pages || meta.paper) && (
          <span className="el-print-preview-meta" data-testid="tpl-preview-meta">
            {formatPaperText(meta.paper)}{meta.pages ? ` · ${meta.pages} 页` : ''}
            {' '}· 参数：模板已保存的打印参数
          </span>
        )}
        {store.printPreviewStale && (
          <span className="el-print-preview-dirty" data-testid="tpl-preview-stale">
            草稿在预览后有变更（绑定/源文件/打印参数），请刷新预览查看最新版式
          </span>
        )}
      </div>
      {store.printPreviewError ? (
        <div data-testid="tpl-preview-error" style={{padding: 24}}>
          <Empty description={store.printPreviewError}>
            <Button type="primary" onClick={() => store.fetchTemplatePrintPreview().catch(() => {})}>
              重试
            </Button>
          </Empty>
        </div>
      ) : store.printPreviewUrl ? (
        <iframe title="模板打印预览" src={store.printPreviewUrl}
                className="el-print-preview-frame" data-testid="tpl-preview-iframe"/>
      ) : (
        <Empty description="正在生成打印预览..." style={{padding: 48}}/>
      )}
    </div>
  );
});

/**
 * 工作区主体：「字段绑定 / 打印预览」视图切换（默认字段绑定）。
 * 两个视图独立渲染，切换不触碰 store 业务状态（绑定/选区/显示模式各自
 * 保留，切回不丢失）。
 */
export function TemplateWorkspaceBody({store, deleted}) {
  const [viewMode, setViewMode] = useState('binding');
  return (
    <React.Fragment>
      <div style={{marginBottom: 8}}>
        <Radio.Group size="small" buttonStyle="solid" value={viewMode}
                     data-testid="tpl-view-mode"
                     onChange={event => setViewMode(event.target.value)}>
          <Radio.Button value="binding" data-testid="tpl-view-mode-binding">
            字段绑定
          </Radio.Button>
          <Radio.Button value="preview" data-testid="tpl-view-mode-preview">
            打印预览
          </Radio.Button>
        </Radio.Group>
      </div>
      {viewMode === 'preview' ? (
        <TemplatePrintPreviewPane store={store}/>
      ) : (
        <React.Fragment>
          <CompatibilityAlert store={store}/>
          <SizeHintsAlert store={store}/>
          <TemplateBindingView store={store} deleted={deleted}/>
        </React.Fragment>
      )}
    </React.Fragment>
  );
}
