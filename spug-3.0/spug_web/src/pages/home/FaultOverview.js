/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState, useEffect } from 'react';
import { Card, Tag } from 'antd';
import { BugOutlined } from '@ant-design/icons';
import moment from 'moment';
import { http, history } from 'libs';

const LEVEL_COLORS = { A: 'red', B: 'orange', C: 'blue' };

function FaultOverview() {
  const [fetching, setFetching] = useState(true);
  const [faultData, setFaultData] = useState(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    http.get('/api/home/statistic/')
      .then(res => { if (!cancelled) setFaultData(res.fault || {}); })
      .catch(() => { if (!cancelled) setError(true); })
      .finally(() => { if (!cancelled) setFetching(false); });
    return () => { cancelled = true; };
  }, []);

  const renderContent = () => {
    if (error) {
      return <div style={{ color: '#999', fontSize: 13, textAlign: 'center', padding: '24px 0' }}>故障数据暂时无法获取</div>;
    }
    const recent = faultData?.recent || [];
    if (recent.length === 0) {
      return <div style={{ color: '#999', fontSize: 13, textAlign: 'center', padding: '24px 0' }}>暂无故障记录</div>;
    }
    return (
      <div>
        {recent.slice(0, 3).map(item => {
          const level = item.fault_level || '';
          const levelColor = LEVEL_COLORS[level] || 'default';
          const dateStr = item.fault_date ? moment(item.fault_date).format('MM-DD') : '--';
          const phenomenon = item.fault_phenomenon || '无';
          return (
            <div
              key={item.id}
              style={{ padding: '6px 0', borderBottom: '1px solid #f0f0f0' }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: 13, fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '60%' }}>
                  {item.system_name || '未知系统'}
                </span>
                <Tag color={levelColor} style={{ marginRight: 0 }}>{level || '未知'}</Tag>
              </div>
              <div style={{ fontSize: 12, color: '#999', marginTop: 2 }}>
                {item.device_code || '无编号'} · {dateStr}
              </div>
              <div
                title={phenomenon}
                style={{ fontSize: 12, color: '#666', marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
              >
                {phenomenon}
              </div>
            </div>
          );
        })}
      </div>
    );
  };

  return (
    <Card
      title={<span><BugOutlined style={{ marginRight: 8 }} />最近故障</span>}
      loading={fetching}
      hoverable
      style={{ cursor: 'pointer', height: '100%' }}
      onClick={() => history.push('/exec/fault/record')}
    >
      {renderContent()}
    </Card>
  );
}

export default FaultOverview;
