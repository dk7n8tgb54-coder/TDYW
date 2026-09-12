import React, { useState } from 'react';
import { observer } from 'mobx-react';
import { Tabs } from 'antd';
import { AuthDiv, Breadcrumb } from 'components';
import AlertIndex from '../alert';
import DataQualityIndex from '../dataQuality';
import PlatformHealth from '../alert/PlatformHealth';

const { TabPane } = Tabs;

export default observer(function SystemMonitor() {
  const params = new URLSearchParams(window.location.search);
  const [activeKey, setActiveKey] = useState(params.get('tab') === 'alerts' ? 'alerts' : 'health');
  return <AuthDiv auth="system.alert.view">
    <Breadcrumb><Breadcrumb.Item>运维管理</Breadcrumb.Item><Breadcrumb.Item>系统监控</Breadcrumb.Item></Breadcrumb>
    <Tabs activeKey={activeKey} onChange={setActiveKey} destroyInactiveTabPane>
      <TabPane tab="平台健康" key="health"><PlatformHealth /></TabPane>
      <TabPane tab="系统告警" key="alerts"><AlertIndex embedded /></TabPane>
      <TabPane tab="数据质量" key="quality"><DataQualityIndex embedded /></TabPane>
    </Tabs>
  </AuthDiv>;
});
