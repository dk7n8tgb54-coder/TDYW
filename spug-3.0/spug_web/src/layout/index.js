/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState, useEffect } from 'react';
import { Switch, Route } from 'react-router-dom';
import { Layout } from 'antd';
import { NotFound } from 'components';
import ExpirationReminderNotification from 'components/ExpirationReminderNotification';
import { licenseReminderConfig, approvalReminderConfig } from 'components/expirationReminderConfigs';
import ContractAgreementReminderNotification from 'components/ContractAgreementReminderNotification';
import Sider from './Sider';
import Header from './Header';
import Footer from './Footer'
import routes from '../routes';
import radioLicenseBadge from './RadioLicenseBadgeStore';
import approvalBadge from './ApprovalBadgeStore';
import coopTaskBadge from './CoopTaskBadgeStore';
import alertStore from './AlertStore';
import { hasPermission } from 'libs';
import styles from './layout.module.less';

function initRoutes(Routes, routes) {
  for (let route of routes) {
    if (route.component) {
      if (!route.auth || hasPermission(route.auth)) {
        Routes.push(<Route exact key={route.path} path={route.path} component={route.component}/>)
      }
    } else if (route.child) {
      initRoutes(Routes, route.child)
    }
  }
}

export default function () {
  const [viewportWidth, setViewportWidth] = useState(() => window.innerWidth);
  const [collapsed, setCollapsed] = useState(() => window.innerWidth < 992)
  const [Routes, setRoutes] = useState([]);
  const isPhone = viewportWidth < 576;

  useEffect(() => {
    let previousWidth = window.innerWidth;
    const handleResize = () => {
      const width = window.innerWidth;
      setViewportWidth(width);
      // Crossing the desktop breakpoint applies the responsive default. A user can
      // still manually toggle the sider after it has been applied.
      if ((previousWidth >= 992 && width < 992) || (previousWidth < 992 && width >= 992)) {
        setCollapsed(width < 992);
      }
      previousWidth = width;
    };
    window.addEventListener('resize', handleResize);
    handleResize();
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  useEffect(() => {
    const Routes = [];
    initRoutes(Routes, routes);
    setRoutes(Routes)
    // 启动无线电台执照菜单红点轮询
    radioLicenseBadge.start();
    approvalBadge.start();
    coopTaskBadge.start();
    alertStore.start();
    return () => {
      radioLicenseBadge.stop();
      approvalBadge.stop();
      coopTaskBadge.stop();
      alertStore.stop();
    }
  }, [])

  return (
    <Layout style={{minWidth: 0, width: '100%'}}>
      <Sider collapsed={collapsed} isPhone={isPhone}/>
      <Layout style={{height: '100vh', display: 'flex', flexDirection: 'column', flex: 1, minWidth: 0}}>
        <Header collapsed={collapsed} toggle={() => setCollapsed(!collapsed)}/>
        <Layout.Content className={styles.content} id="spug-container" style={{flex: 1, minWidth: 0, width: '100%', overflow: 'auto'}}>
          <Switch>
            {Routes}
            <Route component={NotFound}/>
          </Switch>
        </Layout.Content>
        <Footer/>
      </Layout>
      <ExpirationReminderNotification config={licenseReminderConfig}/>
      <ExpirationReminderNotification config={approvalReminderConfig}/>
      <ContractAgreementReminderNotification/>
    </Layout>
  )
}
