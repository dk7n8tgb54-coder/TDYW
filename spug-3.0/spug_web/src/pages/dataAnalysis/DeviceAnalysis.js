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

export default observer(function DeviceAnalysis() {
  const data = store.getData('device');
  const loading = store.isFetching('device');
  const error = store.getError('device');

  if (error) {
    return (
      <Alert
        message="数据加载失败"
        description={error}
        type="error"
        showIcon
        action={
          <Button size="small" icon={<ReloadOutlined />} onClick={() => store.fetchTab('device')}>
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
        <Col xs={24} sm={12} lg={8} xl={3}>
          <StatCard title="设备总数" value={summary.total_snapshot || 0} loading={loading} />
        </Col>
        <Col xs={24} sm={12} lg={8} xl={3}>
          <StatCard title="正常" value={summary.normal_snapshot || 0} loading={loading} />
        </Col>
        <Col xs={24} sm={12} lg={8} xl={3}>
          <StatCard title="故障" value={summary.fault_snapshot || 0} loading={loading} />
        </Col>
        <Col xs={24} sm={12} lg={8} xl={3}>
          <StatCard title="维修中" value={summary.repairing_snapshot || 0} loading={loading} />
        </Col>
        <Col xs={24} sm={12} lg={8} xl={3}>
          <StatCard title="停用" value={summary.disabled_snapshot || 0} loading={loading} />
        </Col>
        <Col xs={24} sm={12} lg={8} xl={3}>
          <StatCard title="报废" value={summary.scrapped_snapshot || 0} loading={loading} />
        </Col>
        <Col xs={24} sm={12} lg={8} xl={3}>
          <StatCard title="区间新增" value={summary.created_in_period || 0} loading={loading} />
        </Col>
      </Row>

      <div style={{ marginTop: 16 }}>
        <Row gutter={[16, 16]}>
          <Col xs={24} lg={24}>
            <TrendChart
              title="设备新增月度趋势"
              data={trends.created_monthly}
              loading={loading}
            />
          </Col>
        </Row>
      </div>

      <div style={{ marginTop: 16 }}>
        <Row gutter={[16, 16]}>
          <Col xs={24} lg={12}>
            <DistributionChart
              title="设备状态分布"
              data={dist.by_status}
              loading={loading}
            />
          </Col>
          <Col xs={24} lg={12}>
            <DistributionChart
              title="设备型号分布"
              data={dist.by_model}
              loading={loading}
            />
          </Col>
          <Col xs={24} lg={12}>
            <DistributionChart
              title="厂商分布"
              data={dist.by_manufacturer}
              loading={loading}
            />
          </Col>
          <Col xs={24} lg={12}>
            <DistributionChart
              title="使用单位分布"
              data={dist.by_use_unit}
              loading={loading}
            />
          </Col>
        </Row>
      </div>
    </div>
  );
});
