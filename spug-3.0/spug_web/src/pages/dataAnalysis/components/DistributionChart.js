/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { Card, Empty, Skeleton, Radio } from 'antd';
import { Chart, Geom, Axis, Tooltip, Legend, Coord } from 'bizcharts';

/**
 * 分布图表（饼图 / 柱状图切换）。
 * data: [{ name: 'A', count: 12, percent: 60.0 }, ...]
 * title: 卡片标题
 * loading: 是否加载中
 */
export default function DistributionChart({ title, data, loading }) {
  const [chartType, setChartType] = React.useState('pie');

  const chartData = (data || []).map(item => ({
    name: item.name,
    count: Number(item.count) || 0,
    percent: Number(item.percent) || 0,
  }));

  const extra = (
    <Radio.Group
      size="small"
      value={chartType}
      onChange={e => setChartType(e.target.value)}
    >
      <Radio.Button value="pie">饼图</Radio.Button>
      <Radio.Button value="bar">柱图</Radio.Button>
    </Radio.Group>
  );

  return (
    <Card title={title} size="small" extra={extra} style={{ marginBottom: 16 }}>
      {loading ? (
        <Skeleton active paragraph={{ rows: 4 }} />
      ) : chartData.length === 0 ? (
        <Empty description="暂无数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : chartType === 'pie' ? (
        <Chart height={300} data={chartData} forceFit>
          <Coord type="theta" radius={0.75} />
          <Tooltip
            showTitle={false}
            itemTpl='<li><span style="background-color:{color};" class="g2-tooltip-marker"></span>{name}: {count} ({percent}%)</li>'
          />
          <Geom
            type="intervalStack"
            position="count"
            color="name"
            style={{ lineWidth: 1, stroke: '#fff' }}
          >
          </Geom>
          <Legend name="name" position="right" />
        </Chart>
      ) : (
        <Chart height={300} data={chartData} forceFit>
          <Axis name="name" />
          <Axis name="count" />
          <Tooltip />
          <Geom type="interval" position="name*count" color="#1890ff" />
        </Chart>
      )}
    </Card>
  );
}
