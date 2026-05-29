/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Card, Button, Tabs, DatePicker } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { Chart, Geom, Axis, Tooltip, Legend } from 'bizcharts';
import store from './statisticsStore';

const { TabPane } = Tabs;
const { RangePicker } = DatePicker;

// 干扰类型颜色映射
const TYPE_COLOR_MAP = {
  '同频干扰': '#ff4d4f',
  '邻频干扰': '#faad14',
  '互调干扰': '#1890ff',
  '其他干扰': '#52c41a',
  '杂音干扰': '#722ed1',
};

// 预定义频率颜色池
const FREQUENCY_COLORS = [
  '#1890ff', '#52c41a', '#faad14', '#722ed1', '#eb2f96',
  '#13c2c2', '#f5222d', '#fa8c16', '#a0d911', '#ad8b00'
];

// 频率颜色缓存，确保相同频率颜色一致
const frequencyColorCache = {};

const getFrequencyColor = (frequency) => {
  if (frequencyColorCache[frequency]) {
    return frequencyColorCache[frequency];
  }
  // 使用频率字符串的hashCode来分配颜色，确保相同频率颜色相同
  let hash = 0;
  for (let i = 0; i < frequency.length; i++) {
    hash = frequency.charCodeAt(i) + ((hash << 5) - hash);
  }
  const index = Math.abs(hash) % FREQUENCY_COLORS.length;
  const color = FREQUENCY_COLORS[index];
  frequencyColorCache[frequency] = color;
  return color;
};

class InterferenceStatistics extends React.Component {
  componentDidMount() {
    store.fetchStatistics();
  }

  render() {
    // 数据预处理：聚合数据
    const aggregateData = (stats, groupField) => {
      const aggregated = {};
      stats.forEach(item => {
        const month = item.date.substring(0, 7); // YYYY-MM
        const group = item[groupField];
        const count = item.count;
        
        const key = `${month}-${group}`;
        if (!aggregated[key]) {
          aggregated[key] = { time: month, [groupField]: group, count: 0 };
        }
        aggregated[key].count += count;
      });
      
      return Object.values(aggregated);
    };

    // 自定义Tooltip（按类型统计）
    const typeCustomTooltip = (title, items) => {
      if (!items || items.length === 0) return null;

      // 过滤出当前时间点的原始数据
      const currentTimeItems = store.typeStats.filter(item => item.date.substring(0, 7) === title);
      // 按干扰类型分组
      const groupedByType = currentTimeItems.reduce((acc, item) => {
        if (!acc[item.type]) {
          acc[item.type] = [];
        }
        acc[item.type].push(item);
        return acc;
      }, {});

      return (
        <div style={{ padding: '8px 12px', minWidth: 200, backgroundColor: 'rgba(255,255,255,0.95)', borderRadius: 4 }}>
          <div style={{ fontWeight: 'bold', marginBottom: 8, fontSize: 14 }}>{title}</div>
          {Object.entries(groupedByType).map(([type, dateItems]) => {
            const totalCount = dateItems.reduce((sum, item) => sum + item.count, 0);
            const color = TYPE_COLOR_MAP[type] || '#1890ff';
            return (
              <div key={type} style={{ marginBottom: 8 }}>
                <div style={{ display: 'flex', alignItems: 'center', marginBottom: 4 }}>
                  <span
                    style={{
                      width: 8,
                      height: 8,
                      borderRadius: '50%',
                      backgroundColor: color,
                      marginRight: 8,
                    }}
                  />
                  <span style={{ fontWeight: 500 }}>{type}</span>
                  <span style={{ marginLeft: 'auto', color: '#333' }}>总次数：{totalCount}</span>
                </div>
                {dateItems.map((item, index) => (
                  <div
                    key={index}
                    style={{
                      marginLeft: 16,
                      fontSize: 12,
                      color: '#666',
                      marginBottom: 2,
                    }}
                  >
                    - {item.date}：{item.count}次
                  </div>
                ))}
              </div>
            );
          })}
        </div>
      );
    };

    // 自定义Tooltip（按频率统计）
    const freqCustomTooltip = (title, items) => {
      if (!items || items.length === 0) return null;

      // 过滤出当前时间点的原始数据
      const currentTimeItems = store.frequencyStats.filter(item => item.date.substring(0, 7) === title);
      // 按频率分组
      const groupedByFreq = currentTimeItems.reduce((acc, item) => {
        if (!acc[item.frequency]) {
          acc[item.frequency] = [];
        }
        acc[item.frequency].push(item);
        return acc;
      }, {});

      // 按频率排序
      const sortedFreqs = Object.keys(groupedByFreq).sort();

      return (
        <div style={{ padding: '8px 12px', minWidth: 200, backgroundColor: 'rgba(255,255,255,0.95)', borderRadius: 4 }}>
          <div style={{ fontWeight: 'bold', marginBottom: 8, fontSize: 14 }}>{title}</div>
          {sortedFreqs.map((freq, index) => {
            const freqItems = groupedByFreq[freq];
            const totalCount = freqItems.reduce((sum, item) => sum + item.count, 0);
            const color = getFrequencyColor(freq);
            return (
              <div key={freq} style={{ marginBottom: 8 }}>
                <div style={{ display: 'flex', alignItems: 'center', marginBottom: 4 }}>
                  <span
                    style={{
                      width: 8,
                      height: 8,
                      borderRadius: '50%',
                      backgroundColor: color,
                      marginRight: 8,
                    }}
                  />
                  <span style={{ fontWeight: 500 }}>{freq}</span>
                  <span style={{ marginLeft: 'auto', color: '#333' }}>总次数：{totalCount}</span>
                </div>
                {freqItems.map((item, idx) => (
                  <div
                    key={idx}
                    style={{
                      marginLeft: 16,
                      fontSize: 12,
                      color: '#666',
                      marginBottom: 2,
                    }}
                  >
                    - {item.date}：{item.count}次
                  </div>
                ))}
              </div>
            );
          })}
        </div>
      );
    };

    // 渲染堆叠柱状图
    const renderStackedChart = (chartData, groupField, customTooltip, titleText) => {
      if (!chartData || chartData.length === 0) {
        return <div style={{ textAlign: 'center', padding: '60px 0', color: '#999' }}>暂无数据</div>;
      }

      return (
        <div style={{ width: '100%', height: 550 }}>
          <Chart
            data={chartData}
            autoFit
            height={450}
            padding={[60, 40, 60, 80]}
          >
            {/* X轴：时间 */}
            <Axis
              name="time"
              title={{
                text: '时间（月）',
                style: { fill: '#333', fontSize: 12 },
              }}
              label={{
                style: { fill: '#666', fontSize: 12 },
              }}
            />
            {/* Y轴：干扰次数 */}
            <Axis
              name="count"
              title={{
                text: '干扰次数',
                style: { fill: '#333', fontSize: 12 },
              }}
              label={{
                style: { fill: '#666', fontSize: 12 },
              }}
            />
            {/* 图例 */}
            <Legend
              name={groupField}
              position="top"
              itemName={{
                style: { fill: '#333', fontSize: 12 },
              }}
            />
            {/* 自定义Tooltip */}
            <Tooltip
              showCrosshairs={false}
              showMarkers={false}
              customContent={customTooltip}
            />
            {/* 堆叠柱状图 */}
            <Geom
              type="interval"
              position="time*count"
              color={[
                groupField,
                groupField === 'type'
                  ? (val) => TYPE_COLOR_MAP[val] || '#1890ff'
                  : (val) => getFrequencyColor(val)
              ]}
              adjust={[
                {
                  type: 'stack',
                },
              ]}
            />
          </Chart>
        </div>
      );
    };

    const typeChartData = aggregateData(store.typeStats, 'type');
    const freqChartData = aggregateData(store.frequencyStats, 'frequency');

    return (
      <Card
        title="干扰统计"
        extra={
          <div>
            <RangePicker
              value={store.dateRange}
              onChange={(dates) => store.setDateRange(dates)}
              style={{ marginRight: 16 }}
            />
            <Button icon={<ReloadOutlined />} onClick={store.fetchStatistics}>
              刷新
            </Button>
          </div>
        }
      >
        <Tabs defaultActiveKey="frequency">
          <TabPane tab="按频率统计" key="frequency">
            <Card title="干扰趋势分析（按月）">
              {renderStackedChart(freqChartData, 'frequency', freqCustomTooltip, '频率')}
            </Card>
          </TabPane>
          <TabPane tab="按类型统计" key="type">
            <Card title="干扰趋势分析（按月）">
              {renderStackedChart(typeChartData, 'type', typeCustomTooltip, '干扰类型')}
            </Card>
          </TabPane>
        </Tabs>
      </Card>
    )
  }
}

export default observer(InterferenceStatistics);
