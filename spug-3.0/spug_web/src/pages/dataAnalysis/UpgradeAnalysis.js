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

export default observer(function UpgradeAnalysis() {
  const data = store.getData('upgrade');
  const loading = store.isFetching('upgrade');
  const error = store.getError('upgrade');

  if (error) {
    return (
      <Alert
        message="数据加载失败"
        description={error}
        type="error"
        showIcon
        action={
          <Button size="small" icon={<ReloadOutlined />} onClick={() => store.fetchTab('upgrade')}>
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
        <Col xs={24} sm={12} lg={8} xl={4}>
          <StatCard title="升级记录数" value={summary.record_count || 0} loading={loading} />
        </Col>
        <Col xs={24} sm={12} lg={8} xl={4}>
          <StatCard title="处理中" value={summary.in_progress_count || 0} loading={loading} />
        </Col>
        <Col xs={24} sm={12} lg={8} xl={4}>
          <StatCard title="已完成" value={summary.completed_count || 0} loading={loading} />
        </Col>
        <Col xs={24} sm={12} lg={8} xl={4}>
          <StatCard title="已回退" value={summary.rolled_back_count || 0} loading={loading} />
        </Col>
        <Col xs={24} sm={12} lg={8} xl={4}>
          <StatCard title="完成率" value={summary.completion_rate || '0.0%'} loading={loading} />
        </Col>
      </Row>

      <div style={{ marginTop: 16 }}>
        <Row gutter={[16, 16]}>
          <Col xs={24} lg={24}>
            <TrendChart
              title="升级记录月度趋势"
              data={trends.record_monthly}
              loading={loading}
            />
          </Col>
        </Row>
      </div>

      <div style={{ marginTop: 16 }}>
        <Row gutter={[16, 16]}>
          <Col xs={24} lg={8}>
            <DistributionChart
              title="升级状态分布"
              data={dist.by_status}
              loading={loading}
            />
          </Col>
          <Col xs={24} lg={8}>
            <DistributionChart
              title="升级类型分布"
              data={dist.by_type}
              loading={loading}
            />
          </Col>
          <Col xs={24} lg={8}>
            <DistributionChart
              title="系统分布"
              data={dist.by_system}
              loading={loading}
            />
          </Col>
        </Row>
      </div>
    </div>
  );
});
