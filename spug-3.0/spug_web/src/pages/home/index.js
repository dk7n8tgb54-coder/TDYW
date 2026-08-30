/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { Row, Col } from 'antd';
import { Breadcrumb } from 'components';
import CoopTaskOverview from './CoopTaskOverview';
import ExpiryOverview from './ExpiryOverview';
import FaultOverview from './FaultOverview';
import UpgradeOverview from './UpgradeOverview';
import InterferenceOverview from './InterferenceOverview';
import AnnouncementPanel from './AnnouncementPanel';
import ReminderPanel from './ReminderPanel';

function HomeIndex() {
  return (
    <div>
      <Breadcrumb>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>工作台</Breadcrumb.Item>
      </Breadcrumb>

      {/* 第1行：公告 + 提醒事项 */}
      <Row gutter={12} style={{ marginBottom: 12 }}>
        <Col span={16}>
          <AnnouncementPanel />
        </Col>
        <Col span={8}>
          <ReminderPanel />
        </Col>
      </Row>

      {/* 第2行：协作任务（我发起的 + 待我交付） */}
      <CoopTaskOverview />

      {/* 第3行：到期提醒 + 最近故障 + 进行中升级 + 干扰统计 */}
      <Row gutter={12} style={{ marginBottom: 12 }}>
        <Col span={6}>
          <ExpiryOverview />
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
