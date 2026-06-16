/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
import React, { useState, useEffect } from 'react';
import { observer } from 'mobx-react';
import { Table, Tag, Button, Space, message, Popconfirm, Badge } from 'antd';
import { CheckOutlined, CheckCircleOutlined } from '@ant-design/icons';
import { http, hasPermission } from 'libs';
import store from './store';

const REMIND_TYPE_MAP = {
  expiring_45: {color: 'blue', text: '45天提醒'},
  expiring_30: {color: 'cyan', text: '30天提醒'},
  expiring_15: {color: 'orange', text: '15天提醒'},
  expiring_7: {color: 'volcano', text: '7天提醒'},
  expiring_1: {color: 'red', text: '1天提醒'},
  expired: {color: 'red', text: '已过期'},
};

export default observer(function ReminderList({ licenseId }) {
  const [reminders, setReminders] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (licenseId) {
      fetchReminders();
    }
  }, [licenseId]);

  function fetchReminders() {
    setLoading(true);
    http.get(`/api/radio-license/reminders/`, {params: {page_size: 50}})
      .then(({records}) => {
        // 只显示该执照的提醒（to_view 返回 license_id）
        setReminders(records.filter(r => r.license_id === licenseId));
      })
      .catch(e => {
        console.error('[电台执照] 获取提醒列表失败:', e);
      })
      .finally(() => setLoading(false));
  }

  function handleRead(r) {
    http.post('/api/radio-license/reminders/handle/', {id: r.id, action: 'read'})
      .then(() => {
        message.success('已标记为已读');
        fetchReminders();
      })
      .catch(e => message.error(e?.message || '操作失败'));
  }

  function handleHandle(r) {
    http.post('/api/radio-license/reminders/handle/', {id: r.id, action: 'handle'})
      .then(() => {
        message.success('已标记为已处理');
        fetchReminders();
      })
      .catch(e => message.error(e?.message || '操作失败'));
  }

  const columns = [
    {
      title: '类型',
      dataIndex: 'remind_type',
      key: 'remind_type',
      width: 110,
      render: type => {
        const info = REMIND_TYPE_MAP[type] || {color: 'default', text: type};
        return <Tag color={info.color}>{info.text}</Tag>;
      },
    },
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      ellipsis: true,
    },
    {
      title: '内容',
      dataIndex: 'content',
      key: 'content',
      ellipsis: true,
    },
    {
      title: '剩余天数',
      dataIndex: 'days_left',
      key: 'days_left',
      width: 90,
      render: v => v < 0
        ? <span style={{color: '#ff4d4f'}}>已过期{Math.abs(v)}天</span>
        : <span style={{color: v <= 15 ? '#fa8c16' : '#52c41a'}}>{v}天</span>,
    },
    {
      title: '提醒日期',
      dataIndex: 'remind_date',
      key: 'remind_date',
      width: 110,
    },
    {
      title: '状态',
      key: 'status',
      width: 120,
      render: (_, r) => (
        <Space>
          {r.is_read ? <Tag color="default">已读</Tag> : <Tag color="processing">未读</Tag>}
          {r.is_handled ? <Tag color="success">已处理</Tag> : <Tag color="warning">待处理</Tag>}
        </Space>
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 140,
      render: (_, r) => (
        <Space>
          {!r.is_read && hasPermission('radio_license.reminder.handle') && (
            <Button type="link" size="small" icon={<CheckOutlined />} onClick={() => handleRead(r)}>
              已读
            </Button>
          )}
          {!r.is_handled && hasPermission('radio_license.reminder.handle') && (
            <Button type="link" size="small" icon={<CheckCircleOutlined />} onClick={() => handleHandle(r)}>
              已处理
            </Button>
          )}
        </Space>
      ),
    },
  ];

  return (
    <Table
      columns={columns}
      dataSource={reminders}
      rowKey="id"
      loading={loading}
      size="small"
      pagination={false}
      locale={{emptyText: '暂无提醒记录'}}
    />
  );
})
