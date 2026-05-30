/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState, useEffect } from 'react';
import { Card, Statistic, Tag } from 'antd';
import { FolderOpenOutlined } from '@ant-design/icons';
import { http, history } from 'libs';

function DocumentOverview() {
  const [fetching, setFetching] = useState(true);
  const [stats, setStats] = useState(null);

  useEffect(() => {
    http.get('/api/home/statistic/')
      .then(res => setStats(res.document || {}))
      .finally(() => setFetching(false));
  }, []);

  return (
    <Card
      title={
        <span>
          <FolderOpenOutlined style={{ marginRight: 8 }} />
          资料库今日新增
        </span>
      }
      loading={fetching}
      hoverable
      style={{ cursor: 'pointer', height: '100%' }}
      onClick={() => history.push('/document')}
    >
      {stats && (
        <div>
          <Statistic
            title="今日新增文件"
            value={stats.today_total}
            suffix="个"
            valueStyle={{ color: '#1890ff', fontSize: 28 }}
          />
          <div style={{ marginTop: 12, display: 'flex', gap: 8 }}>
            <Tag color="blue">公共: {stats.today_public || 0}</Tag>
            <Tag color="cyan">私有: {stats.today_private || 0}</Tag>
          </div>
        </div>
      )}
      {!fetching && stats && stats.today_total === 0 && (
        <div style={{ marginTop: 8, color: '#999', fontSize: 13 }}>今日暂无新增文件</div>
      )}
    </Card>
  );
}

export default DocumentOverview;
