import React, { useEffect } from 'react';
import { observer } from 'mobx-react';
import { Alert, Button, Card, Col, Empty, Radio, Row, Spin, Statistic, Table, Tag } from 'antd';
import { Chart, Geom, Axis, Tooltip as ChartTooltip, Legend } from 'bizcharts';
import store from './healthStore';
import DiskTrendChart from './DiskTrendChart';
import {buildAxisTicks, formatAxisTime} from './chartAxis';
import {history} from 'libs';

const STATES = {
  healthy: {label: '健康', color: 'green', type: 'success'},
  degraded: {label: '降级', color: 'gold', type: 'warning'},
  unavailable: {label: '不可用', color: 'red', type: 'error'},
  unknown: {label: '未知', color: 'default', type: 'info'},
};

const stateMeta = state => STATES[state] || STATES.unknown;

export default observer(function PlatformHealth() {
  useEffect(() => { store.fetch(); }, []);
  const latest = store.items[store.items.length - 1] || {};
  const meta = stateMeta(store.state);
  // 横轴按数据点抽样约 10 个刻度，粒度随 24h/48h/7d 跨度变化
  const tickLabels = buildAxisTicks(store.items.map(item => new Date(item.bucket_start)), store.hours);
  const chartData = store.items.map(item => ({
    time: formatAxisTime(new Date(item.bucket_start)),
    requests: item.request_count,
    errors: item.request_count ? +(100 * (item.app_server_error_count + item.gateway_error_count) / item.request_count).toFixed(2) : 0,
  }));
  const summaryColumns = [
    {title: '日期', dataIndex: 'date'},
    {title: '请求量', dataIndex: 'request_count'},
    {title: '系统错误', dataIndex: 'system_error_count'},
    {title: '慢请求', dataIndex: 'slow_count'},
    {title: '不可用窗口', dataIndex: 'unavailable_windows'},
    {title: '未知窗口', dataIndex: 'unknown_windows'},
  ];
  return <>
    <Spin spinning={store.loading}>
      <Card size="small" title="平台健康" extra={<Radio.Group size="small" value={store.hours} onChange={e => store.setHours(e.target.value)}>
        <Radio.Button value={24}>24h</Radio.Button><Radio.Button value={48}>48h</Radio.Button><Radio.Button value={168}>7d</Radio.Button>
      </Radio.Group>}>
        <Alert type={meta.type} showIcon message={<span>当前状态：<Tag color={meta.color}>{meta.label}</Tag></span>}
          description={store.state === 'unknown' ? '监控数据缺失，不能据此判断平台正常。' : '平台健康仅展示运行摘要，告警详情请前往系统告警。'}
          action={<Button type="link" size="small" onClick={() => history.push('/maintenance/alert?tab=alerts')}>查看系统告警</Button>} />
        <Row gutter={16} style={{marginTop: 16}}>
          <Col span={6}><Statistic title="请求量" value={latest.request_count || 0} /></Col>
          <Col span={6}><Statistic title="错误率" value={latest.request_count ? ((latest.app_server_error_count + latest.gateway_error_count) * 100 / latest.request_count).toFixed(2) : '-'} suffix="%" /></Col>
          <Col span={6}><Statistic title="平均耗时" value={latest.average_ms == null ? '-' : latest.average_ms} suffix="ms" /></Col>
          <Col span={6}><Statistic title="探活成功率" value={latest.probe_success_rate == null ? '-' : (latest.probe_success_rate * 100).toFixed(1)} suffix="%" /></Col>
        </Row>
        {chartData.length ? <div style={{width: '100%'}}>
          <Chart data={chartData} forceFit height={260} padding={[30, 20, 50, 50]}>
            <Axis name="time" label={{autoRotate: false, formatter: text => tickLabels.get(text) || '', style: {fontSize: 10}}} /><Axis name="requests" />
            <ChartTooltip /><Legend /><Geom type="line" position="time*requests" color="#1677ff" />
          </Chart>
        </div> : <Empty description="监控数据缺失/未知" style={{margin: '32px 0'}} />}
        <Table size="small" style={{marginTop: 16}} rowKey="date" columns={summaryColumns} dataSource={store.summary} pagination={false} />
      </Card>
    </Spin>
    <div style={{marginTop: 16}}>
      <DiskTrendChart/>
    </div>
  </>;
});
