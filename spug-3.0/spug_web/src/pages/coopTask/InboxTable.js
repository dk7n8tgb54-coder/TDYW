/**
 * 待我交付的任务列表（交付科室视角）
 */
import React, {useState, useEffect, useCallback} from 'react';
import {observer} from 'mobx-react';
import {Table, Tag, Space, Badge} from 'antd';
import {http} from 'libs';
import {ASSIGNMENT_STATUS_MAP, TASK_STATUS_MAP} from './utils';

export default function InboxTable(props) {
  const {onOpenDetail} = props;
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState([]);

  const fetchData = useCallback(() => {
    setLoading(true);
    http.get('/api/coop-task/inbox/')
      .then(list => setData(list || []))
      .catch(() => setData([]))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const columns = [
    {
      title: '任务标题', dataIndex: 'task_title', key: 'task_title',
      render: (text, record) => (
        <Badge dot={record.has_unread_urge} offset={[4, 0]}>
          <a onClick={() => onOpenDetail(record)}>{text}</a>
        </Badge>
      ),
    },
    {title: '发起人', dataIndex: 'created_by_name', key: 'created_by_name', width: 100},
    {title: '经办人', dataIndex: 'contact_user_name', key: 'contact_user_name', width: 90,
      render: v => v || '-'},
    {
      title: '交付进度', dataIndex: 'aggregate_status', key: 'aggregate_status', width: 110,
      render: s => {
        const t = ASSIGNMENT_STATUS_MAP[s] || {color: 'default', text: s};
        return <Tag color={t.color}>{t.text}</Tag>;
      },
    },
    {
      title: '截止时间', dataIndex: 'deadline', key: 'deadline', width: 150,
      render: (text, record) => (
        <Space size={4}>
          {text}
          {record.is_overdue && <Tag color="red">已逾期</Tag>}
        </Space>
      ),
    },
    {
      title: '任务状态', dataIndex: 'task_status', key: 'task_status', width: 90,
      render: s => {
        const t = TASK_STATUS_MAP[s] || {color: 'default', text: s};
        return <Tag color={t.color}>{t.text}</Tag>;
      },
    },
    {
      title: '催办', dataIndex: 'urge_count', key: 'urge_count', width: 110,
      render: (v, record) => (
        record.has_unread_urge
          ? <Tag color="red">催办 {v || 0} 次</Tag>
          : (v ? `${v} 次` : '-')
      ),
    },
    {title: '操作', key: 'action', width: 100,
      render: (_, record) => <a onClick={() => onOpenDetail(record)}>去交付</a>},
  ];

  return (
    <Table
      rowKey="id"
      loading={loading}
      columns={columns}
      dataSource={data}
      pagination={false}
    />
  );
}
