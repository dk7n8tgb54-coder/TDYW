/**
 * 提醒事项管理
 *
 * 列表 + 新建/编辑/删除提醒规则。仅持权限码可访问。
 * 列表可查看今日各接收人的确认状态。
 */
import React, { useState, useEffect, useCallback } from 'react';
import { Breadcrumb, AuthDiv } from 'components';
import { Table, Button, Tag, Space, Switch, Popconfirm, notification, Tooltip } from 'antd';
import { PlusOutlined, InfoCircleOutlined } from '@ant-design/icons';
import { http } from 'libs';
import ReminderFormModal from './ReminderFormModal';
import ReminderStatusModal from './ReminderStatusModal';

const API_BASE = '/api/reminder/';

const REPEAT_LABELS = {
  none: '不重复', daily: '每天', weekly: '每周', monthly: '每月', yearly: '每年',
};

function formatRepeat(record) {
  if (!record.repeat_type || record.repeat_type === 'none') return '不重复';
  const label = REPEAT_LABELS[record.repeat_type] || record.repeat_type;
  const n = record.repeat_interval || 1;
  if (n === 1) return label;
  return `每${n}${record.repeat_type === 'daily' ? '天' : record.repeat_type === 'weekly' ? '周' : record.repeat_type === 'monthly' ? '月' : '年'}`;
}

function ReminderAdmin() {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState([]);
  const [users, setUsers] = useState([]);
  const [formVisible, setFormVisible] = useState(false);
  const [editing, setEditing] = useState(null);
  const [statusVisible, setStatusVisible] = useState(false);

  const fetchData = useCallback(() => {
    setLoading(true);
    http.get(API_BASE)
      .then(list => setData(Array.isArray(list) ? list : []))
      .catch(() => setData([]))
      .finally(() => setLoading(false));
  }, []);

  const fetchUsers = useCallback(() => {
    http.get(`${API_BASE}users/`)
      .then(list => setUsers(Array.isArray(list) ? list : []))
      .catch(() => setUsers([]));
  }, []);

  useEffect(() => { fetchData(); fetchUsers(); }, [fetchData, fetchUsers]);

  const openCreate = () => { setEditing(null); setFormVisible(true); };
  const openEdit = (record) => { setEditing(record); setFormVisible(true); };

  const doDelete = (record) => {
    http.delete(`${API_BASE}${record.id}/`)
      .then(() => { notification.success({ message: '已删除' }); fetchData(); })
      .catch(e => notification.error({ message: '删除失败', description: e.message || String(e) }));
  };

  const toggleEnabled = (record) => {
    http.patch(`${API_BASE}${record.id}/`, {
      name: record.name,
      enabled: !record.enabled,
      target_date: record.target_date,
      repeat_type: record.repeat_type || 'none',
      repeat_interval: record.repeat_interval || 1,
      content: record.content || '',
      recipient_users: JSON.stringify(record.recipient_users || []),
    })
      .then(() => { fetchData(); })
      .catch(e => notification.error({ message: '操作失败', description: e.message || String(e) }));
  };

  const columns = [
    {
      title: '事件名称', dataIndex: 'name', key: 'name', width: 180,
      render: (text, record) => (
        <Space size={4}>
          <span>{text}</span>
          {!record.enabled && <Tag>已停用</Tag>}
        </Space>
      ),
    },
    {
      title: '目标日', dataIndex: 'target_date', key: 'target_date', width: 120,
    },
    {
      title: '重复', key: 'repeat', width: 100,
      render: (_, r) => formatRepeat(r),
    },
    {
      title: '接收人', key: 'recipients', width: 100,
      render: (_, r) => {
        const count = (r.recipient_users || []).length;
        return (
          <Tooltip title={(r.recipient_users || []).map(u => u.nickname).join('、')}>
            <span>{count} 人</span>
          </Tooltip>
        );
      },
    },
    {
      title: '启用', key: 'enabled', width: 70,
      render: (_, r) => (
        <Switch size="small" checked={r.enabled} onChange={() => toggleEnabled(r)} />
      ),
    },
    {
      title: '操作', key: 'actions', width: 140,
      render: (_, r) => (
        <Space>
          <a onClick={() => openEdit(r)}>编辑</a>
          <Popconfirm title="确定删除该提醒规则？" onConfirm={() => doDelete(r)}>
            <a style={{ color: '#ff4d4f' }}>删除</a>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <AuthDiv auth="home.reminder.view">
      <Breadcrumb>
        <Breadcrumb.Item>提醒事项</Breadcrumb.Item>
      </Breadcrumb>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between' }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建提醒规则</Button>
        <Button icon={<InfoCircleOutlined />} onClick={() => setStatusVisible(true)}>今日确认状态</Button>
      </div>
      <Table
        rowKey="id"
        loading={loading}
        dataSource={data}
        columns={columns}
        pagination={false}
      />

      <ReminderFormModal
        visible={formVisible}
        editing={editing}
        users={users}
        onCancel={() => { setFormVisible(false); setEditing(null); }}
        onSuccess={() => { setFormVisible(false); setEditing(null); fetchData(); }}
      />
      <ReminderStatusModal
        visible={statusVisible}
        onCancel={() => setStatusVisible(false)}
      />
    </AuthDiv>
  );
}

export default ReminderAdmin;
