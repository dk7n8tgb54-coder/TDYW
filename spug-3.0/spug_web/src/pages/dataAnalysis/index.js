/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useEffect } from 'react';
import { Tabs, DatePicker, Space, Button } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { observer } from 'mobx-react';
import { Breadcrumb } from 'components';
import { hasPermission } from 'libs';
import store, { TABS } from './store';
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
  // 过滤出有权限的 Tab
  const visibleTabs = TABS.filter(tab => hasPermission(tab.perm));

  // 如果当前 Tab 无权限，切到第一个有权限的
  useEffect(() => {
    if (visibleTabs.length > 0) {
      const currentTab = TABS.find(t => t.key === store.activeTab);
      if (!currentTab || !hasPermission(currentTab.perm)) {
        const firstTab = visibleTabs[0];
        store.setActiveTab(firstTab.key);
        store.fetchTab(firstTab.key);
      }
    }
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
