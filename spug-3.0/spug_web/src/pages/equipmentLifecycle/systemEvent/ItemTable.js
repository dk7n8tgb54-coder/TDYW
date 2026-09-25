/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——系统履历事项表格（系统分组内）。
 * 一个业务事项只展示一条主记录；展开行按需加载完整节点时间线
 * （含归并进来的台账转换节点），加载/失败/空状态完整处理。
 * 来源列跳转由来源页面独立重新校验权限与租户。
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Table, Tag, Timeline, Spin, Empty } from 'antd';
import { history } from 'libs';
import store, { itemKey } from './groupStore';
import {
  EVENT_TYPE_COLOR, EVENT_TYPE_TEXT, ITEM_STATUS_COLOR,
  SOURCE_TYPE_TEXT, buildSourceHref, formatDateTime, formatDuration,
} from './constants';

function renderSourceLink(record) {
  const text = SOURCE_TYPE_TEXT[record.source_type] || record.source_type;
  const label = record.item_no || record.source_no ? `${text} ${record.item_no || record.source_no}` : text;
  const href = buildSourceHref(record);
  if (!href) return label || '-';
  return <a onClick={() => history.push(href)}>{label}</a>;
}

const ItemNodes = observer(({systemId, record}) => {
  const key = itemKey(systemId, record.source_type, record.source_id);
  const state = store.itemNodes[key];
  if (!state || state.status === 'loading') {
    return <Spin size="small"/>;
  }
  if (state.status === 'failed') {
    return (
      <div>
        <span style={{color: '#999'}}>节点加载失败，</span>
        <a onClick={() => store.loadItemNodes(systemId, record.source_type, record.source_id)}>
          重试
        </a>
      </div>
    );
  }
  if (!state.nodes.length) {
    return <Empty description="暂无节点记录" image={Empty.PRESENTED_IMAGE_SIMPLE}/>;
  }
  return (
    <Timeline>
      {state.nodes.map(node => (
        <Timeline.Item key={node.id}>
          <span style={{marginRight: 8}}>{formatDateTime(node.occurred_at)}</span>
          <Tag color={EVENT_TYPE_COLOR[node.event_type]}>
            {EVENT_TYPE_TEXT[node.event_type] || node.event_type}
          </Tag>
          <span style={{marginRight: 8}}>{node.title}</span>
          {renderSourceLink(node)}
          {node.created_by_name ? (
            <span style={{marginLeft: 8, color: '#999'}}>{node.created_by_name}</span>
          ) : null}
        </Timeline.Item>
      ))}
    </Timeline>
  );
});

function renderDuration(record) {
  if (record.source_type !== 'fault') return '-';
  if (record.duration_seconds === null || record.duration_seconds === undefined) {
    return <Tag color="orange">进行中</Tag>;
  }
  return formatDuration(record.duration_seconds);
}

@observer
class ItemTable extends React.Component {
  columns = [{
    title: '事项类型',
    dataIndex: 'event_type',
    width: 95,
    render: (text) => <Tag color={EVENT_TYPE_COLOR[text]}>{EVENT_TYPE_TEXT[text] || text}</Tag>,
  }, {
    title: '事项编号',
    key: 'item_no',
    width: 180,
    render: (text, record) => renderSourceLink(record),
  }, {
    title: '当前状态',
    key: 'status',
    width: 100,
    render: (text, record) => record.status_text ? (
      <Tag color={ITEM_STATUS_COLOR[record.status] || 'default'}>{record.status_text}</Tag>
    ) : '-',
  }, {
    title: '事项摘要',
    key: 'title',
    ellipsis: true,
    render: (text, record) => (
      <span>
        {record.level_text ? (
          <Tag color="red" style={{marginRight: 6}}>{record.level_text}</Tag>
        ) : null}
        {record.title}
      </span>
    ),
  }, {
    title: '首次发生',
    dataIndex: 'first_occurred_at',
    width: 140,
    render: (text) => formatDateTime(text),
  }, {
    title: '最近更新',
    dataIndex: 'last_occurred_at',
    width: 140,
    render: (text) => formatDateTime(text),
  }, {
    title: '持续时间',
    key: 'duration',
    width: 110,
    render: (text, record) => renderDuration(record),
  }, {
    title: '节点数',
    dataIndex: 'node_count',
    width: 70,
  }, {
    title: '来源台账',
    key: 'ledger_sources',
    width: 160,
    render: (text, record) => (
      record.ledger_sources && record.ledger_sources.length ? (
        record.ledger_sources.map((source, index) => (
          <Tag key={index} color="orange">{source.ledger_no}</Tag>
        ))
      ) : '-'
    ),
  }];

  render() {
    const {group} = this.props;
    const systemId = group.system.id;
    return (
      <Table
        rowKey={record => `${record.source_type}:${record.source_id}`}
        size="small"
        pagination={false}
        dataSource={group.items}
        columns={this.columns}
        expandable={{
          onExpand: (expanded, record) => store.onItemExpand(expanded, record, systemId),
          expandedRowRender: record => <ItemNodes systemId={systemId} record={record}/>,
          rowExpandable: record => Boolean(record.source_id),
        }}
        locale={{emptyText: <Empty description="暂无履历事项" image={Empty.PRESENTED_IMAGE_SIMPLE}/>}}
      />
    );
  }
}

export default ItemTable;
