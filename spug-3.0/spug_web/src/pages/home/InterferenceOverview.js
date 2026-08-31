/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 *
 * 干扰管理今日概览（双业务类型）：分别展示地面/空中今日记录数并给出总量。
 */
import React, { useState, useEffect } from 'react';
import { Card, Statistic, Row, Col } from 'antd';
import { ExceptionOutlined } from '@ant-design/icons';
import { http, history } from 'libs';

function InterferenceOverview() {
  const [fetching, setFetching] = useState(true);
  const [stats, setStats] = useState(null);

  useEffect(() => {
    http.get('/api/home/statistic/')
      .then(res => setStats(res.interference || {}))
      .finally(() => setFetching(false));
  }, []);

  return (
    <Card
      title={
        <span>
          <ExceptionOutlined style={{ marginRight: 8 }} />
          干扰信息今日统计
        </span>
      }
      loading={fetching}
      hoverable
      style={{ cursor: 'pointer', height: '100%' }}
      onClick={() => history.push('/data-analysis?tab=interference')}
    >
      {stats && (
        <div>
          <Statistic
            title="今日干扰合计"
            value={stats.today_total}
            suffix="条"
            valueStyle={{ color: stats.today_total > 0 ? '#faad14' : '#52c41a', fontSize: 28 }}
          />

          <Row gutter={16} style={{ marginTop: 12 }}>
            <Col span={12}>
              <Statistic
                title="地面通信异常"
                value={stats.bridge_today_total}
                suffix="条"
                valueStyle={{ fontSize: 18, color: '#1890ff' }}
              />
            </Col>
            <Col span={12}>
              <Statistic
                title="空中干扰"
                value={stats.air_today_total}
                suffix="条"
                valueStyle={{ fontSize: 18, color: '#faad14' }}
              />
            </Col>
          </Row>
        </div>
      )}
    </Card>
  );
}

export default InterferenceOverview;
