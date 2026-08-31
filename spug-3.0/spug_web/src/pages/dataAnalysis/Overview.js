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

export default observer(function Overview() {
  const data = store.getData('overview');
  const loading = store.isFetching('overview');
  const error = store.getError('overview');

  if (error) {
    return (
      <Alert
        message="数据加载失败"
        description={error}
        type="error"
        showIcon
        action={
          <Button size="small" icon={<ReloadOutlined />} onClick={() => store.fetchTab('overview')}>
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

  return (
    <div>
      {/* 汇总指标 */}
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} lg={8} xl={6}>
          <StatCard title="故障记录数" value={summary.fault_record_count || 0} loading={loading} />
        </Col>
        <Col xs={24} sm={12} lg={8} xl={6}>
          <StatCard title="干扰记录数" value={summary.interference_record_count || 0} loading={loading} />
        </Col>
        <Col xs={24} sm={12} lg={8} xl={6}>
          <StatCard title="地面干扰数" value={summary.interference_bridge_count || 0} loading={loading} />
        </Col>
        <Col xs={24} sm={12} lg={8} xl={6}>
          <StatCard title="空中干扰数" value={summary.interference_air_count || 0} loading={loading} />
        </Col>
        <Col xs={24} sm={12} lg={8} xl={6}>
          <StatCard title="设备总数" value={summary.device_total_snapshot || 0} loading={loading} />
        </Col>
        <Col xs={24} sm={12} lg={8} xl={6}>
          <StatCard title="设备故障数" value={summary.device_fault_snapshot || 0} loading={loading} />
        </Col>
        <Col xs={24} sm={12} lg={8} xl={6}>
          <StatCard title="升级记录数" value={summary.upgrade_record_count || 0} loading={loading} />
        </Col>
        <Col xs={24} sm={12} lg={8} xl={6}>
          <StatCard title="升级完成数" value={summary.upgrade_completed_count || 0} loading={loading} />
        </Col>
        <Col xs={24} sm={12} lg={8} xl={6}>
          <StatCard title="升级完成率" value={summary.upgrade_completion_rate || '0.0%'} loading={loading} />
        </Col>
        <Col xs={24} sm={12} lg={8} xl={6}>
          <StatCard title="设备正常数" value={summary.device_normal_snapshot || 0} loading={loading} />
        </Col>
      </Row>

      {/* 趋势图 */}
      <div style={{ marginTop: 16 }}>
        <Row gutter={[16, 16]}>
          <Col xs={24} lg={12}>
            <TrendChart
              title="故障记录月度趋势"
              data={trends.fault_monthly}
              loading={loading}
            />
          </Col>
          <Col xs={24} lg={12}>
            <TrendChart
              title="干扰记录月度趋势"
              data={trends.interference_monthly}
              loading={loading}
            />
          </Col>
          <Col xs={24} lg={24}>
            <TrendChart
              title="升级记录月度趋势"
              data={trends.upgrade_monthly}
              loading={loading}
            />
          </Col>
        </Row>
      </div>
    </div>
  );
});
