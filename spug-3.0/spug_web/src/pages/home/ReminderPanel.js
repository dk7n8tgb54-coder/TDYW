/**
 * 提醒事项首页面板
 *
 * 展示当前用户未确认的提醒，带"已完成"按钮。
 * 无待办时显示"暂无待办提醒"。
 */
import React, { useState, useEffect, useCallback } from 'react';
import { Card, List, Tag, Button, Empty, Spin, notification } from 'antd';
import { ScheduleOutlined } from '@ant-design/icons';
import { http } from 'libs';

const PENDING_URL = '/api/reminder/pending/';
const ACK_URL = '/api/reminder/ack/';

export default function ReminderPanel() {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState([]);

  const fetchData = useCallback(() => {
    setLoading(true);
    http.get(PENDING_URL)
      .then(list => setData(Array.isArray(list) ? list : []))
      .catch(() => setData([]))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleAck = (logId) => {
    http.post(ACK_URL, { log_id: logId })
      .then(() => {
        notification.success({ message: '已确认' });
        fetchData();
      })
      .catch(e => notification.error({ message: '操作失败', description: e.message || String(e) }));
  };

  const title = (
    <span>
      <ScheduleOutlined style={{ marginRight: 6 }} />
      提醒事项
      {data.length > 0 && <Tag color="orange" style={{ marginLeft: 8 }}>{data.length}</Tag>}
    </span>
  );

  return (
    <Card
      title={title}
      size="small"
      style={{ marginBottom: 12 }}
      bodyStyle={{ maxHeight: 300, overflow: 'auto' }}
    >
      <Spin spinning={loading}>
        {data.length === 0 ? (
          <Empty description="暂无待办提醒" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <List
            size="small"
            dataSource={data}
            renderItem={item => (
              <List.Item
                actions={[
                  <Button
                    size="small"
                    type="primary"
                    onClick={() => handleAck(item.id)}
                  >
                    已完成
                  </Button>
                ]}
              >
                <List.Item.Meta
                  title={item.reminder_name || '提醒事项'}
                  description={
                    <div>
                      {item.content && <div style={{ marginBottom: 4 }}>{item.content}</div>}
                      <div style={{ fontSize: 12, color: '#8c8c8c' }}>
                        {item.date_key} {item.sent_at || ''}
                      </div>
                    </div>
                  }
                />
              </List.Item>
            )}
          />
        )}
      </Spin>
    </Card>
  );
}
