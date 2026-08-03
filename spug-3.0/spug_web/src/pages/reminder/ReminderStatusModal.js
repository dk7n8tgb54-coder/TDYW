import React, { useState, useEffect } from 'react';
import { Modal, Table, Tag, Space, Progress } from 'antd';
import { http } from 'libs';

const API_BASE = '/api/reminder/';

export default function ReminderStatusModal({ visible, onCancel }) {
  const [statusData, setStatusData] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!visible) return;
    setLoading(true);
    http.get(`${API_BASE}status/`)
      .then(list => setStatusData(Array.isArray(list) ? list : []))
      .catch(() => setStatusData([]))
      .finally(() => setLoading(false));
  }, [visible]);

  return (
    <Modal
      title="今日确认状态"
      visible={visible}
      onCancel={onCancel}
      footer={null}
      width={720}
    >
      <Table
        rowKey="id"
        loading={loading}
        dataSource={statusData}
        pagination={false}
        expandable={{
          expandedRowRender: (record) => (
            <Table
              rowKey="id"
              dataSource={record.recipients || []}
              pagination={false}
              size="small"
              columns={[
                { title: '姓名', dataIndex: 'nickname', key: 'nickname' },
                {
                  title: '状态', key: 'is_acked', width: 120,
                  render: (_, r) => r.is_acked
                    ? <Tag color="green">已确认</Tag>
                    : <Tag color="orange">未确认</Tag>,
                },
                { title: '确认时间', dataIndex: 'acked_at', key: 'acked_at', width: 180 },
              ]}
            />
          ),
        }}
        columns={[
          { title: '事件名称', dataIndex: 'name', key: 'name' },
          {
            title: '确认进度', key: 'progress', width: 200,
            render: (_, r) => {
              const pct = r.total > 0 ? Math.round(r.acked / r.total * 100) : 0;
              return (
                <Space>
                  <Progress percent={pct} size="small" style={{ width: 120 }} />
                  <span>{r.acked}/{r.total}</span>
                </Space>
              );
            },
          },
        ]}
      />
    </Modal>
  );
}
