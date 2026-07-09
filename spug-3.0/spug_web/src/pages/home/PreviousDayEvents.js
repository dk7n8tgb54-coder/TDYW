/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState, useEffect } from 'react';
import { Card, List, Tag } from 'antd';
import { ExclamationCircleOutlined } from '@ant-design/icons';
import { http, history } from 'libs';

function PreviousDayEvents(props) {
  const [fetching, setFetching] = useState(true);
  const [events, setEvents] = useState([]);

  useEffect(() => {
    fetchEvents();
  }, []);

  function fetchEvents() {
    setFetching(true);
    // 获取跨日事项跟踪中"处理中"状态的事件，设置足够大的分页大小以获取所有记录
    http.get('/api/runlog/', { params: { status: 'in_progress', page_size: 1000 } })
      .then(res => {
        setEvents(res.logs || []);
      })
      .finally(() => setFetching(false));
  }

  const getSeverityColor = (severity) => {
    const map = {
      'P0': 'red',
      'P1': 'orange',
      'P2': 'green'
    };
    return map[severity] || 'default';
  };

  return (
    <Card
      title={
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <ExclamationCircleOutlined />
          <span>待办</span>
        </div>
      }
      loading={fetching}
      bodyStyle={{ height: 400, padding: '0 24px' }}
      className={props.className}
    >
      {events.length === 0 ? (
        <div style={{ marginTop: 40, color: '#999', textAlign: 'center' }}>
          暂无待办事项
        </div>
      ) : (
        <List
          style={{ minHeight: 400, maxHeight: 400, overflowY: 'auto' }}
          dataSource={events}
          renderItem={(item, index) => (
            <List.Item
              key={item.id}
              style={{
                padding: '12px 0',
                borderBottom: index < events.length - 1 ? '1px solid #f0f0f0' : 'none',
                cursor: 'pointer'
              }}
              onClick={() => {
                // 点击跳转到跨日事项跟踪详情，带上事件ID
                history.push(`/runlog?view=${item.id}`);
              }}
            >
              <List.Item.Meta
                title={
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontWeight: 500 }}>{item.event_title}</span>
                    <Tag color={getSeverityColor(item.severity)}>{item.severity}</Tag>
                  </div>
                }
                description={
                  <div>
                    <div style={{ marginBottom: 4, color: '#666' }}>
                      {item.event_type} | {item.system_name}
                    </div>
                    <div style={{ fontSize: 12, color: '#999' }}>
                      创建时间：{item.created_at} | 动态数：{item.update_count}
                    </div>
                  </div>
                }
              />
            </List.Item>
          )}
        />
      )}
    </Card>
  );
}

export default PreviousDayEvents;
