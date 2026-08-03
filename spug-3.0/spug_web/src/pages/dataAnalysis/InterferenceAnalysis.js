/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { Row, Col, Alert, Button, Empty } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { observer } from 'mobx-react';
import store from './store';
import StatCard from './components/StatCard';
import TrendChart from './components/TrendChart';
import DistributionChart from './components/DistributionChart';

export default observer(function InterferenceAnalysis() {
  const data = store.getData('interference');
  const loading = store.isFetching('interference');
  const error = store.getError('interference');

  if (error) {
    return (
      <Alert
        message="数据加载失败"
        description={error}
        type="error"
        showIcon
        action={
          <Button size="small" icon={<ReloadOutlined />} onClick={() => store.fetchTab('interference')}>
            重试
          </Button>
        }
      />
    );
  }

  if (!loading && !data) {
    return <Empty description="暂无数据" />;
  }

  const summary = data?.summary || {};
  const trends = data?.trends || {};
  const dist = data?.distributions || {};

  return (
    <div>
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} lg={6}>
          <StatCard title="干扰记录数" value={summary.record_count || 0} loading={loading} />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <StatCard title="已上报数" value={summary.reported_count || 0} loading={loading} />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <StatCard title="未上报数" value={summary.unreported_count || 0} loading={loading} />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <StatCard title="上报率" value={summary.report_rate || '0.0%'} loading={loading} />
        </Col>
      </Row>

      <div style={{ marginTop: 16 }}>
        <Row gutter={[16, 16]}>
          <Col xs={24} lg={24}>
            <TrendChart
              title="干扰记录月度趋势"
              data={trends.record_monthly}
              loading={loading}
            />
          </Col>
        </Row>
      </div>

      <div style={{ marginTop: 16 }}>
        <Row gutter={[16, 16]}>
          <Col xs={24} lg={12}>
            <DistributionChart
              title="干扰类型分布"
              data={dist.by_type}
              loading={loading}
            />
          </Col>
          <Col xs={24} lg={12}>
            <DistributionChart
              title="频率分布"
              data={dist.by_frequency}
              loading={loading}
            />
          </Col>
          <Col xs={24} lg={12}>
            <DistributionChart
              title="状态分布"
              data={dist.by_status}
              loading={loading}
            />
          </Col>
          <Col xs={24} lg={12}>
            <DistributionChart
              title="上报部门分布"
              data={dist.by_report_department}
              loading={loading}
            />
          </Col>
        </Row>
      </div>
    </div>
  );
});
