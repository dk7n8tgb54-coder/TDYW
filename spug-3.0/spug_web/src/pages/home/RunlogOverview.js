/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState, useEffect } from 'react';
import { Card, Row, Col, Statistic, Tag, List } from 'antd';
import {
  FileTextOutlined,
  ClockCircleOutlined,
  CheckCircleOutlined,
} from '@ant-design/icons';
import { http, history } from 'libs';

const severityColors = { P0: 'red', P1: 'orange', P2: 'green' };
const severityLabels = { P0: '紧急', P1: '重要', P2: '一般' };

function RunlogOverview() {
  const [fetching, setFetching] = useState(true);
  const [stats, setStats] = useState(null);

  useEffect(() => {
    http.get('/api/home/statistic/')
      .then(res => setStats(res.runlog || {}))
      .finally(() => setFetching(false));
  }, []);

  if (fetching) return <Card loading style={{ marginBottom: 12 }} />;
  if (!stats) return null;

  return (
    <Card style={{ marginBottom: 12 }}>
      {/* 统计数字行 */}
      <Row gutter={24}>
        <Col span={8}>
          <Statistic
            title="今日新增"
            value={stats.today_total}
            prefix={<FileTextOutlined style={{ color: '#1890ff' }} />}
            valueStyle={{ color: '#1890ff' }}
          />
        </Col>
        <Col span={8}>
          <Statistic
            title="处理中"
            value={stats.in_progress_total}
            prefix={<ClockCircleOutlined style={{ color: '#faad14' }} />}
            valueStyle={{ color: '#faad14' }}
          />
        </Col>
        <Col span={8}>
          <Statistic
            title="今日已解决"
            value={stats.today_resolved}
            prefix={<CheckCircleOutlined style={{ color: '#52c41a' }} />}
            valueStyle={{ color: '#52c41a' }}
          />
        </Col>
      </Row>

      {/* 等级分布 */}
      {stats.severity_stats && stats.severity_stats.length > 0 && (
        <div style={{ marginTop: 12, display: 'flex', gap: 8, alignItems: 'center' }}>
          <span style={{ color: '#999', fontSize: 13 }}>处理中等级分布：</span>
          {stats.severity_stats.map(s => (
            <Tag key={s.severity} color={severityColors[s.severity]}>
              {severityLabels[s.severity] || s.severity}: {s.count}
            </Tag>
          ))}
        </div>
      )}

      {/* 待办事件列表 */}
      {stats.recent_pending && stats.recent_pending.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <div style={{ fontWeight: 500, marginBottom: 8, color: '#595959' }}>当前处理中</div>
          <List
            size="small"
            dataSource={stats.recent_pending}
            renderItem={item => (
              <List.Item
                style={{ cursor: 'pointer', padding: '6px 0' }}
                onClick={() => history.push(`/runlog?view=${item.id}`)}
              >
                <List.Item.Meta
                  title={
                    <span style={{ fontSize: 13 }}>
                      <Tag color={severityColors[item.severity]} style={{ fontSize: 11 }}>
                        {item.severity}
                      </Tag>
                      {item.event_title}
                    </span>
                  }
                />
              </List.Item>
            )}
          />
        </div>
      )}
    </Card>
  );
}

export default RunlogOverview;
