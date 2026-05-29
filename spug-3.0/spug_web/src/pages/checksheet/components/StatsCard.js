/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { Card, Row, Col, Statistic } from 'antd';

export default function StatsCard({ stats }) {
  return (
    <div style={{ marginBottom: 24 }}>
      <Card size="small" style={{ textAlign: 'center', backgroundColor: '#f6ffed' }}>
        <Row gutter={16}>
          <Col span={6}>
            <Statistic title="总检查项（全部项目）" value={stats.total} />
          </Col>
          <Col span={6}>
            <Statistic title="正常" value={stats.normal} valueStyle={{ color: '#52c41a' }} />
          </Col>
          <Col span={6}>
            <Statistic title="异常" value={stats.abnormal} valueStyle={{ color: '#ff4d4f' }} />
          </Col>
          <Col span={6}>
            <Statistic title="未检查" value={stats.unchecked} valueStyle={{ color: '#d9d9d9' }} />
          </Col>
        </Row>
      </Card>
    </div>
  );
}
