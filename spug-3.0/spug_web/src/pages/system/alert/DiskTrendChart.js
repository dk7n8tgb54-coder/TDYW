import React, { useEffect, useState } from 'react';
import { observer } from 'mobx-react';
import { Button, Card, Empty, Radio, Space, Spin } from 'antd';
import { Chart, Geom, Axis, Tooltip as ChartTooltip, Legend } from 'bizcharts';
import {buildAxisTicks, formatAxisTime} from './chartAxis';
import store from './store';

// 磁盘趋势四条曲线样式：三类存储各用一种实线颜色，
// 总计用醒目颜色的虚线加粗，与分类曲线明显区分（由后端计算，前端不重复相加）
const TOTAL_SERIES_LABEL = '三类存储总计';
const TREND_COLORS = {
  '文档存储': '#5B8FF9',
  '分片存储': '#5AD8A6',
  '媒体存储': '#F6BD16',
  '三类存储总计': '#E8684A',
};
const trendColor = type => TREND_COLORS[type] || '#999999';

export default observer(function DiskTrendChart() {
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    store.fetchTrend();
  }, []);

  // 将 store.trendData 展平为 bizcharts 数据格式
  const chartData = [];
  const tickLabels = new Map();
  let hasData = false;
  store.trendData.forEach(series => {
    // 各序列时间点一致，横轴刻度按序列分别抽样后合并
    buildAxisTicks(series.points.map(p => new Date(p.time * 1000)), store.trendHours)
      .forEach((label, key) => tickLabels.set(key, label));
    series.points.forEach(p => {
      chartData.push({
        time: formatAxisTime(new Date(p.time * 1000)),
        value: +(p.value / 1024 / 1024 / 1024).toFixed(2),  // bytes -> GB
        type: series.label,
      });
      hasData = true;
    });
  });

  return (
    <Card
      size="small"
      title="磁盘使用趋势"
      extra={
        <Space>
          <Radio.Group
            size="small"
            value={store.trendHours}
            onChange={e => store.setTrendHours(e.target.value)}>
            <Radio.Button value={6}>6h</Radio.Button>
            <Radio.Button value={24}>24h</Radio.Button>
            <Radio.Button value={72}>3天</Radio.Button>
            <Radio.Button value={168}>7天</Radio.Button>
          </Radio.Group>
          <Button size="small" type="text" onClick={() => setCollapsed(!collapsed)}>
            {collapsed ? '展开' : '收起'}
          </Button>
        </Space>
      }
      bodyStyle={{display: collapsed ? 'none' : 'block'}}>
      <Spin spinning={store.trendLoading}>
        {hasData ? (
          <div style={{width: '100%'}}>
            <Chart
              data={chartData}
              forceFit
              height={280}
              padding={[30, 20, 60, 60]}
              scale={{value: {min: 0, alias: '已用(GB)'}}}>
              <Axis name="time" label={{autoRotate: false, formatter: text => tickLabels.get(text) || '', style: {fontSize: 10}}} />
              <Axis name="value" title={{text: '已用空间(GB)'}} />
              <Legend name="type" position="top" />
              <ChartTooltip showCrosshairs />
              <Geom
                type="line"
                position="time*value"
                color={['type', trendColor]}
                shape={['type', type => (type === TOTAL_SERIES_LABEL ? 'dash' : 'smooth')]}
                size={['type', type => (type === TOTAL_SERIES_LABEL ? 3 : 2)]}
              />
              <Geom type="point" position="time*value" color={['type', trendColor]} size={3} shape="circle" />
            </Chart>
          </div>
        ) : (
          <Empty description="暂无趋势数据（数据采集需运行至少 6 小时）" style={{margin: '40px 0'}} />
        )}
      </Spin>
    </Card>
  );
});
