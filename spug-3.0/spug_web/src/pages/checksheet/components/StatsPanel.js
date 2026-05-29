/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { Statistic, Space } from 'antd';

export default function StatsPanel({ stats }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <Space size="large">
        <Statistic title="总检查项" value={stats.total} />
        <Statistic title="正常" value={stats.normal} valueStyle={{ color: '#52c41a' }} />
        <Statistic title="异常" value={stats.abnormal} valueStyle={{ color: '#ff4d4f' }} />
        <Statistic title="未检查" value={stats.unchecked} valueStyle={{ color: '#d9d9d9' }} />
      </Space>
    </div>
  );
}
