/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 运维台账路由入口 + 模板入口 + 值班巡检入口：
 * - *LedgerIndex：台账列表页（查询/详情/编辑/退回修改），routes.js 引用；
 * - InspectionToday：今日巡检工作台（值班巡检单：值班日+模板+固定四轮，
 *   不关联系统；旧巡检台账入口已删除）；2026-09 起巡检三入口融合为
 *   巡检中心页签（../inspectionCenter），本文件的巡检入口仅保留导出
 *   兼容旧引用（legacy 契约测试仍使用），routes.js 不再直接引用；
 * - InspectionTemplateIndex：巡检模板管理（设备名称 → 检查内容两级结构）。
 */
import React from 'react';
import LedgerIndex from './LedgerIndex';
import TemplateIndex from './TemplateIndex';
import InspectionWorksheet from '../inspection/InspectionWorksheet';
import InspectionTemplateIndex from '../inspection/TemplateIndex';
import InspectionSheetIndex from '../inspection/SheetIndex';
import {LEDGER_TYPE} from './constants';

export function InspectionToday(props) {
  return <InspectionWorksheet {...props}/>;
}

export {InspectionTemplateIndex, InspectionSheetIndex};

export function WeekMonthLedgerIndex(props) {
  return <LedgerIndex ledgerType={LEDGER_TYPE.WEEK_MONTH} {...props}/>;
}

export function SeasonalLedgerIndex(props) {
  return <LedgerIndex ledgerType={LEDGER_TYPE.SEASONAL} {...props}/>;
}

export {TemplateIndex};
