/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * Excel 台账填写工作区（2026-10-19）：填写导航 + 工作表切换 + 显示模式。
 *
 * 布局：左侧可收起「填写导航」（FillNavigator），右侧表格区。表格区：
 * - 顶部工具栏：多工作表 Tabs（单工作表不显示）、纸张说明、显示模式
 *   （适合页宽 / 原始尺寸）；
 * - 表格按版式原始像素（列宽/行高既有换算）渲染，缩放乘在布局像素上
 *   （等比，不改变单元格相对尺寸、合并关系与输入控件位置），只作用于
 *   网页显示——版本快照、导出 Excel/PDF 完全不受影响；
 * - 「原始尺寸」= 100%（列宽 = Excel 字符宽×7+5px，行高 = pt×4/3px）；
 *   「适合页宽」= 可用宽度 / 内容宽度（内容宽度 = max(纸张页宽, 表格自然
 *   宽度)，让整页含表格完整落入可视区；夹取 0.4~2.5，随窗口与工作表
 *   切换重算）；默认模式：内容宽度超出可用宽度选适合页宽，否则原始
 *   尺寸（加载中量不到宽度时保持原始尺寸）；
 * - 纸张边界：按版本打印参数（pdf_params，含页边距；缺失回退布局 meta
 *   的页面设置）绘制白纸卡片 + 可打印区域参考线，宽度超出时给出横向
 *   分页提示；无纸张信息时退化为普通白底卡片；
 * - 表格在可用区域内水平居中（margin auto，溢出时自然左对齐可横向
 *   滚动），区域限高内滚动，页面版式（导出）不受显示模式影响。
 *
 * 未保存值安全：填写值存 store（按 field_id），切换工作表/显示模式/
 * 定位仅改变渲染形态，不触碰 values，输入不丢失。
 */
import React, {useCallback, useEffect, useRef, useState} from 'react';
import {observer} from 'mobx-react';
import {Button, Radio, Tabs, Tooltip} from 'antd';
import {MenuUnfoldOutlined} from '@ant-design/icons';

import LayoutTable from './LayoutTable';
import FillNavigator from './FillNavigator';
import {
  defaultDisplayMode, fitPageWidthScale, paperViewInfo,
} from '../utils';
import './FillWorkspace.less';

/** 工具栏：导航展开钮 + 多工作表 Tabs + 纸张说明 + 显示模式切换。 */
function FillToolbar({store, sheets, mode, onModeChange, paper,
                      navCollapsed, onExpand}) {
  return (
    <div className="el-fill-toolbar">
      {navCollapsed && (
        <Tooltip title="展开填写导航">
          <Button size="small" icon={<MenuUnfoldOutlined/>}
                  data-testid="fill-nav-expand"
                  onClick={onExpand}/>
        </Tooltip>
      )}
      {sheets.length > 1 && (
        <Tabs className="el-fill-sheet-tabs" size="small"
              activeKey={store.activeSheet}
              onChange={name => store.setSheet(name)}
              data-testid="fill-sheet-tabs">
          {sheets.map(item => <Tabs.TabPane tab={item.name} key={item.name}/>)}
        </Tabs>
      )}
      <div className="el-fill-toolbar-right">
        {paper && (
          <span className={`el-fill-paper-caption${paper.overflow ? ' el-fill-paper-caption-warn' : ''}`}
                data-testid="fill-paper-caption">
            {paper.caption}
          </span>
        )}
        <Radio.Group size="small" buttonStyle="solid" value={mode}
                     data-testid="fill-display-mode"
                     onChange={event => onModeChange(event.target.value)}>
          <Radio.Button value="fit_width">适合页宽</Radio.Button>
          <Radio.Button value="original">原始尺寸</Radio.Button>
        </Radio.Group>
      </div>
    </div>
  );
}

/** 表格视图区：纸张卡片（有纸张信息时含页边距参考线）+ 版式表格；
 * 表格在区域内水平居中，溢出可横向滚动。
 * observer：读取 store.values/bindingByCell 供受控输入——不订阅时填写
 * 值变化不会重渲染表格（输入显示与 store 失真的根因）。 */
const FillSheetArea = observer(function FillSheetArea(
  {sheet, store, readOnly, scale, locate, tableRef, areaRef, paper}) {
  // 纸张卡片与表格整体等比缩放（缩放只作用于网页显示）：
  // 不缩放纸张时固定页宽会独立于表格溢出可视区，适合页宽失效
  const paperStyle = paper ? {
    width: paper.widthPx * scale,
    minHeight: paper.heightPx * scale,
    paddingTop: paper.marginTopPx * scale,
    paddingLeft: paper.marginLeftPx * scale,
    paddingRight: paper.marginRightPx * scale,
    '--el-fill-margin-top': `${paper.marginTopPx * scale}px`,
    '--el-fill-margin-left': `${paper.marginLeftPx * scale}px`,
    '--el-fill-margin-right': `${paper.marginRightPx * scale}px`,
  } : undefined;
  return (
    <div className="el-fill-sheet-area" ref={areaRef} data-testid="fill-sheet-area">
      <div className={paper ? 'el-fill-paper' : 'el-fill-paper el-fill-paper-plain'}
           style={paperStyle} data-testid="fill-paper">
        <LayoutTable
          sheet={sheet}
          bindingByCell={store.bindingByCell}
          fillMode
          readOnly={readOnly}
          values={store.values}
          scale={scale}
          locate={locate}
          tableRef={tableRef}
          onValueChange={(fieldId, value) => store.setValue(fieldId, value)}/>
      </div>
    </div>
  );
});

function FillWorkspace({store, readOnly}) {
  const detailId = store.detail ? store.detail.id : null;
  const sheets = (store.layout && store.layout.sheets) || [];
  const sheet = store.currentSheet;
  const [mode, setMode] = useState('original');
  const [modeDecided, setModeDecided] = useState(false);
  const [fitScale, setFitScale] = useState(1);
  const [navCollapsed, setNavCollapsed] = useState(false);
  const [locate, setLocate] = useState(null); // {coordinate, nonce}
  const nonceRef = useRef(0);
  const areaRef = useRef(null);
  const tableRef = useRef(null);
  const appliedScaleRef = useRef(1); // 最近一次提交已生效的缩放（量宽换算基准）
  const scale = mode === 'fit_width' ? fitScale : 1;

  // 每次提交后同步已生效缩放：渲染期读 DOM 宽度时 DOM 仍是上一轮缩放
  // 的结果，自然宽度必须除以已生效值而非本轮目标值（否则缩放错配）
  useEffect(() => {
    appliedScaleRef.current = scale;
  });

  /** 表格自然宽度（px，未缩放基准）：渲染宽度 / 已生效缩放值。 */
  const naturalWidth = useCallback(() => {
    const table = tableRef.current;
    if (!table || !table.offsetWidth) return 0;
    return table.offsetWidth / (appliedScaleRef.current || 1);
  }, []);

  /** 可用宽度（去掉区域左右留白；量不到返回 0 不参与判定）。 */
  const availableWidth = useCallback(() => {
    const area = areaRef.current;
    return area && area.clientWidth > 48 ? area.clientWidth - 48 : 0;
  }, []);

  /** 参与宽度适配的内容宽度：纸张页（A4=794px 等）与表格自然宽度取大——
   * 适合页宽让整页（纸张及其上的表格）完整落入可视区，横向不再滚动。 */
  const contentWidth = useCallback(() => {
    const natural = naturalWidth();
    const paper = paperViewInfo(
      (store.version && store.version.pdf_params) || {}, store.currentSheet, natural);
    return Math.max(natural, paper ? paper.widthPx : 0);
  }, [naturalWidth, store]);

  const recomputeFit = useCallback(() => {
    const content = contentWidth();
    const available = availableWidth();
    if (content > 0 && available > 0) {
      setFitScale(fitPageWidthScale(content, available));
    }
  }, [contentWidth, availableWidth]);

  // 切换台账详情重置显示状态（模式重判、导航展开、定位清除）
  useEffect(() => {
    setModeDecided(false);
    setMode('original');
    setFitScale(1);
    setNavCollapsed(false);
    setLocate(null);
  }, [detailId]);

  // 版式首次渲染完成后决定默认显示模式（整页宽度超出可用区选适合页宽，
  // 否则原始尺寸）
  useEffect(() => {
    if (modeDecided || !sheet) return;
    const content = contentWidth();
    const available = availableWidth();
    if (!content || !available) return;
    setModeDecided(true);
    setMode(defaultDisplayMode(content, available));
  }, [modeDecided, sheet, contentWidth, availableWidth]);

  // 适合页宽模式：工作表切换与容器尺寸变化（含窗口缩放）时重算缩放
  useEffect(() => {
    if (mode !== 'fit_width') return undefined;
    recomputeFit();
    if (typeof ResizeObserver === 'undefined' || !areaRef.current) return undefined;
    const observer = new ResizeObserver(() => recomputeFit());
    observer.observe(areaRef.current);
    return () => observer.disconnect();
  }, [mode, store.activeSheet, recomputeFit]);

  /** 定位字段：跨工作表先切换，再以新 nonce 触发滚动/高亮/聚焦。 */
  const locateBinding = useCallback(binding => {
    if (!binding) return;
    if (store.activeSheet !== binding.sheet_name) store.setSheet(binding.sheet_name);
    nonceRef.current += 1;
    setLocate({coordinate: binding.cell_coordinate, nonce: nonceRef.current});
  }, [store]);

  if (!sheet) return null;
  const paper = paperViewInfo(
    (store.version && store.version.pdf_params) || {}, sheet, naturalWidth());
  return (
    <div className="el-fill-workspace" data-testid="fill-workspace">
      {!navCollapsed && (
        <FillNavigator store={store} onLocate={locateBinding}
                       onCollapse={() => setNavCollapsed(true)}/>
      )}
      <div className="el-fill-main">
        <FillToolbar store={store} sheets={sheets} mode={mode}
                     onModeChange={setMode} paper={paper}
                     navCollapsed={navCollapsed}
                     onExpand={() => setNavCollapsed(false)}/>
        <FillSheetArea sheet={sheet} store={store} readOnly={readOnly}
                       scale={scale} locate={locate}
                       tableRef={tableRef} areaRef={areaRef} paper={paper}/>
      </div>
    </div>
  );
}

export default observer(FillWorkspace);
