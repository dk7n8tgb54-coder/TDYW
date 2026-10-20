/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 系统升级管理——页签融合外壳（2026-10，参照巡检中心模式）。
 *
 * 将左侧菜单"升级表单 / 升级方案"两个入口融合为一个页面，通过页签访问：
 * - 复用原页面组件（升级表单 index.js / 升级方案 PlanManager），不合并
 *   两者的请求、表单与业务逻辑；二者共用同一 upgrade store（模块单例）；
 * - 两个页签同属 upgrade.upgrade.view 权限，由外壳 AuthDiv 统一拦截，
 *   无需按页签过滤；
 * - 当前页签写入 URL（?tab=），刷新后恢复；旧路径 /upgrade/plans 经
 *   UpgradeCenterRedirect 跳入方案页签并保留其余查询参数；
 * - 同一时刻只挂载当前页签的页面组件；新建升级弹窗由 store 驱动且仅由
 *   升级表单页渲染，切换页签后保留（切回即恢复），无巡检中心那类
 *   共享 detail 状态覆盖问题，故不做切换清理；
 * - 方案页"创建表单"跳转携带 ?tab=records&planId=，外壳监听 URL 变化
 *   切换页签，planId 由升级表单页的既有挂载逻辑消费。
 */
import React, {useEffect, useState} from 'react';
import {Tabs} from 'antd';
import {useLocation} from 'react-router-dom';
import {AuthDiv} from 'components';
import {history} from 'libs';
import UpgradeRecordIndex from './index';
import PlanManager from './plan/PlanManager';

// 统一入口路径与页签查询参数名（菜单路径与旧路径重定向共用）
export const CENTER_PATH = '/upgrade';
export const TAB_QUERY_KEY = 'tab';

// 页签定义（数组顺序即默认页签优先级）
const TABS = [
  {key: 'records', label: '升级表单'},
  {key: 'plans', label: '升级方案'},
];

// 初始页签：URL ?tab= 指定时优先，否则回退首个页签
function resolveInitialTab(search) {
  const requested = new URLSearchParams(search || '').get(TAB_QUERY_KEY);
  return TABS.some(t => t.key === requested) ? requested : TABS[0].key;
}

function UpgradeCenter() {
  const location = useLocation();
  const [activeTab, setActiveTab] = useState(() => resolveInitialTab(location.search));

  // 外壳已挂载时响应 URL 变化（方案页"创建表单"带 planId 跳入表单页签）
  useEffect(() => {
    const requested = resolveInitialTab(location.search);
    if (requested !== activeTab) setActiveTab(requested);
  }, [location.search]);  // eslint-disable-line react-hooks/exhaustive-deps

  function handleTabChange(key) {
    if (key === activeTab) return;
    setActiveTab(key);
    // 页签状态入 URL（replace 不产生历史记录）；切换即丢弃 planId 等一次性参数
    history.replace(`${CENTER_PATH}?${TAB_QUERY_KEY}=${key}`);
  }

  return (
    <AuthDiv auth="upgrade.upgrade.view">
      <div>
        <Tabs activeKey={activeTab} onChange={handleTabChange}>
          {TABS.map(t => <Tabs.TabPane key={t.key} tab={t.label}/>)}
        </Tabs>
        {/* 只挂载当前页签的页面组件（原页面自带数据加载与权限控制，
            embedded 仅用于隐藏升级表单页自身的完整面包屑，页面路径
            由全局 Header 面包屑统一显示） */}
        {activeTab === 'records' && <UpgradeRecordIndex embedded/>}
        {activeTab === 'plans' && <PlanManager/>}
      </div>
    </AuthDiv>
  );
}

export default UpgradeCenter;

/**
 * 旧升级方案独立路径兼容跳转（routes.js 保留 /upgrade/plans 隐藏路由）。
 * 挂载即替换到升级中心方案页签，并保留旧 URL 上的其余查询参数。
 */
export function UpgradeCenterRedirect({tab, location}) {
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
