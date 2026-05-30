/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState, useEffect } from 'react';
import { Card, Statistic, Tag, Row, Col } from 'antd';
import { ExceptionOutlined, CheckCircleOutlined, WarningOutlined } from '@ant-design/icons';
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
      onClick={() => history.push('/interference')}
    >
      {stats && (
        <div>
          <Statistic
            title="今日干扰"
            value={stats.today_total}
            suffix="条"
            valueStyle={{ color: stats.today_total > 0 ? '#faad14' : '#52c41a', fontSize: 28 }}
          />

          {stats.type_stats && stats.type_stats.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <span style={{ color: '#999', fontSize: 13 }}>类型分布：</span>
              <div style={{ marginTop: 4 }}>
                {stats.type_stats.map(s => (
                  <Tag key={s.interference_type} style={{ marginBottom: 4 }}>
                    {s.interference_type}: {s.count}
                  </Tag>
                ))}
              </div>
            </div>
          )}

          <Row gutter={16} style={{ marginTop: 12 }}>
            <Col span={12}>
              <Statistic
                title="已上报"
                value={stats.reported_count}
                prefix={<CheckCircleOutlined style={{ color: '#52c41a' }} />}
                valueStyle={{ fontSize: 18, color: '#52c41a' }}
              />
            </Col>
            <Col span={12}>
              <Statistic
                title="未上报"
                value={stats.unreported_count}
                prefix={<WarningOutlined style={{ color: stats.unreported_count > 0 ? '#faad14' : '#d9d9d9' }} />}
                valueStyle={{ fontSize: 18, color: stats.unreported_count > 0 ? '#faad14' : '#d9d9d9' }}
              />
            </Col>
          </Row>
        </div>
      )}
    </Card>
  );
}

export default InterferenceOverview;
