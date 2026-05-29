/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useEffect, useState } from 'react';
import { observer } from 'mobx-react';
import { Breadcrumb, Card, Row, Col, Space, Button, DatePicker, Spin } from 'antd';
import { PlusOutlined, SyncOutlined, SwapOutlined } from '@ant-design/icons';
import { AuthDiv, AuthButton } from 'components';
import CalendarView from './CalendarView';
import SwapList from './SwapList';
import SubstituteList from './SubstituteList';
import ShiftAdjust from './ShiftAdjust';
import store, { initializeStores } from './stores';

export default observer(function () {
  const [showShiftAdjust, setShowShiftAdjust] = useState(false);
  const [initError, setInitError] = useState(null);

  console.log('[SchedulePage] 组件渲染, isInitialized:', store.isInitialized);

  useEffect(() => {
    console.log('[SchedulePage] useEffect 执行，调用 initializeStores');
    // 修复P0-1：使用统一初始化函数，防止竞态条件
    initializeStores().then(() => {
      console.log('[SchedulePage] initializeStores 完成');
    }).catch(error => {
      console.error('[SchedulePage] Failed to initialize stores:', error);
      setInitError('数据加载失败，请刷新页面重试');
    });
  }, []);

  const handleMonthChange = (date) => {
    store.setCurrentDate(date);
    store.fetchSchedule(date.year(), date.month() + 1);
  };

  // 显示加载状态
  if (!store.isInitialized && !initError) {
    return (
      <AuthDiv auth="schedule.schedule.view">
        <div style={{ textAlign: 'center', padding: '100px' }}>
          <Spin size="large" tip="正在加载排班数据..." />
        </div>
      </AuthDiv>
    );
  }

  // 显示错误状态
  if (initError) {
    return (
      <AuthDiv auth="schedule.schedule.view">
        <div style={{ textAlign: 'center', padding: '100px', color: '#ff4d4f' }}>
          <p>{initError}</p>
          <Button type="primary" onClick={() => window.location.reload()}>
            刷新页面
          </Button>
        </div>
      </AuthDiv>
    );
  }

  return (
    <AuthDiv auth="schedule.schedule.view">
      <Breadcrumb>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>排班管理</Breadcrumb.Item>
        <Breadcrumb.Item>排班日历</Breadcrumb.Item>
      </Breadcrumb>

      <Card
        title={
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span>排班日历</span>
            <Button type="primary" danger icon={<PlusOutlined />} onClick={() => {
              // 将通过ref或回调触发CalendarView中的批量删除
              const event = new CustomEvent('openBatchDelete');
              window.dispatchEvent(event);
            }}>
              按人员批量删除排班
            </Button>
          </div>
        }
      >
        <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
          <Col span={24} style={{ textAlign: 'right' }}>
            <Space>
              <AuthButton
                auth="schedule.schedule.edit"
                type="primary"
                icon={<SwapOutlined />}
                onClick={() => setShowShiftAdjust(true)}
              >
                班次调整
              </AuthButton>
              <Button
                type="primary"
                icon={<SyncOutlined />}
                onClick={() => store.fetchSchedule(store.currentDate.year(), store.currentDate.month() + 1)}
              >
                刷新
              </Button>
            </Space>
          </Col>
        </Row>

        <CalendarView
          currentDate={store.currentDate}
          scheduleList={store.scheduleList}
          onDateChange={(date) => {
            store.setCurrentDate(date);
            store.fetchSchedule(date.year(), date.month() + 1);
          }}
        />
      </Card>

      <Row gutter={[16, 16]} style={{ marginTop: 24 }}>
        <Col span={24}>
          <AuthDiv auth="schedule.swap.view">
            <SwapList />
          </AuthDiv>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 24 }}>
        <Col span={24}>
          <AuthDiv auth="schedule.substitute.view">
            <SubstituteList />
          </AuthDiv>
        </Col>
      </Row>

      {showShiftAdjust && (
        <ShiftAdjust onClose={() => setShowShiftAdjust(false)} />
      )}
    </AuthDiv>
  );
})
