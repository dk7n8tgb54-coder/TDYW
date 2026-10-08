/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——巡检中心（2026-09 前端融合外壳）。
 *
 * 将左侧菜单"今日巡检 / 巡检单记录 / 巡检模板"三个入口融合为一个页面，
 * 通过页签访问，减少菜单层级。仅做外壳融合：
 * - 复用原页面组件（InspectionWorksheet / SheetIndex / TemplateIndex），
 *   不合并三者的请求、表单与业务逻辑，不合并 Store；
 * - 页签按权限显示：今日巡检、巡检记录需 equipment_lifecycle.inspection.view，
 *   巡检模板需 equipment_lifecycle.inspection_template.view；
 *   仅有模板权限时默认打开"巡检模板"，有巡检权限时默认打开"今日巡检"；
 * - 当前页签写入 URL（?tab=），刷新后恢复；旧路径经 LegacyRedirect
 *   跳入对应页签并保留 detail 等参数；
 * - 同一时刻只挂载当前页签的页面组件：三个页面复用同一巡检 Store
 *   （store.detail 既承载工作台草稿单也承载记录页详情抽屉），并存挂载会
 *   相互覆盖；切换后今日巡检草稿按既有 localStorage 暂存机制自动恢复；
 * - 切换页签 / 离开页面时清理记录页详情抽屉与模板表单弹窗的遗留状态，
 *   避免残留的 browse detail 在工作台重新挂载时被误判为非草稿单而清空草稿。
 *
 * 页签模式与数据分析页一致（空 TabPane + 权限过滤 + activeKey 受控）。
 */
import React, {useEffect, useState} from 'react';
import {Tabs} from 'antd';
import {useLocation} from 'react-router-dom';
import {runInAction} from 'mobx';
import {Breadcrumb, AuthDiv} from 'components';
import {hasPermission, history} from 'libs';
import InspectionWorksheet from '../inspection/InspectionWorksheet';
import SheetIndex from '../inspection/SheetIndex';
import TemplateIndex from '../inspection/TemplateIndex';
import inspectionStore from '../inspection/store';
import {PERM_I, PERM_ITPL} from '../inspection/constants';
import {CENTER_PATH, TAB_QUERY_KEY} from './constants';

// 页签定义：perm 控制可见性；数组顺序即默认页签优先级
const TABS = [
  {key: 'today', label: '今日巡检', perm: PERM_I.VIEW},
  {key: 'history', label: '巡检记录', perm: PERM_I.VIEW},
  {key: 'templates', label: '巡检模板', perm: PERM_ITPL.VIEW},
];

// 初始页签：URL ?tab= 指定且有权可见时优先，否则回退首个可见页签
function resolveInitialTab(visibleTabs, search) {
  const requested = new URLSearchParams(search || '').get(TAB_QUERY_KEY);
  const requestedTab = visibleTabs.find(t => t.key === requested);
  return requestedTab ? requestedTab.key
    : (visibleTabs.length ? visibleTabs[0].key : null);
}

function InspectionCenter() {
  const location = useLocation();
  const visibleTabs = TABS.filter(t => hasPermission(t.perm));
  const [activeTab, setActiveTab] = useState(
    () => resolveInitialTab(visibleTabs, location.search));

  // 三个页签复用同一巡检 Store：切换/离开时清掉弹层类遗留状态，
  // 防止隐藏状态影响其他页签重新挂载（如遗留详情覆盖工作台草稿单）
  function closeLeftoverOverlays() {
    if (inspectionStore.browseVisible) inspectionStore.closeBrowseDetail();
    if (inspectionStore.tplFormVisible) {
      runInAction(() => {inspectionStore.tplFormVisible = false;});
    }
  }

  useEffect(() => () => closeLeftoverOverlays(), []);   // eslint-disable-line react-hooks/exhaustive-deps

  function handleTabChange(key) {
    if (key === activeTab) return;
    closeLeftoverOverlays();
    setActiveTab(key);
    // 页签状态入 URL（replace 不产生历史记录）；切换即丢弃 detail 等一次性参数
    history.replace(`${CENTER_PATH}?${TAB_QUERY_KEY}=${key}`);
  }

  return (
    <AuthDiv>
      <Breadcrumb>
        <Breadcrumb.Item>设备运行维护管理</Breadcrumb.Item>
        <Breadcrumb.Item>巡视与维护</Breadcrumb.Item>
        <Breadcrumb.Item>日巡视</Breadcrumb.Item>
      </Breadcrumb>
      {visibleTabs.length === 0 ? (
        <div style={{textAlign: 'center', padding: '60px 0', color: '#999'}}>
          您没有巡检业务的访问权限
        </div>
      ) : (
        <div>
          <Tabs activeKey={activeTab} onChange={handleTabChange}>
            {visibleTabs.map(t => <Tabs.TabPane key={t.key} tab={t.label}/>)}
          </Tabs>
          {/* 只挂载当前页签的页面组件（原页面自带数据加载与权限控制，
              embedded 仅用于隐藏各自的完整面包屑） */}
          {activeTab === 'today' && <InspectionWorksheet embedded/>}
          {activeTab === 'history' && <SheetIndex embedded location={location}/>}
          {activeTab === 'templates' && <TemplateIndex embedded/>}
        </div>
      )}
    </AuthDiv>
  );
}

export default InspectionCenter;
export {TABS, resolveInitialTab};
