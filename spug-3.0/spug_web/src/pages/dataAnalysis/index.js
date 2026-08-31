/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { Tabs, DatePicker, Space, Button } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import moment from 'moment';
import { observer } from 'mobx-react';
import { useLocation } from 'react-router-dom';
import { Breadcrumb } from 'components';
import { hasPermission } from 'libs';
import store, { TABS, MAX_RANGE_DAYS, getDatePresets } from './store';
import Overview from './Overview';
import FaultAnalysis from './FaultAnalysis';
import InterferenceAnalysis from './InterferenceAnalysis';
import DeviceAnalysis from './DeviceAnalysis';
import UpgradeAnalysis from './UpgradeAnalysis';

const { RangePicker } = DatePicker;

// Tab key -> 组件映射
const TAB_COMPONENTS = {
  overview: Overview,
  fault: FaultAnalysis,
  interference: InterferenceAnalysis,
  device: DeviceAnalysis,
  upgrade: UpgradeAnalysis,
};

function DataAnalysisIndex() {
  const location = useLocation();
  // 过滤出有权限的 Tab
  const visibleTabs = TABS.filter(tab => hasPermission(tab.perm));
  // 日期快捷选项（组件生命周期内固定，避免每次渲染重建导致面板闪烁）
  const datePresets = useMemo(() => getDatePresets(), []);
  // 面板中已选的起止日期（选择过程中），用于限制跨度
  const [pickingDates, setPickingDates] = useState(null);

  // 可选日期约束：不允许选择未来日期，起止跨度不超过 MAX_RANGE_DAYS
  const disabledDate = (current) => {
    if (!current) return false;
    if (current.isAfter(moment(), 'day')) return true;
    if (!pickingDates || pickingDates.length === 0) return false;
    const [start, end] = pickingDates;
    if (!start || end) return false;
    const limit = MAX_RANGE_DAYS - 1;
    return current.isAfter(moment(start).add(limit, 'days'))
      || current.isBefore(moment(start).subtract(limit, 'days'));
  };

  // 挂载时初始化：优先使用 URL ?tab= 指定的 Tab（如首页卡片跳转），无权限时回退首个可用 Tab
  useEffect(() => {
    if (visibleTabs.length === 0) return;
    const query = new URLSearchParams(location.search);
    const requested = query.get('tab');
    const requestedTab = TABS.find(t => t.key === requested && hasPermission(t.perm));
    const currentTab = TABS.find(t => t.key === store.activeTab);
    if ((!currentTab || !hasPermission(currentTab.perm)) && requestedTab) {
      store.setActiveTab(requestedTab.key);
      store.fetchTab(requestedTab.key);
    } else if (!currentTab || !hasPermission(currentTab.perm)) {
      // 当前 Tab 无权限，切到第一个有权限的
      const firstTab = visibleTabs[0];
      store.setActiveTab(firstTab.key);
      store.fetchTab(firstTab.key);
    } else if (!store.getData(store.activeTab)) {
      // 有权限但还没加载过数据
      store.fetchTab(store.activeTab);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Tab 切换时加载数据
  const handleTabChange = (key) => {
    store.setActiveTab(key);
    if (!store.getData(key)) {
      store.fetchTab(key);
    }
  };

  // 日期范围变化时重新加载当前 Tab
  const handleDateChange = (dates) => {
    if (dates && dates.length === 2) {
      store.setDateRange(dates);
      store.fetchTab(store.activeTab);
    }
  };

  // 刷新
  const handleRefresh = () => {
    store.fetchTab(store.activeTab);
  };

  const ActiveComponent = TAB_COMPONENTS[store.activeTab] || null;

  return (
    <div>
      <Breadcrumb>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>数据分析</Breadcrumb.Item>
      </Breadcrumb>

      {visibleTabs.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '60px 0', color: '#999' }}>
          您没有数据分析模块的访问权限
        </div>
      ) : (
        <div style={{ marginTop: 16 }}>
          <Tabs
            activeKey={store.activeTab}
            onChange={handleTabChange}
            tabBarExtraContent={
              <Space>
                <RangePicker
                  value={store.dateRange}
                  onChange={handleDateChange}
                  allowClear={false}
                  ranges={datePresets}
                  disabledDate={disabledDate}
                  onCalendarChange={setPickingDates}
                  onOpenChange={(open) => { if (!open) setPickingDates(null); }}
                />
                <Button
                  icon={<ReloadOutlined />}
                  onClick={handleRefresh}
                  loading={store.isFetching(store.activeTab)}
                >
                  刷新
                </Button>
              </Space>
            }
          >
            {visibleTabs.map(tab => (
              <Tabs.TabPane key={tab.key} tab={tab.label} />
            ))}
          </Tabs>

          {ActiveComponent && <ActiveComponent />}
        </div>
      )}
    </div>
  );
}

export default observer(DataAnalysisIndex);
