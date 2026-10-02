/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——运行记录重复问题面板（2026-10 第二版，详情抽屉页签）。
 * - 相似记录：同系统、发生时间窗口内（默认前后 30 天）、排除已关联；
 * - 关联/取消关联：仅建立"相似/重复"标记，保留原始记录，不合并、
 *   不自动生成故障或履历；方向（关联/被关联到）双向可见；
 * - 标记重复发生：手动标记（is_repeated），已关闭/已转故障由后端拒绝；
 * - 错误由 http 拦截器统一提示，业务代码不重复提示。
 */
import React, { useState } from 'react';
import { observer } from 'mobx-react';
import { Table, Tag, Button, Input, Popconfirm, Switch, Empty, Typography } from 'antd';
import { AuthButton } from 'components';
import store from './store';
import { PERM, RUNTIME_STATUS_TEXT, RUNTIME_STATUS_COLOR } from '../constants';

const similarColumns = (onLink) => [{
  title: '编号',
  dataIndex: 'record_no',
  width: 140,
}, {
  title: '标题',
  dataIndex: 'title',
  ellipsis: true,
}, {
  title: '发生时间',
  dataIndex: 'occurred_at',
  width: 140,
}, {
  title: '状态',
  dataIndex: 'status',
  width: 90,
  render: text => <Tag color={RUNTIME_STATUS_COLOR[text]}>{RUNTIME_STATUS_TEXT[text]}</Tag>,
}, {
  title: '操作',
  width: 80,
  render: (text, record) => (
    <LinkButton record={record} onLink={onLink}/>
  ),
}];

function LinkButton({record, onLink}) {
  const [note, setNote] = useState('');
  const [inputVisible, setInputVisible] = useState(false);
  if (!inputVisible) {
    return (
      <AuthButton
        auth={PERM.RUNTIME_LINK}
        type="link"
        size="small"
        style={{padding: 0}}
        onClick={() => setInputVisible(true)}
      >
        关联
      </AuthButton>
    );
  }
  return (
    <div style={{whiteSpace: 'nowrap'}}>
      <Input
        size="small"
        style={{width: 140, marginRight: 4}}
        value={note}
        onChange={e => setNote(e.target.value)}
        placeholder="关联说明（选填）"
      />
      <Button
        size="small"
        type="primary"
        loading={store.isActionSubmitting}
        onClick={() => {
          onLink(record.id, note.trim());
          setNote('');
          setInputVisible(false);
        }}
      >
        确认
      </Button>
    </div>
  );
}

const linkColumns = (onUnlink) => [{
  title: '方向',
  dataIndex: 'direction_text',
  width: 90,
  render: (text) => <Tag>{text}</Tag>,
}, {
  title: '对端记录',
  key: 'other_record',
  ellipsis: true,
  render: (text, record) => {
    const other = record.other_record || {};
    return (
      <span>
        {other.record_no} {other.title}
      </span>
    );
  },
}, {
  title: '说明',
  dataIndex: 'note',
  width: 180,
  ellipsis: true,
  render: text => text || '-',
}, {
  title: '关联人',
  dataIndex: 'created_by_name',
  width: 110,
}, {
  title: '操作',
  width: 90,
  render: (text, record) => (
    <Popconfirm
      title="确定取消该关联吗？原始记录不受影响。"
      onConfirm={() => onUnlink(record.id)}
    >
      <AuthButton
        auth={PERM.RUNTIME_LINK}
        type="link"
        size="small"
        style={{padding: 0}}
      >
        取消关联
      </AuthButton>
    </Popconfirm>
  ),
}];

// observer 包裹：读取 duplicateLinks/similarRecords 等 observable
const DuplicatePanel = observer(function DuplicatePanel({editable}) {
  const d = store.detail;
  return (
    <div>
      <div style={{marginBottom: 8}}>
        <span style={{marginRight: 8}}>重复发生：</span>
        <Switch
          checked={!!d.is_repeated}
          disabled={!editable}
          checkedChildren="是"
          unCheckedChildren="否"
          onChange={checked => {
            // 状态以服务端回读为准；错误提示由 http 拦截器统一弹出
            store.markRepeated(checked).catch(() => {});
          }}
        />
        <Typography.Text type="secondary" style={{marginLeft: 12, fontSize: 12}}>
          手动标记是否重复发生；关联相似记录不会自动置位。
        </Typography.Text>
      </div>
      <Typography.Title level={5} style={{marginTop: 12}}>已关联记录</Typography.Title>
      <Table
        rowKey="id"
        size="small"
        loading={store.isLinksFetching}
        pagination={false}
        dataSource={store.duplicateLinks}
        columns={linkColumns(linkId => {
          store.unlinkDuplicate(linkId).catch(() => {});
        })}
        locale={{emptyText: <Empty description="暂无关联记录" image={Empty.PRESENTED_IMAGE_SIMPLE}/>}}
      />
      <Typography.Title level={5} style={{marginTop: 16}}>相似记录（同系统，前后 30 天）</Typography.Title>
      <Table
        rowKey="id"
        size="small"
        loading={store.isSimilarFetching}
        pagination={false}
        dataSource={store.similarRecords}
        columns={similarColumns((duplicateId, note) => {
          store.linkDuplicate(duplicateId, note).catch(() => {});
        })}
        locale={{emptyText: <Empty description="未发现相似记录" image={Empty.PRESENTED_IMAGE_SIMPLE}/>}}
      />
    </div>
  );
});

export default DuplicatePanel;
