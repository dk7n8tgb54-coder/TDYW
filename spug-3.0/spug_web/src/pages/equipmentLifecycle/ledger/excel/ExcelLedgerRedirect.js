/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 旧 Excel 维护台账独立入口兼容跳转（routes.js 保留 /el/excel-ledgers 隐藏路由，
 * 2026-10 起 Excel 台账创建/查询统一并入正式周月/季维护台账页面）。
 *
 * 挂载即替换到正式周月维护台账页，并原样保留查询参数——
 * 试点期分享链接携带的 ?detail=<台账ID>&source=excel 由统一列表页的
 * 既有挂载逻辑打开 Excel 台账详情。
 */
import React, {useEffect} from 'react';
import {history} from 'libs';

export default function ExcelLedgerRedirect({location}) {
  useEffect(() => {
    const search = (location && location.search) || '';
    history.replace(`/el/week-month-ledgers${search}`);
    // 仅挂载时跳转一次；跳转后本组件随路径变化卸载
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return null;
}
