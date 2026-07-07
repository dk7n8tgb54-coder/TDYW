/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useEffect, useState } from 'react';
import { observer } from 'mobx-react';
import {
  Card, Row, Col, Statistic, DatePicker, Select, Button, Table, Empty,
  Tag, Progress, Spin, Space,
} from 'antd';
import {
  ReloadOutlined, FileTextOutlined, RiseOutlined, ClockCircleOutlined,
  CheckCircleOutlined, FireOutlined, AlertOutlined,
} from '@ant-design/icons';
import { Chart, Geom, Axis, Tooltip } from 'bizcharts';
import { AuthDiv, Breadcrumb } from 'components';
import store from './statisticsStore';
import { history } from 'libs';

const { RangePicker } = DatePicker;
const { Option } = Select;

// 级别 / 状态 颜色映射（与 Table.js 保持一致）
const SEVERITY_COLOR = { P0: 'red', P1: 'orange', P2: 'green' };
const STATUS_COLOR = {
  in_progress: 'orange', resolved: 'green', verified: 'blue',
  closed: 'default', voided: 'default',
};

const STATUS_OPTIONS = [
  { value: 'in_progress', label: '处理中' },
  { value: 'resolved', label: '已解决' },
  { value: 'verified', label: '已验证' },
  { value: 'closed', label: '已归档' },
  { value: 'voided', label: '已作废' },
];
const SEVERITY_OPTIONS = [
  { value: 'P0', label: 'P0 紧急' },
  { value: 'P1', label: 'P1 重要' },
  { value: 'P2', label: 'P2 一般' },
];

const getValue = value => value ?? 0;

// 分布表格通用列
const distColumns = [
  { title: '分类', dataIndex: 'label', key: 'label' },
  { title: '数量', dataIndex: 'count', key: 'count', width: 70 },
  {
    title: '占比', dataIndex: 'percent', key: 'percent', width: 140,
    render: v => <Progress percent={v} size="small" />,
  },
];

const systemColumns = [
  {
    title: '排名', key: 'rank', width: 60,
    render: (_, __, idx) => idx + 1,
  },
  { title: '关联系统', dataIndex: 'system_name', key: 'system_name' },
  { title: '事件数', dataIndex: 'count', key: 'count', width: 80 },
];

const unclosedColumns = [
  {
    title: '事件标题', dataIndex: 'event_title', key: 'event_title',
    render: (text, record) => (
      <a
        href={`/runlog?view=${record.id}`}
        onClick={(e) => {
          e.preventDefault();
          history.push(`/runlog?view=${record.id}`);
        }}
      >
        {text}
      </a>
    ),
  },
  { title: '关联系统', dataIndex: 'system_name', key: 'system_name', width: 160 },
  {
    title: '级别', dataIndex: 'severity', key: 'severity', width: 80,
    render: v => <Tag color={SEVERITY_COLOR[v]}>{v}</Tag>,
  },
  {
    title: '状态', dataIndex: 'status', key: 'status', width: 90,
    render: (v, r) => <Tag color={STATUS_COLOR[v]}>{r.status_label}</Tag>,
  },
  { title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 150 },
];

const FilterCard = observer(function FilterCard({ data, range, load }) {
  return (
    <Card style={{ marginBottom: 16 }} title="筛选条件" extra={
      <Space>
        <Button onClick={() => { store.resetFilters(); }}>重置</Button>
        <Button type="primary" icon={<ReloadOutlined />} onClick={load}>刷新</Button>
      </Space>
    }>
      <Row gutter={16}>
        <Col span={8}>
          <div style={{ marginBottom: 4, color: '#999' }}>时间范围</div>
          <RangePicker
            style={{ width: '100%' }}
            value={store.f_date_range}
            onChange={v => store.setFilter('date_range', v)}
          />
        </Col>
        <Col span={4}>
          <div style={{ marginBottom: 4, color: '#999' }}>事件类型</div>
          <Select
            style={{ width: '100%' }} allowClear placeholder="全部类型"
            value={store.f_event_type}
            onChange={v => store.setFilter('event_type', v)}
          >
            {store.eventTypes.map(t => (
              <Option key={t.name} value={t.name}>{t.name}</Option>
            ))}
          </Select>
        </Col>
        <Col span={4}>
          <div style={{ marginBottom: 4, color: '#999' }}>关联系统</div>
          <Select
            style={{ width: '100%' }} allowClear showSearch placeholder="全部系统"
            value={store.f_system_name}
            onChange={v => store.setFilter('system_name', v)}
          >
            {store.systemNames.map(s => (
              <Option key={s} value={s}>{s}</Option>
            ))}
          </Select>
        </Col>
        <Col span={4}>
          <div style={{ marginBottom: 4, color: '#999' }}>级别</div>
          <Select
            style={{ width: '100%' }} allowClear placeholder="全部级别"
            value={store.f_severity}
            onChange={v => store.setFilter('severity', v)}
          >
            {SEVERITY_OPTIONS.map(s => (
              <Option key={s.value} value={s.value}>{s.label}</Option>
            ))}
          </Select>
        </Col>
        <Col span={4}>
          <div style={{ marginBottom: 4, color: '#999' }}>状态</div>
          <Select
            style={{ width: '100%' }} allowClear placeholder="全部状态"
            value={store.f_status}
            onChange={v => store.setFilter('status', v)}
          >
            {STATUS_OPTIONS.map(s => (
              <Option key={s.value} value={s.value}>{s.label}</Option>
            ))}
          </Select>
        </Col>
      </Row>
      {data && (
        <div style={{ marginTop: 8, color: '#999', fontSize: 12 }}>
          统计区间：{range.start_date} ~ {range.end_date}（KPI 与未闭环列表反映当前态，分布与趋势受时间范围筛选）
        </div>
      )}
    </Card>
  );
});

function Statistics() {
  const [spinning, setSpinning] = useState(false);

  function load() {
    setSpinning(true);
    store.fetchOverview().finally(() => setSpinning(false));
  }

  useEffect(() => {
    store.fetchEventTypes();
    store.fetchSystemNames();
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 筛选条件变化自动刷新
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    store.f_date_range, store.f_event_type, store.f_system_name,
    store.f_severity, store.f_status,
  ]);

  const data = store.data;
  const {
    range = {},
    kpi = {},
    trend = [],
    by_system: bySystem = [],
    by_status: byStatus = [],
    by_severity: bySeverity = [],
    by_type: byType = [],
    unclosed_list: unclosedList = [],
  } = data || {};

  return (
    <AuthDiv auth="runlog.runlog.view">
      <Breadcrumb style={{ marginBottom: 16 }}>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>运行日志</Breadcrumb.Item>
        <Breadcrumb.Item>统计概览</Breadcrumb.Item>
      </Breadcrumb>

      <Spin spinning={spinning}>
        {/* 筛选条件 */}
        <FilterCard data={data} range={range} load={load} />

        {/* KPI 卡片 */}
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={4}>
            <Card><Statistic title="事件总数" value={getValue(kpi.total)} prefix={<FileTextOutlined style={{ color: '#1890ff' }} />} /></Card>
          </Col>
          <Col span={4}>
            <Card><Statistic title="今日新增" value={getValue(kpi.today_new)} prefix={<RiseOutlined style={{ color: '#52c41a' }} />} valueStyle={{ color: '#52c41a' }} /></Card>
          </Col>
          <Col span={4}>
            <Card><Statistic title="本月新增" value={getValue(kpi.month_new)} prefix={<RiseOutlined style={{ color: '#1890ff' }} />} /></Card>
          </Col>
          <Col span={4}>
            <Card><Statistic title="未闭环" value={getValue(kpi.unclosed)} prefix={<ClockCircleOutlined style={{ color: '#faad14' }} />} valueStyle={{ color: '#faad14' }} /></Card>
          </Col>
          <Col span={4}>
            <Card><Statistic title="已归档" value={getValue(kpi.archived)} prefix={<CheckCircleOutlined style={{ color: '#8c8c8c' }} />} /></Card>
          </Col>
          <Col span={4}>
            <Card><Statistic title="P0/P1 高优" value={getValue(kpi.high_priority)} prefix={<FireOutlined style={{ color: '#ff4d4f' }} />} valueStyle={{ color: '#ff4d4f' }} suffix={<span style={{ fontSize: 12, color: '#999' }}>(P0:{getValue(kpi.p0)}/P1:{getValue(kpi.p1)})</span>} /></Card>
          </Col>
        </Row>

        {/* 趋势 + 系统排行 */}
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={14}>
            <Card title="事件趋势（按日）">
              {trend.length > 0 ? (
                <Chart
                  data={trend}
                  autoFit
                  height={300}
                  padding={[30, 20, 60, 50]}
                  scale={{ count: { min: 0, tickInterval: 1 } }}
                >
                  <Axis name="date" label={{ autoRotate: true, style: { fontSize: 11 } }} />
                  <Axis name="count" />
                  <Tooltip showCrosshairs />
                  <Geom type="line" position="date*count" color="#1890ff" shape="smooth" size={2} />
                  <Geom type="point" position="date*count" color="#1890ff" size={3} shape="circle" />
                </Chart>
              ) : <Empty description="暂无数据" style={{ padding: 40 }} />}
            </Card>
          </Col>
          <Col span={10}>
            <Card title="关联系统排行 Top 10">
              {bySystem.length > 0 ? (
                <Table
                  dataSource={bySystem} columns={systemColumns}
                  pagination={false} size="small" rowKey="system_name"
                />
              ) : <Empty description="暂无数据" style={{ padding: 40 }} />}
            </Card>
          </Col>
        </Row>

        {/* 分布统计 */}
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={8}>
            <Card title="按状态分布">
              {byStatus.length > 0 ? (
                <Table dataSource={byStatus} columns={distColumns} pagination={false} size="small" rowKey="key" />
              ) : <Empty description="暂无数据" style={{ padding: 24 }} />}
            </Card>
          </Col>
          <Col span={8}>
            <Card title="按级别分布">
              {bySeverity.length > 0 ? (
                <Table dataSource={bySeverity} columns={distColumns} pagination={false} size="small" rowKey="key" />
              ) : <Empty description="暂无数据" style={{ padding: 24 }} />}
            </Card>
          </Col>
          <Col span={8}>
            <Card title="按事件类型分布">
              {byType.length > 0 ? (
                <Table dataSource={byType} columns={distColumns} pagination={false} size="small" rowKey="key" />
              ) : <Empty description="暂无数据" style={{ padding: 24 }} />}
            </Card>
          </Col>
        </Row>

        {/* 未闭环事件列表 */}
        <Card
          title={
            <span>
              <AlertOutlined style={{ color: '#faad14', marginRight: 8 }} />
              未闭环事件列表（最近 {unclosedList.length} 条）
            </span>
          }
        >
          <Table
            dataSource={unclosedList} columns={unclosedColumns}
            pagination={false} size="small" rowKey="id"
            locale={{ emptyText: <Empty description="暂无未闭环事件" /> }}
          />
        </Card>
      </Spin>
    </AuthDiv>
  );
}

export default observer(Statistics);
