import React, { useEffect, useState } from 'react';
import { observer } from 'mobx-react';
import { Button, Card, Col, Empty, Input, Popconfirm, Radio, Row, Select, Space, Spin, Tag, Tooltip, Typography } from 'antd';
import { Chart, Geom, Axis, Tooltip as ChartTooltip, Legend } from 'bizcharts';
import { CheckCircleOutlined, EyeOutlined, SearchOutlined } from '@ant-design/icons';
import { AuthDiv, AuthFragment, Breadcrumb, SearchForm, TableCard } from 'components';
import store from './store';

const { Option } = Select;
const { Text } = Typography;

const LEVELS = {
  error: {label: '严重', color: 'red'},
  warning: {label: '警告', color: 'gold'},
  info: {label: '提示', color: 'blue'},
};

const STATUSES = {
  unread: {label: '未读', color: 'red'},
  read: {label: '已读', color: 'default'},
  resolved: {label: '已处理', color: 'green'},
};

const SOURCE_LABELS = {
  celery: 'Celery',
  middleware: 'API',
  disk: '磁盘',
  db: '数据库',
};

const DiskTrendChart = observer(function DiskTrendChart() {
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    store.fetchTrend();
  }, []);

  // 将 store.trendData 展平为 bizcharts 数据格式
  const chartData = [];
  let hasData = false;
  store.trendData.forEach(series => {
    series.points.forEach(p => {
      chartData.push({
        time: new Date(p.time * 1000).toLocaleString('zh-CN', {hour12: false}),
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
          <Chart
            data={chartData}
            autoFit
            height={280}
            padding={[30, 20, 60, 60]}
            scale={{value: {min: 0, alias: '已用(GB)'}}}>
            <Axis name="time" label={{autoRotate: true, style: {fontSize: 10}}} />
            <Axis name="value" title={{text: '已用空间(GB)'}} />
            <Legend name="type" position="top" />
            <ChartTooltip showCrosshairs />
            <Geom type="line" position="time*value" color="type" shape="smooth" size={2} />
            <Geom type="point" position="time*value" color="type" size={3} shape="circle" />
          </Chart>
        ) : (
          <Empty description="暂无趋势数据（数据采集需运行至少 2 小时）" style={{margin: '40px 0'}} />
        )}
      </Spin>
    </Card>
  );
});

const AlertTable = observer(function AlertTable() {
  const columns = [{
    title: '发生时间',
    dataIndex: 'created_at',
    width: 170,
  }, {
    title: '级别',
    dataIndex: 'level',
    width: 80,
    render: value => {
      const item = LEVELS[value] || {label: value || '-', color: 'default'};
      return <Tag color={item.color}>{item.label}</Tag>;
    },
  }, {
    title: '告警标题',
    dataIndex: 'title',
    width: 220,
    ellipsis: true,
  }, {
    title: '详情',
    dataIndex: 'message',
    width: 320,
    render: value => value ? (
      <Text ellipsis={{tooltip: value}} style={{maxWidth: 300, display: 'block'}}>{value}</Text>
    ) : '-',
  }, {
    title: '来源',
    dataIndex: 'source',
    width: 100,
    render: value => SOURCE_LABELS[value] || value || '-',
  }, {
    title: '状态',
    dataIndex: 'status',
    width: 90,
    render: value => {
      const item = STATUSES[value] || {label: value || '-', color: 'default'};
      return <Tag color={item.color}>{item.label}</Tag>;
    },
  }, {
    title: '处理信息',
    width: 170,
    render: record => record.status === 'resolved'
      ? <Tooltip title={record.resolved_at || ''}>{record.resolved_by || '系统自动处理'}</Tooltip>
      : '-',
  }, {
    title: '操作',
    width: 180,
    fixed: 'right',
    render: record => (
      <Space size={4}>
        {record.status === 'unread' && (
          <Button
            type="link"
            size="small"
            icon={<EyeOutlined/>}
            loading={store.actionId === record.id}
            onClick={() => store.markRead(record.id)}>
            标记已读
          </Button>
        )}
        {record.status !== 'resolved' && (
          <AuthFragment auth="system.alert.resolve">
            <Popconfirm
              title="确认将这条告警标记为已处理？"
              okText="确认"
              cancelText="取消"
              onConfirm={() => store.resolve(record.id)}>
              <Button
                type="link"
                size="small"
                icon={<CheckCircleOutlined/>}
                loading={store.actionId === record.id}>
                标记已处理
              </Button>
            </Popconfirm>
          </AuthFragment>
        )}
      </Space>
    ),
  }];

  const summary = store.summary;
  const actions = [(
    <Space key="summary" size={6}>
      <Tag>未读 {summary.unread_count}</Tag>
      <Tag color="red">严重 {summary.error_count}</Tag>
      <Tag color="gold">警告 {summary.warning_count}</Tag>
      <Tag color="blue">提示 {summary.info_count}</Tag>
    </Space>
  )];

  return (
    <TableCard
      tKey="system-alert"
      rowKey="id"
      title="系统告警"
      loading={store.isFetching}
      dataSource={store.records}
      columns={columns}
      actions={actions}
      onReload={store.fetchRecords}
      scroll={{x: 1350}}
      pagination={{
        current: store.page,
        pageSize: store.pageSize,
        total: store.total,
        showSizeChanger: true,
        showLessItems: true,
        showTotal: total => `共 ${total} 条`,
        pageSizeOptions: ['10', '20', '50', '100'],
        onChange: store.changePage,
        onShowSizeChange: store.changePage,
      }}/>
  );
});

export default observer(function AlertIndex() {
  useEffect(() => {
    store.fetchRecords();
  }, []);

  return (
    <AuthDiv auth="system.alert.view">
      <Breadcrumb>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>系统管理</Breadcrumb.Item>
        <Breadcrumb.Item>系统告警</Breadcrumb.Item>
      </Breadcrumb>
      <SearchForm>
        <SearchForm.Item span={5} title="告警级别">
          <Select
            allowClear
            value={store.f_level || undefined}
            placeholder="全部级别"
            style={{width: '100%'}}
            onChange={value => store.f_level = value || ''}>
            <Option value="error">严重</Option>
            <Option value="warning">警告</Option>
            <Option value="info">提示</Option>
          </Select>
        </SearchForm.Item>
        <SearchForm.Item span={5} title="状态">
          <Select
            allowClear
            value={store.f_status || undefined}
            placeholder="全部状态"
            style={{width: '100%'}}
            onChange={value => store.f_status = value || ''}>
            <Option value="unread">未读</Option>
            <Option value="read">已读</Option>
            <Option value="resolved">已处理</Option>
          </Select>
        </SearchForm.Item>
        <SearchForm.Item span={5} title="来源">
          <Select
            allowClear
            value={store.f_source || undefined}
            placeholder="全部来源"
            style={{width: '100%'}}
            onChange={value => store.f_source = value || ''}>
            <Option value="celery">Celery</Option>
            <Option value="middleware">API</Option>
            <Option value="disk">磁盘</Option>
            <Option value="db">数据库</Option>
          </Select>
        </SearchForm.Item>
        <SearchForm.Item span={6} title="关键词">
          <Input
            allowClear
            prefix={<SearchOutlined style={{color: '#c0c0c0'}}/>}
            placeholder="标题、详情或告警键"
            value={store.f_keyword}
            onPressEnter={store.search}
            onChange={event => store.f_keyword = event.target.value}/>
        </SearchForm.Item>
        <SearchForm.Item span={3}>
          <Button type="primary" icon={<SearchOutlined/>} onClick={store.search}>查询</Button>
          <Button style={{marginLeft: 8}} onClick={store.resetFilters}>重置</Button>
        </SearchForm.Item>
      </SearchForm>
      <div style={{marginBottom: 16}}>
        <DiskTrendChart/>
      </div>
      <AlertTable/>
    </AuthDiv>
  );
});
