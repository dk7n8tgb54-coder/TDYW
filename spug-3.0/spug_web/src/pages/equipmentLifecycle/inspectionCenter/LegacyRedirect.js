/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 旧巡检独立路径兼容跳转（routes.js 保留 /el/inspection-today、
 * /el/inspection-sheets、/el/inspection-templates 三条隐藏路由）。
 *
 * 挂载即替换到巡检中心对应页签，并保留旧 URL 上的其余查询参数——
 * 故障详情 / 系统履历跳转来源巡检单携带的 detail=<巡检单ID>
 * 原样带入巡检中心，由巡检记录页签的既有挂载逻辑打开详情。
 */
import React, {useEffect} from 'react';
import {history} from 'libs';
import {CENTER_PATH, TAB_QUERY_KEY} from './constants';

export default function InspectionCenterRedirect({tab, location}) {
  useEffect(() => {
    const params = new URLSearchParams(location ? location.search : '');
    params.set(TAB_QUERY_KEY, tab);
    const search = params.toString();
    history.replace(`${CENTER_PATH}${search ? `?${search}` : ''}`);
    // 仅挂载时跳转一次；跳转后本组件随路径变化卸载
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return null;
}
