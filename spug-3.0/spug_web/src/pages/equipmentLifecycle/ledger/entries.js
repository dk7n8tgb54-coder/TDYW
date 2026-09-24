/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 运维台账路由入口 + 模板入口（routes.js 引用）：
 * - *LedgerIndex：台账列表页（查询/详情/编辑/退回修改）；
 * - InspectionToday：今日巡检常驻工作台（打开即填，提交瞬间实体化台账）。
 */
import React from 'react';
import LedgerIndex from './LedgerIndex';
import TemplateIndex from './TemplateIndex';
import LedgerWorksheet from './LedgerWorksheet';
import {LEDGER_TYPE} from './constants';

export function InspectionLedgerIndex(props) {
  return <LedgerIndex ledgerType={LEDGER_TYPE.INSPECTION} {...props}/>;
}

export function InspectionToday(props) {
  return <LedgerWorksheet ledgerType={LEDGER_TYPE.INSPECTION} {...props}/>;
}

export function WeekMonthLedgerIndex(props) {
  return <LedgerIndex ledgerType={LEDGER_TYPE.WEEK_MONTH} {...props}/>;
}

export function SeasonalLedgerIndex(props) {
  return <LedgerIndex ledgerType={LEDGER_TYPE.SEASONAL} {...props}/>;
}

export {TemplateIndex};
