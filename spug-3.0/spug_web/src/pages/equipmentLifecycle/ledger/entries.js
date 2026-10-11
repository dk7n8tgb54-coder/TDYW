/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
/**
 * 运维台账路由入口：
 * - *LedgerIndex：台账列表页（查询/详情/提交/作废），routes.js 引用；
 *   旧可视化台账模板入口（TemplateIndex）已随旧可视化模板路线删除（2026-10），
 *   正式新增台账统一走 Excel/WPS 模板路线（LedgerIndex 内直接弹 Excel 创建）；
 *   日巡视巡检入口（InspectionToday/InspectionTemplateIndex/InspectionSheetIndex）
 *   已随日巡视活跃功能整体下线删除（2026-10-11），巡检历史数据保留在后端。
 */
import React from 'react';
import LedgerIndex from './LedgerIndex';
import {LEDGER_TYPE} from './constants';

export function WeekMonthLedgerIndex(props) {
  return <LedgerIndex ledgerType={LEDGER_TYPE.WEEK_MONTH} {...props}/>;
}

export function SeasonalLedgerIndex(props) {
  return <LedgerIndex ledgerType={LEDGER_TYPE.SEASONAL} {...props}/>;
}
