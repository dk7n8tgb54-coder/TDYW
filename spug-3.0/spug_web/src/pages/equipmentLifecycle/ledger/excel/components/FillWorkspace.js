/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * Excel 台账填写工作区（2026-10-19；2026-10-21 统一打印布局改版；
 * 同日纸张/缩放/工具栏展示层上提至 PaperSheetArea 与模板编辑共用）。
 *
 * 布局：左侧可收起「填写导航」（FillNavigator），右侧表格区。表格区
 * （SheetViewToolbar + PaperSheetArea，展示规则与模板编辑同一实现）：
 * - 顶部工具栏：多工作表 Tabs（单工作表不显示）、纸张说明、显示模式
 *   （适合页宽 / 原始尺寸）；
 * - 表格按版式原始像素渲染（列宽/行高/字号/内边距都不乘缩放），
 *   「适合页宽 / 原始尺寸」用外层 transform: scale 等比缩放整个纸张
 *   卡片——文字、边框、行高、列宽、内边距同步缩放，倍率切换不改变
 *   文字换行、表格比例与分页位置（与浏览器 PDF 打印同一布局规则，
 *   后端 excel_print_layout 为唯一分页事实来源）；缩放只作用于网页
 *   显示——版本快照、导出 Excel/PDF 完全不受影响；
 * - 纸张卡片按统一打印计划（store.version.print_plan，缺省回落打印
 *   参数近似 paperViewInfo）绘制真实纸张，分页参考线由计划换算成像素。
 *
 * 未保存值安全：填写值存 store（按 field_id），切换工作表/显示模式/
 * 定位仅改变渲染形态，不触碰 values，输入不丢失。
 */
import React, {useCallback, useEffect, useRef, useState} from 'react';
import {observer} from 'mobx-react';

import LayoutTable from './LayoutTable';
import FillNavigator from './FillNavigator';
import PaperSheetArea, {SheetViewToolbar, usePaperDisplay} from './PaperSheetArea';

function FillWorkspace({store, readOnly}) {
  const detailId = store.detail ? store.detail.id : null;
  const sheets = (store.layout && store.layout.sheets) || [];
  const sheet = store.currentSheet;
  const [navCollapsed, setNavCollapsed] = useState(false);
  const [locate, setLocate] = useState(null); // {coordinate, nonce}
  const nonceRef = useRef(0);
  const {mode, setMode, paper, viewSize, naturalSize, areaRef, tableRef,
    scale} = usePaperDisplay({store, sheet, detailKey: detailId});

  /** 定位字段：跨工作表先切换，再以新 nonce 触发滚动/高亮/聚焦。 */
  const locateBinding = useCallback(binding => {
    if (!binding) return;
    if (store.activeSheet !== binding.sheet_name) store.setSheet(binding.sheet_name);
    nonceRef.current += 1;
    setLocate({coordinate: binding.cell_coordinate, nonce: nonceRef.current});
  }, [store]);

  if (!sheet) return null;
  return (
    <div className="el-fill-workspace" data-testid="fill-workspace">
      {!navCollapsed && (
        <FillNavigator store={store} onLocate={locateBinding}
                       onCollapse={() => setNavCollapsed(true)}/>
      )}
      <div className="el-fill-main">
        <SheetViewToolbar sheets={sheets} activeSheet={store.activeSheet}
                          onSheetChange={name => store.setSheet(name)}
                          mode={mode} onModeChange={setMode} paper={paper}
                          navCollapsed={navCollapsed}
                          onExpand={() => setNavCollapsed(false)}
                          testPrefix="fill"/>
        <PaperSheetArea paper={paper} scale={scale} viewSize={viewSize}
                        naturalSize={naturalSize} areaRef={areaRef}
                        testPrefix="fill">
          <LayoutTable
            sheet={sheet}
            bindingByCell={store.bindingByCell}
            fillMode
            readOnly={readOnly}
            wrapOverflow="visible"
            values={store.values}
            locate={locate}
            tableRef={tableRef}
            onValueChange={(fieldId, value) => store.setValue(fieldId, value)}/>
        </PaperSheetArea>
      </div>
    </div>
  );
}

export default observer(FillWorkspace);
