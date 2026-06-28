/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useEffect, useState } from 'react';
import { observer } from 'mobx-react';
import { Card, Row, Col, Statistic, DatePicker, Select, Empty, Table } from 'antd';
import { AuthDiv, Breadcrumb } from 'components';
import store from './store';

const { RangePicker } = DatePicker;
const { Option } = Select;

export default observer(function () {
  const [dateRange, setDateRange] = useState(null);
  const [selectedSystem, setSelectedSystem] = useState(null);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(false);

  function fetchStats() {
    setLoading(true);
    const filters = {};
    if (selectedSystem) filters.system = selectedSystem;
    if (dateRange && dateRange.length === 2) {
      filters.start_date = dateRange[0].format('YYYY-MM-DD');
      filters.end_date = dateRange[1].format('YYYY-MM-DD');
    }
    store.fetchStatistics(filters)
      .then(data => setStats(data))
      .catch(() => setStats(null))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    store.fetchFilterOptions();
    fetchStats();
  }, []);

  useEffect(() => {
    fetchStats();
  }, [selectedSystem, dateRange]);

  const typeColumns = [
    { title: '升级类型', dataIndex: 'upgrade_type', key: 'upgrade_type' },
    { title: '次数', dataIndex: 'count', key: 'count' },
    { title: '占比', dataIndex: 'percent', key: 'percent', render: (text) => `${text}%` }
  ];

  const systemColumns = [
    { title: '系统', dataIndex: 'system', key: 'system' },
    { title: '次数', dataIndex: 'count', key: 'count' },
    { title: '占比', dataIndex: 'percent', key: 'percent', render: (text) => `${text}%` }
  ];

  const trendColumns = [
    { title: '日期', dataIndex: 'date', key: 'date' },
    { title: '升级次数', dataIndex: 'count', key: 'count' }
  ];

  return (
    <AuthDiv auth="upgrade.statistics.view">
      <Breadcrumb style={{ marginBottom: 16 }}>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>系统升级管理</Breadcrumb.Item>
        <Breadcrumb.Item>统计报表</Breadcrumb.Item>
      </Breadcrumb>
      <Card style={{ marginBottom: 16 }}>
        <Row gutter={16}>
          <Col span={24}>
            <Statistic title="总升级次数" value={stats?.total_count || 0}/>
          </Col>
        </Row>
      </Card>

      <Card style={{ marginBottom: 16 }} title="筛选条件">
        <Row gutter={16}>
          <Col span={8}>
            <Select
              placeholder="选择系统"
              style={{ width: '100%' }}
              allowClear
              value={selectedSystem}
              onChange={setSelectedSystem}
            >
              {store.filterOptions.systems.map(sys => (
                <Option key={sys} value={sys}>{sys}</Option>
              ))}
            </Select>
          </Col>
          <Col span={8}>
            <RangePicker
              style={{ width: '100%' }}
              value={dateRange}
              onChange={setDateRange}
            />
          </Col>
        </Row>
      </Card>

      <Row gutter={16}>
        <Col span={12}>
          <Card title="升级类型统计">
            {stats?.by_type?.length > 0 ? (
              <Table
                dataSource={stats.by_type}
                columns={typeColumns}
                pagination={false}
                size="small"
                rowKey="upgrade_type"
              />
            ) : (
              <Empty description="暂无数据"/>
            )}
          </Card>
        </Col>
      </Row>

      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col span={12}>
          <Card title="系统升级统计" style={{ marginBottom: 16 }}>
            {stats?.by_system?.length > 0 ? (
              <Table
                dataSource={stats.by_system}
                columns={systemColumns}
                pagination={false}
                size="small"
                rowKey="system"
              />
            ) : (
              <Empty description="暂无数据"/>
            )}
          </Card>
        </Col>
        <Col span={12}>
          <Card title="升级趋势">
            {stats?.trend?.length > 0 ? (
              <Table
                dataSource={stats.trend}
                columns={trendColumns}
                pagination={{ pageSize: 10 }}
                size="small"
                rowKey="date"
              />
            ) : (
              <Empty description="暂无数据"/>
            )}
          </Card>
        </Col>
      </Row>
    </AuthDiv>
  );
})
