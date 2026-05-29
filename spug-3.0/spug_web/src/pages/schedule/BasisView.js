/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useEffect, useState } from 'react';
import { observer } from 'mobx-react';
import { Breadcrumb, Row, Col, Spin, message } from 'antd';
import { AuthDiv } from 'components';
import StaffList from './StaffList';
import ShiftList from './ShiftList';
import store from './stores';

// 【优化】命名组件，便于 React DevTools 调试
function BasisView() {
  // 【优化】管理加载状态，改善用户体验
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const fetchData = async () => {
      try {
        setIsLoading(true);
        // 【优化】并行请求，独立错误处理
        await Promise.all([
          store.fetchStaffList().catch(e => {
            console.error('[排班] 员工列表加载失败:', e);
            message.error('员工列表加载失败');
          }),
          store.fetchShiftList().catch(e => {
            console.error('[排班] 班次列表加载失败:', e);
            message.error('班次列表加载失败');
          })
        ]);
      } finally {
        setIsLoading(false);
      }
    };

    fetchData();
  }, []);

  return (
    <AuthDiv auth="schedule.staff.view|schedule.shift.view">
      <Breadcrumb>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>排班管理</Breadcrumb.Item>
        <Breadcrumb.Item>基础数据</Breadcrumb.Item>
      </Breadcrumb>

      {/* 【优化】全局加载态，提升用户体验 */}
      <Spin spinning={isLoading} tip="正在加载基础数据...">
        <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
          <Col span={12}>
            <StaffList />
          </Col>
          <Col span={12}>
            <ShiftList />
          </Col>
        </Row>
      </Spin>
    </AuthDiv>
  );
}

export default observer(BasisView);
