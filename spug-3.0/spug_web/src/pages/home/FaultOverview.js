/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState, useEffect } from 'react';
import { Card, Statistic, Tag } from 'antd';
import { BugOutlined } from '@ant-design/icons';
import { http, history } from 'libs';

function FaultOverview() {
  const [fetching, setFetching] = useState(true);
  const [stats, setStats] = useState(null);

  useEffect(() => {
    http.get('/api/home/statistic/')
      .then(res => setStats(res.fault || {}))
      .finally(() => setFetching(false));
  }, []);

  return (
    <Card
      title={
        <span>
          <BugOutlined style={{ marginRight: 8 }} />
          故障处置概览
        </span>
      }
      loading={fetching}
      hoverable
      style={{ cursor: 'pointer', height: '100%' }}
      onClick={() => history.push('/exec/fault/record')}
    >
      {stats && (
        <div>
          <Statistic title="今日故障" value={stats.today_total} suffix="条" valueStyle={{ color: stats.today_total > 0 ? '#ff4d4f' : '#52c41a' }} />
          {stats.level_stats && stats.level_stats.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <span style={{ color: '#999', fontSize: 13 }}>等级分布：</span>
              <div style={{ marginTop: 4 }}>
                {stats.level_stats.map(s => (
                  <Tag key={s.fault_level} style={{ marginBottom: 4 }}>
                    {s.fault_level}: {s.count}
                  </Tag>
                ))}
              </div>
            </div>
          )}
          <div style={{ marginTop: 12, color: '#999', fontSize: 13 }}>
            累计记录: <strong>{stats.total_all}</strong> 条
          </div>
        </div>
      )}
      {!fetching && stats && stats.today_total === 0 && (
        <div style={{ marginTop: 8, color: '#52c41a', fontSize: 13 }}>今日无故障记录</div>
      )}
    </Card>
  );
}

export default FaultOverview;
