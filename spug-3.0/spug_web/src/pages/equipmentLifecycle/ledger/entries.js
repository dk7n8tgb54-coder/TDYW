/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 运维台账三个路由入口 + 模板/巡检点入口（routes.js 引用）。
 */
import React from 'react';
import LedgerIndex from './LedgerIndex';
import TemplateIndex from './TemplateIndex';
import PointIndex from './PointIndex';
import {LEDGER_TYPE} from './constants';

export function InspectionLedgerIndex(props) {
  return <LedgerIndex ledgerType={LEDGER_TYPE.INSPECTION} {...props}/>;
}

export function WeekMonthLedgerIndex(props) {
  return <LedgerIndex ledgerType={LEDGER_TYPE.WEEK_MONTH} {...props}/>;
}

export function SeasonalLedgerIndex(props) {
  return <LedgerIndex ledgerType={LEDGER_TYPE.SEASONAL} {...props}/>;
}

export {TemplateIndex, PointIndex};
