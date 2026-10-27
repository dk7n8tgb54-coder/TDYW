/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 *
 * 干扰分析统一从事件主表聚合，调查和频谱测量作为独立指标展示。
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
          <StatCard title="地面记录数" value={summary.ground_count || 0} loading={loading} />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <StatCard title="空中记录数" value={summary.air_count || 0} loading={loading} />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <StatCard title="地面+空中记录数" value={summary.cross_count || 0} loading={loading} />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <StatCard title="规律调查数" value={summary.investigation_count || 0} loading={loading} />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <StatCard title="频谱测量数" value={summary.measurement_count || 0} loading={loading} />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <StatCard title="未知场景记录数" value={summary.unknown_count || 0} loading={loading} />
        </Col>
      </Row>

      <div style={{ marginTop: 16 }}>
        <Row gutter={[16, 16]}>
          <Col xs={24} lg={12}>
            <TrendChart
              title="事件月度趋势"
              data={trends.record_monthly}
              loading={loading}
            />
          </Col>
          <Col xs={24} lg={12}>
            <TrendChart
              title="调查月度趋势"
              data={trends.investigation_monthly}
              loading={loading}
            />
          </Col>
          {trends.measurement_monthly && (
            <Col xs={24} lg={24}>
              <TrendChart
                title="测量月度趋势"
                data={trends.measurement_monthly}
                loading={loading}
              />
            </Col>
          )}
        </Row>
      </div>

      <div style={{ marginTop: 16 }}>
        <Row gutter={[16, 16]}>
          <Col xs={24} lg={12}>
            <DistributionChart title="发生场景分布" data={dist.by_scene} loading={loading} />
          </Col>
          <Col xs={24} lg={12}>
            <DistributionChart title="具体干扰类型分布" data={dist.by_interference_kind} loading={loading} />
          </Col>
          <Col xs={24} lg={12}>
            <DistributionChart title="受影响系统分布" data={dist.by_affected_system} loading={loading} />
          </Col>
          <Col xs={24} lg={12}>
            <DistributionChart title="疑似干扰源分布" data={dist.by_source_type} loading={loading} />
          </Col>
        </Row>
      </div>
    </div>
  );
});
