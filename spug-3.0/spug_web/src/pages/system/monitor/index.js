import React, { useEffect, useState } from 'react';
import { observer } from 'mobx-react';
import { Tabs } from 'antd';
import { useLocation } from 'react-router-dom';
import {AuthDiv} from 'components';
import AlertIndex from '../alert';
import DataQualityIndex from '../dataQuality';
import PlatformHealth from '../alert/PlatformHealth';

const { TabPane } = Tabs;

export default observer(function SystemMonitor() {
  const location = useLocation();
  const requestedTab = new URLSearchParams(location.search).get('tab');
  const requestedKey = requestedTab === 'alerts' || requestedTab === 'quality' ? requestedTab : 'health';
  const [activeKey, setActiveKey] = useState(requestedKey);

  // 同一路由切换 query 参数时同步当前 Tab，例如从平台健康跳转系统告警。
  useEffect(() => {
    setActiveKey(requestedKey);
  }, [requestedKey]);

  return <AuthDiv auth="system.alert.view">
    <Tabs activeKey={activeKey} onChange={setActiveKey} destroyInactiveTabPane>
      <TabPane tab="平台健康" key="health"><PlatformHealth /></TabPane>
      <TabPane tab="系统告警" key="alerts"><AlertIndex embedded /></TabPane>
      <TabPane tab="数据质量" key="quality"><DataQualityIndex embedded /></TabPane>
    </Tabs>
  </AuthDiv>;
});
