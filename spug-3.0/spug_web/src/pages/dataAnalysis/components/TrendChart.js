/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { Card, Empty, Skeleton } from 'antd';
import { Chart, Geom, Axis, Tooltip, Legend } from 'bizcharts';

/**
 * 月度趋势折线图。
 * data: [{ month: '2026-01', count: 3 }, ...]
 * title: 卡片标题
 * loading: 是否加载中
 */
export default function TrendChart({ title, data, loading }) {
  const chartData = (data || []).map(item => ({
    month: item.month,
    count: Number(item.count) || 0,
  }));

  return (
    <Card title={title} size="small" style={{ marginBottom: 16 }}>
      {loading ? (
        <Skeleton active paragraph={{ rows: 4 }} />
      ) : chartData.length === 0 ? (
        <Empty description="暂无数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <Chart height={300} data={chartData} forceFit>
          <Axis name="month" />
          <Axis name="count" />
          <Tooltip
            crosshairs={{ type: 'y' }}
            showTitle={true}
          />
          <Geom type="line" position="month*count" size={2}
            shape="smooth"
            color="#1890ff"
          />
          <Geom type="point" position="month*count" size={4}
            shape="circle"
            color="#1890ff"
            style={{ stroke: '#fff', lineWidth: 1 }}
          />
        </Chart>
      )}
    </Card>
  );
}
