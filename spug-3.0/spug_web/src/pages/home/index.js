/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { Row, Col } from 'antd';
import { Breadcrumb } from 'components';
import PreviousDayEvents from './PreviousDayEvents';
import DutyToday from './DutyToday';

function HomeIndex() {
  return (
    <div>
      <Breadcrumb>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>工作台</Breadcrumb.Item>
      </Breadcrumb>
      <Row gutter={12}>
        <Col span={16}>
          <PreviousDayEvents/>
        </Col>
        <Col span={8}>
          <DutyToday/>
        </Col>
      </Row>
    </div>
  )
}

export default HomeIndex