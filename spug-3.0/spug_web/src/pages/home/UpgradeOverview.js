/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState, useEffect } from 'react';
import { Card, Statistic, Tag, List } from 'antd';
import { CloudUploadOutlined } from '@ant-design/icons';
import { http, history } from 'libs';

function UpgradeOverview() {
  const [fetching, setFetching] = useState(true);
  const [stats, setStats] = useState(null);

  useEffect(() => {
    let cancelled = false;
    http.get('/api/home/statistic/')
      .then(res => {
        if (!cancelled) setStats(res.upgrade || {});
      })
      .finally(() => {
        if (!cancelled) setFetching(false);
      });
    return () => { cancelled = true; };
  }, []);

  const statusColor = (status) => {
    if (!status) return 'default';
    if (status.includes('处理') || status.includes('进行')) return 'processing';
    if (status.includes('完成') || status.includes('成功')) return 'success';
    if (status.includes('取消') || status.includes('失败')) return 'error';
    return 'default';
  };

  return (
    <Card
      title={
        <span>
          <CloudUploadOutlined style={{ marginRight: 8 }} />
          系统升级动态
        </span>
      }
      loading={fetching}
      hoverable
      style={{ cursor: 'pointer', height: '100%' }}
      onClick={() => history.push('/upgrade')}
    >
      {stats && (
        <div>
          <div style={{ display: 'flex', gap: 16, marginBottom: 12 }}>
            <Statistic title="累计" value={stats.total} suffix="次" valueStyle={{ fontSize: 20 }} />
            <Statistic title="本月" value={stats.this_month} suffix="次" valueStyle={{ fontSize: 20, color: '#1890ff' }} />
          </div>

          {stats.status_stats && stats.status_stats.length > 0 && (
            <div style={{ marginBottom: 8 }}>
              <span style={{ color: '#999', fontSize: 13 }}>状态分布：</span>
              <div style={{ marginTop: 4 }}>
                {stats.status_stats.map((s, i) => (
                  <Tag key={`${s.status}-${i}`} color={statusColor(s.status)} style={{ marginBottom: 4 }}>
                    {s.status}: {s.count}
                  </Tag>
                ))}
              </div>
            </div>
          )}

          {stats.recent && stats.recent.length > 0 && (
            <div>
              <span style={{ color: '#999', fontSize: 13 }}>最近记录：</span>
              <List
                size="small"
                dataSource={stats.recent.slice(0, 3)}
                renderItem={item => (
                  <List.Item style={{ padding: '4px 0' }}>
                    <span style={{ fontSize: 12, color: '#595959', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 180 }} title={item.system}>
                      {item.system}
                    </span>
                    <Tag color={statusColor(item.status)} style={{ fontSize: 11, marginLeft: 'auto' }}>
                      {item.status}
                    </Tag>
                  </List.Item>
                )}
              />
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

export default UpgradeOverview;
