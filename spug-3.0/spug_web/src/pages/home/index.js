/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { Row, Col } from 'antd';
import { Breadcrumb } from 'components';
import RunlogOverview from './RunlogOverview';
import DocumentOverview from './DocumentOverview';
import FaultOverview from './FaultOverview';
import UpgradeOverview from './UpgradeOverview';
import InterferenceOverview from './InterferenceOverview';

function HomeIndex() {
  return (
    <div>
      <Breadcrumb>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>工作台</Breadcrumb.Item>
      </Breadcrumb>

      {/* 第1行：运行日志概览 */}
      <RunlogOverview />

      {/* 第2行：资料库新增 + 故障处置 + 升级动态 + 干扰统计 */}
      <Row gutter={12} style={{ marginBottom: 12 }}>
        <Col span={6}>
          <DocumentOverview />
        </Col>
        <Col span={6}>
          <FaultOverview />
        </Col>
        <Col span={6}>
          <UpgradeOverview />
        </Col>
        <Col span={6}>
          <InterferenceOverview />
        </Col>
      </Row>
    </div>
  );
}

export default HomeIndex;
