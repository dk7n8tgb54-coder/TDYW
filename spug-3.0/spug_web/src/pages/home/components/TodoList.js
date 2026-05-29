/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { List, Button, Space, Tag, Popconfirm } from 'antd';
import { EditOutlined, DeleteOutlined, CheckOutlined } from '@ant-design/icons';
import moment from 'moment';

const getPriorityColor = (priority) => {
  const map = { high: 'red', medium: 'orange', low: 'green' };
  return map[priority] || 'default';
};

const getPriorityText = (priority) => {
  const map = { high: '高', medium: '中', low: '低' };
  return map[priority] || priority;
};

export default function TodoList({ records, onEdit, onDelete, onComplete }) {
  return (
    <List
      style={{ minHeight: 400, maxHeight: 400, overflowY: 'auto' }}
      dataSource={records}
      renderItem={(item, index) => (
        <List.Item
          key={item.id}
          style={{
            padding: '12px 0',
            borderBottom: index < records.length - 1 ? '1px solid #f0f0f0' : 'none'
          }}
        >
          <List.Item.Meta
            avatar={
              item.status === 'completed' ? (
                <CheckOutlined style={{ color: '#52c41a', fontSize: 16 }} />
              ) : (
                <div
                  style={{
                    width: 16,
                    height: 16,
                    border: '2px solid #d9d9d9',
                    borderRadius: '50%',
                    cursor: 'pointer'
                  }}
                  onClick={() => onComplete(item)}
                />
              )
            }
            title={
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span
                  style={{
                    textDecoration: item.status === 'completed' ? 'line-through' : 'none',
                    color: item.status === 'completed' ? '#999' : 'inherit'
                  }}
                >
                  {item.title}
                </span>
                <Tag color={getPriorityColor(item.priority)}>
                  {getPriorityText(item.priority)}
                </Tag>
              </div>
            }
            description={
              <div>
                {item.description && (
                  <div style={{ marginBottom: 4, color: '#666' }}>{item.description}</div>
                )}
                {item.due_date && (
                  <div style={{ fontSize: 12, color: '#999' }}>
                    截止: {moment(item.due_date).format('YYYY-MM-DD HH:mm')}
                  </div>
                )}
              </div>
            }
          />
          <Space>
            {item.status !== 'completed' && (
              <Button type="link" size="small" icon={<EditOutlined />} onClick={() => onEdit(item)}>
                编辑
              </Button>
            )}
            <Popconfirm title="确定删除?" onConfirm={() => onDelete(item)} okText="确定" cancelText="取消">
              <Button type="link" size="small" danger icon={<DeleteOutlined />}>删除</Button>
            </Popconfirm>
          </Space>
        </List.Item>
      )}
    />
  );
}
