/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 系统详情——配置变更历史页签。
 * 每次保存记录变更人、时间、来源及字段前后值；字段/组成项停用或删除后历史保留。
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Table, Tag, Timeline, Collapse } from 'antd';
import store from './store';
import { SOURCE_TEXT, ACTION_TEXT } from './constants';

const {Panel} = Collapse;

const SOURCE_COLOR = {
  system: 'blue',
  config: 'green',
  component: 'orange',
  field_definition: 'purple',
};

@observer
class ChangeHistoryTab extends React.Component {
  componentDidMount() {
    store.fetchChanges();
  }

  renderChanges(changes) {
    if (!changes || !changes.length) {
      return <span style={{color: '#999'}}>无字段级差异</span>;
    }
    return (
      <Timeline style={{margin: '8px 0 0'}}>
        {changes.map((c, idx) => (
          <Timeline.Item key={idx}>
            <b>{c.label}</b>
            <span style={{marginLeft: 8}}>
              {c.old !== '' && <Tag>原值: {c.old || '(空)'}</Tag>}
              <Tag color="blue">新值: {c.new || '(空)'}</Tag>
            </span>
          </Timeline.Item>
        ))}
      </Timeline>
    );
  }

  render() {
    return (
      <div>
        <Table
          rowKey="id"
          size="small"
          loading={store.isChangesFetching}
          dataSource={store.changes}
          columns={[{
            title: '变更时间', dataIndex: 'changed_at', width: 170,
          }, {
            title: '变更人', dataIndex: 'changed_by_name', width: 110,
          }, {
            title: '来源', dataIndex: 'source', width: 120,
            render: v => <Tag color={SOURCE_COLOR[v] || 'default'}>{SOURCE_TEXT[v] || v}</Tag>,
          }, {
            title: '动作', dataIndex: 'action', width: 120,
            render: v => ACTION_TEXT[v] || v,
          }, {
            title: '变更内容',
            render: (text, record) => this.renderChanges(record.changes),
          }]}
          pagination={{
            current: store.changesPage,
            pageSize: 10,
            total: store.changesTotal,
            showTotal: t => `共 ${t} 条`,
            onChange: (page) => {
              store.changesPage = page;
              store.fetchChanges();
            },
          }}
          locale={{emptyText: '暂无变更历史'}}
        />
      </div>
    );
  }
}

export default ChangeHistoryTab;
