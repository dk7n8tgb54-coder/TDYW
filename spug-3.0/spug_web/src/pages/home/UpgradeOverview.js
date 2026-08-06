/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState, useEffect } from 'react';
import { Card, Statistic, Tag } from 'antd';
import { CloudUploadOutlined } from '@ant-design/icons';
import moment from 'moment';
import { http, history } from 'libs';

function UpgradeOverview() {
  const [fetching, setFetching] = useState(true);
  const [upgradeData, setUpgradeData] = useState(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    http.get('/api/home/statistic/')
      .then(res => { if (!cancelled) setUpgradeData(res.upgrade || {}); })
      .catch(() => { if (!cancelled) setError(true); })
      .finally(() => { if (!cancelled) setFetching(false); });
    return () => { cancelled = true; };
  }, []);

  const renderContent = () => {
    if (error) {
      return <div style={{ color: '#999', fontSize: 13, textAlign: 'center', padding: '24px 0' }}>升级数据暂时无法获取</div>;
    }
    const inProgress = upgradeData?.in_progress || [];
    const total = upgradeData?.in_progress_total ?? 0;

    if (inProgress.length === 0 && total === 0) {
      return <div style={{ color: '#999', fontSize: 13, textAlign: 'center', padding: '24px 0' }}>当前暂无进行中的系统升级</div>;
    }

    return (
      <div>
        <Statistic
          title="当前进行中"
          value={total}
          suffix="项"
          valueStyle={{ color: '#1890ff', fontSize: 28 }}
        />
        {inProgress.slice(0, 3).map(item => {
          const title = item.title || item.system || '未命名升级';
          const timeStr = item.upgrade_time ? moment(item.upgrade_time).format('MM-DD HH:mm') : '--';
          return (
            <div
              key={item.id}
              style={{ padding: '6px 0', borderBottom: '1px solid #f0f0f0', cursor: 'pointer' }}
              onClick={e => { e.stopPropagation(); history.push(`/upgrade/workbench/${item.id}`); }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span
                  title={title}
                  style={{ fontSize: 13, fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '65%' }}
                >
                  {title}
                </span>
                <Tag color="processing" style={{ marginRight: 0 }}>{item.status}</Tag>
              </div>
              <div style={{ fontSize: 12, color: '#999', marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {item.system || '未知系统'} · {item.upgrade_type || ''} · {timeStr}
                {item.owner ? ` · ${item.owner}` : ''}
              </div>
            </div>
          );
        })}
      </div>
    );
  };

  return (
    <Card
      title={<span><CloudUploadOutlined style={{ marginRight: 8 }} />进行中的系统升级</span>}
      loading={fetching}
      hoverable
      style={{ cursor: 'pointer', height: '100%' }}
      onClick={() => history.push('/upgrade')}
    >
      {renderContent()}
    </Card>
  );
}

export default UpgradeOverview;
