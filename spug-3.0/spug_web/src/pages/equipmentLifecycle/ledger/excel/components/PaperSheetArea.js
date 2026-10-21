/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * 纸张视图共用展示层（2026-10-21 自 FillWorkspace 上提）。
 *
 * Excel 台账「填写工作区」与「模板编辑工作区」共用同一套纸张观感：
 * 灰底区域 + 白色纸张卡片（真实纸张尺寸/页边距）+ 打印范围参考框 +
 * 分页参考线（统一打印计划 print_plan，后端 excel_print_layout 为唯一
 * 分页事实来源）+ transform 等比缩放（适合页宽/原始尺寸）。
 * 绑定与填写各自保留业务逻辑（本组件只渲染形态，表格由调用方以
 * children 传入各自的 LayoutTable props）。
 *
 * 组成：
 * - usePaperDisplay：显示模式状态与测量（适合页宽缩放值、默认模式判定、
 *   表格自然尺寸测量、纸张视图模型、窗口/容器尺寸变化重算）；
 * - SheetViewToolbar：导航展开钮 + 多工作表 Tabs + 纸张说明 + 显示模式
 *   切换（testid 前缀按调用方传入，填写视图保持 fill-* 不变）；
 * - PaperSheetArea：灰底区域 + 缩放视口 + 纸张卡片 + 参考线 + 打印
 *   缩放层（表格在纸张内先乘计划 scale，与浏览器 PDF 同一比例）。
 *
 * 未保存值安全：填写值/选区状态都在调用方 store，切换工作表/显示模式
 * 仅改变渲染形态，不触碰业务数据。
 */
import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {Button, Radio, Tabs, Tooltip} from 'antd';
import {MenuUnfoldOutlined} from '@ant-design/icons';

import {
  colGuideOffsets, defaultDisplayMode, fitPageWidthScale, paperViewModel,
  rowGuideOffsets,
} from '../utils';
import './FillWorkspace.less';

/** 每页一张的打印范围参考框（网页辅助；虚线不进入 PDF）：
 * 纸张卡片总高为整页倍数，每页画一个四边缩进页边距的虚线框。 */
function PrintRects({paper}) {
  const pageHeight = paper.heightPx;
  const totalHeight = paper.totalHeightPx;
  const count = Math.max(1, Math.round(totalHeight / pageHeight));
  const rects = [];
  for (let index = 0; index < count; index++) {
    rects.push(
      <div key={index} className="el-fill-print-rect"
           style={{
             top: paper.marginTopPx + index * pageHeight,
             height: Math.max(0, pageHeight - paper.marginTopPx - paper.marginBottomPx),
             left: paper.marginLeftPx,
             right: paper.marginRightPx,
           }}/>);
  }
  return <React.Fragment>{rects}</React.Fragment>;
}

/** 分页参考线：行分页横线 + 横向分块竖线（来自统一打印计划，
 * 偏移按布局行列尺寸累计，与表格 DOM 一致；仅网页辅助）。 */
function PageGuides({paper, testPrefix}) {
  const guides = [];
  paper.rowGuides.forEach((guide, index) => {
    guides.push(
      <div key={`r${guide.row}`} className="el-fill-page-guide-row"
           data-testid={`${testPrefix}-page-guide`}
           style={{top: paper.marginTopPx + guide.offsetPx,
                   left: paper.marginLeftPx, right: paper.marginRightPx}}>
        <span className="el-fill-page-guide-tag">第 {index + 2} 页</span>
      </div>);
  });
  paper.colGuides.forEach(guide => {
    guides.push(
      <div key={`c${guide.col}`} className="el-fill-page-guide-col"
           style={{left: paper.marginLeftPx + guide.offsetPx,
                   top: paper.marginTopPx,
                   height: Math.max(0, paper.printableHeightPx)}}/>);
  });
  return <React.Fragment>{guides}</React.Fragment>;
}

/**
 * 显示模式与纸张测量 hook（填写/模板编辑共用）：
 * - mode：'original' 100% | 'fit_width' 适合页宽（可用宽/内容宽，夹取）；
 * - 版式首次渲染完成后判定默认模式（宽表超可用区选适合页宽）；
 * - 渲染后测量表格自然尺寸（transform 缩放不影响 offsetWidth/Height）；
 * - 适合页宽模式下工作表切换与容器尺寸变化（含窗口缩放）时重算；
 * - detailKey 变化（切换详情/模板）重置全部显示状态。
 * store 只用于 paperViewModel（version|draft + activeSheet）。
 */
export function usePaperDisplay({store, sheet, detailKey}) {
  const [mode, setMode] = useState('original');
  const [modeDecided, setModeDecided] = useState(false);
  const [fitScale, setFitScale] = useState(1);
  // 表格自然尺寸（px，100% 渲染，不随缩放变化；量不到时 0 不参与判定）
  const [naturalSize, setNaturalSize] = useState({width: 0, height: 0});
  const areaRef = useRef(null);
  const tableRef = useRef(null);
  const scale = mode === 'fit_width' ? fitScale : 1;

  // 统一打印计划的纸张视图（print_plan 优先；缺失回落打印参数近似），
  // 计算细节在 utils.paperViewModel 纯函数中
  const paper = useMemo(
    () => paperViewModel(store, sheet, naturalSize),
    [store, sheet, naturalSize]);

  /** 视口内容尺寸（纸张卡片尺寸；无纸张信息时按表格自然尺寸）。 */
  const viewSize = paper
    ? {width: paper.totalWidthPx, height: paper.totalHeightPx}
    : {width: Math.max(naturalSize.width, 200), height: naturalSize.height + 32};

  // 渲染后测量表格自然尺寸（transform 缩放不影响 offsetWidth/Height）
  useEffect(() => {
    const table = tableRef.current;
    if (!table || !table.offsetWidth) return;
    setNaturalSize(previous => (
      previous.width === table.offsetWidth && previous.height === table.offsetHeight
        ? previous : {width: table.offsetWidth, height: table.offsetHeight}));
  });

  /** 可用宽度（去掉区域左右留白；量不到返回 0 不参与判定）。 */
  const availableWidth = useCallback(() => {
    const area = areaRef.current;
    return area && area.clientWidth > 48 ? area.clientWidth - 48 : 0;
  }, []);

  const recomputeFit = useCallback(() => {
    const content = viewSize.width;
    const available = availableWidth();
    if (content > 0 && available > 0) {
      setFitScale(fitPageWidthScale(content, available));
    }
  }, [viewSize.width, availableWidth]);

  // 切换详情/模板重置显示状态（模式重判、缩放复位）
  useEffect(() => {
    setModeDecided(false);
    setMode('original');
    setFitScale(1);
    setNaturalSize({width: 0, height: 0});
  }, [detailKey]);

  // 版式首次渲染完成后决定默认显示模式（整页宽度超出可用区选适合页宽，
  // 否则原始尺寸）
  useEffect(() => {
    if (modeDecided || !sheet) return;
    const content = viewSize.width;
    const available = availableWidth();
    if (!content || !available) return;
    setModeDecided(true);
    setMode(defaultDisplayMode(content, available));
  }, [modeDecided, sheet, viewSize.width, availableWidth]);

  // 适合页宽模式：工作表切换与容器尺寸变化（含窗口缩放）时重算缩放
  useEffect(() => {
    if (mode !== 'fit_width') return undefined;
    recomputeFit();
    if (typeof ResizeObserver === 'undefined' || !areaRef.current) return undefined;
    const observer = new ResizeObserver(() => recomputeFit());
    observer.observe(areaRef.current);
    return () => observer.disconnect();
  }, [mode, store.activeSheet, recomputeFit]);

  return {mode, setMode, paper, viewSize, naturalSize, areaRef, tableRef, scale};
}

/** 工具栏：导航展开钮 + 多工作表 Tabs + 纸张说明 + 显示模式切换。 */
export function SheetViewToolbar({sheets, activeSheet, onSheetChange, mode,
                                  onModeChange, paper, navCollapsed, onExpand,
                                  testPrefix = 'fill'}) {
  return (
    <div className="el-fill-toolbar">
      {navCollapsed && (
        <Tooltip title="展开侧栏">
          <Button size="small" icon={<MenuUnfoldOutlined/>}
                  data-testid={`${testPrefix}-nav-expand`}
                  onClick={onExpand}/>
        </Tooltip>
      )}
      {sheets.length > 1 && (
        <Tabs className="el-fill-sheet-tabs" size="small"
              activeKey={activeSheet}
              onChange={onSheetChange}
              data-testid={`${testPrefix}-sheet-tabs`}>
          {sheets.map(item => <Tabs.TabPane tab={item.name} key={item.name}/>)}
        </Tabs>
      )}
      <div className="el-fill-toolbar-right">
        {paper && (
          <span className={`el-fill-paper-caption${paper.overflow ? ' el-fill-paper-caption-warn' : ''}`}
                data-testid={`${testPrefix}-paper-caption`}>
            {paper.caption}
          </span>
        )}
        <Radio.Group size="small" buttonStyle="solid" value={mode}
                     data-testid={`${testPrefix}-display-mode`}
                     onChange={event => onModeChange(event.target.value)}>
          <Radio.Button value="fit_width">适合页宽</Radio.Button>
          <Radio.Button value="original">原始尺寸</Radio.Button>
        </Radio.Group>
      </div>
    </div>
  );
}

/** 表格视图区：transform 缩放视口（sizer 撑出滚动范围）+ 纸张卡片 +
 * 打印缩放层 + children（调用方各自的版式表格）；表格在区域内水平居中，
 * 溢出可横向滚动。打印缩放层：表格在纸张内先乘统一打印计划的 scale
 * （与浏览器 PDF 同一缩放），保证「原始尺寸」模式下表格与纸张的比例 =
 * 打印真实比例；宽表溢出可打印区时保持完整可视，由参考线提示导出时的
 * 横向分块。 */
export default function PaperSheetArea({paper, scale, viewSize, naturalSize,
                                        areaRef, testPrefix = 'fill',
                                        children}) {
  const paperStyle = paper ? {
    width: viewSize.width,
    height: paper.totalHeightPx,
    paddingTop: paper.marginTopPx,
    paddingLeft: paper.marginLeftPx,
    paddingRight: paper.marginRightPx,
    paddingBottom: paper.marginBottomPx,
  } : {minHeight: 320};
  const printScale = paper ? paper.printScale : 1;
  const scaledW = Math.round((naturalSize ? naturalSize.width : 0) * printScale);
  const scaledH = Math.round((naturalSize ? naturalSize.height : 0) * printScale);
  return (
    <div className="el-fill-sheet-area" ref={areaRef}
         data-testid={`${testPrefix}-sheet-area`}>
      {/* sizer 按缩放后尺寸撑出滚动范围；viewport 等比 transform 缩放 */}
      <div className="el-fill-zoom-sizer" data-testid={`${testPrefix}-zoom-sizer`}
           style={{width: viewSize.width * scale, height: viewSize.height * scale}}>
        <div className="el-fill-zoom-viewport"
             style={{width: viewSize.width, transform: `scale(${scale})`}}>
          <div className={paper ? 'el-fill-paper' : 'el-fill-paper el-fill-paper-plain'}
               style={paperStyle} data-testid={`${testPrefix}-paper`}>
            {paper && <PrintRects paper={paper}/>}
            {paper && <PageGuides paper={paper} testPrefix={testPrefix}/>}
            {/* 打印缩放层：占位尺寸 = 表格原始尺寸 × 打印缩放，
                transform 等比缩放（origin 0 0，与打印 HTML 同基准） */}
            <div style={paper ? {
              width: scaledW, height: scaledH,
              transform: `scale(${printScale})`, transformOrigin: '0 0',
              marginLeft: paper.tableOffsetX, marginTop: paper.tableOffsetY,
            } : undefined}>
              {children}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
