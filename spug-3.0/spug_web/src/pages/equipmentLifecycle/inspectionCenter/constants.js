/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——巡检中心常量。
 * 巡检中心为前端融合外壳：今日巡检 / 巡检记录 / 巡检模板三个页签复用
 * 原独立页面组件，不合并业务逻辑与 Store。
 */

// 统一入口路径（routes.js 菜单与旧路径重定向共用）
export const CENTER_PATH = '/el/inspection-center';

// 页签查询参数名与取值（?tab=today / history / templates）
export const TAB_QUERY_KEY = 'tab';
